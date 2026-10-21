"""Load and dump the version manifest, the single source of truth for every
language version this repo builds (epic vergil-project/.github#407, spec §6.1).

`manifest.yml` records what is built: one family per image suffix, each with its
versions newest first. Every other version list in the repo is generated from it
by `generate.py`. Loading is strict: any schema violation raises ManifestError
naming the family and field, never a partial or defaulted manifest.

There are no language branches here. The language names that appear in
`manifest.yml` are data, not code paths."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import yaml

SCHEMA = 1
AUTOMATIONS = ("pr", "report")

_TOP_KEYS = {"schema", "families"}
_FAMILY_KEYS = {"key", "language", "token_prefix", "build_arg", "automation", "versions"}
_VERSION_KEYS = {"version", "ga", "eol", "in_policy", "runtime_published"}

_KEY_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_LANGUAGE_RE = re.compile(r"^[a-z0-9]+$")
_PREFIX_RE = re.compile(r"^([a-z]+-)?$")
_BUILD_ARG_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_VERSION_RE = re.compile(r"^\d+(\.\d+)?$")

HEADER = (
    "# Version manifest: the single source of truth for every language version\n"
    "# this repo builds (epic vergil-project/.github#407).\n"
    "#\n"
    "# Every other version list is generated from this file. After editing it, run\n"
    "#   python3 docker/versions/generate.py\n"
    "# and commit the regenerated files. CI fails if they are out of date.\n"
    "#\n"
    "# Families are image suffixes (dev-<key>); versions are newest first.\n"
)


class ManifestError(ValueError):
    """The manifest violates its schema. The message names the family and field."""


@dataclass(frozen=True)
class ManifestVersion:
    version: str  # "3.14", "20", "1.26"
    ga: date | None
    eol: date | None
    in_policy: bool
    runtime_published: bool | None  # None for languages with no runtime package


@dataclass(frozen=True)
class Family:
    key: str  # image suffix: "python", "cpp-clang", "ts-node"
    language: str  # vergil primary-language: "python", "cpp", "typescript"
    token_prefix: str  # "", "clang-", "gcc-", "node-"
    build_arg: str  # "PYTHON_VERSION", "CLANG_VERSION", "NODE_MAJOR"
    automation: Literal["pr", "report"]
    versions: tuple[ManifestVersion, ...]  # newest first


@dataclass(frozen=True)
class Manifest:
    families: tuple[Family, ...]


def version_sort_key(version: str) -> tuple[int, ...]:
    """Semantic order of a version, ignoring any family prefix ("clang-20").

    Mirrors vergil-tooling's `_version_sort_key`: the runs of digits decide the
    order, so "3.14" sorts above "3.9" and "node-24" above "node-22"."""
    return tuple(int(n) for n in re.findall(r"\d+", version))


def _check_keys(where: str, data: dict, allowed: set[str]) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ManifestError(f"{where}: unknown key(s) {', '.join(map(repr, unknown))}")
    missing = sorted(allowed - set(data))
    if missing:
        raise ManifestError(f"{where}: missing key(s) {', '.join(map(repr, missing))}")


def _string(where: str, field: str, value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise ManifestError(f"{where}: {field} {value!r} must match {pattern.pattern}")
    return value


def _date(where: str, field: str, value: object) -> date | None:
    if value is None:
        return None
    # PyYAML reads an unquoted ISO date as datetime.date; accept a quoted ISO
    # string too. A datetime (with a time part) is not a date.
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ManifestError(f"{where}: {field} {value!r} must be an ISO date (YYYY-MM-DD) or null")


def _bool(where: str, field: str, value: object, *, nullable: bool) -> bool | None:
    if value is None and nullable:
        return None
    if not isinstance(value, bool):
        allowed = "true, false or null" if nullable else "true or false"
        raise ManifestError(f"{where}: {field} {value!r} must be {allowed}")
    return value


def _parse_version(family: str, index: int, data: object) -> ManifestVersion:
    where = f"family {family!r}: versions[{index}]"
    if not isinstance(data, dict):
        raise ManifestError(f"{where}: must be a mapping")
    _check_keys(where, data, _VERSION_KEYS)
    return ManifestVersion(
        version=_string(where, "version", data["version"], _VERSION_RE),
        ga=_date(where, "ga", data["ga"]),
        eol=_date(where, "eol", data["eol"]),
        in_policy=bool(_bool(where, "in_policy", data["in_policy"], nullable=False)),
        runtime_published=_bool(
            where, "runtime_published", data["runtime_published"], nullable=True
        ),
    )


def _parse_family(index: int, data: object) -> Family:
    if not isinstance(data, dict):
        raise ManifestError(f"families[{index}]: must be a mapping")
    name = data.get("key")
    where = f"family {name!r}" if isinstance(name, str) else f"families[{index}]"
    _check_keys(where, data, _FAMILY_KEYS)
    key = _string(where, "key", data["key"], _KEY_RE)
    automation = data["automation"]
    if automation not in AUTOMATIONS:
        raise ManifestError(
            f"{where}: automation {automation!r} must be one of {', '.join(AUTOMATIONS)}"
        )
    raw_versions = data["versions"]
    if not isinstance(raw_versions, list) or not raw_versions:
        raise ManifestError(f"{where}: versions must be a non-empty list")
    versions = tuple(_parse_version(key, i, v) for i, v in enumerate(raw_versions))
    seen: set[str] = set()
    for v in versions:
        if v.version in seen:
            raise ManifestError(f"{where}: versions: duplicate version {v.version!r}")
        seen.add(v.version)
    for newer, older in zip(versions, versions[1:]):
        if version_sort_key(newer.version) <= version_sort_key(older.version):
            raise ManifestError(
                f"{where}: versions must be newest first, "
                f"but {newer.version!r} is listed before {older.version!r}"
            )
    return Family(
        key=key,
        language=_string(where, "language", data["language"], _LANGUAGE_RE),
        token_prefix=_string(where, "token_prefix", data["token_prefix"], _PREFIX_RE),
        build_arg=_string(where, "build_arg", data["build_arg"], _BUILD_ARG_RE),
        automation=automation,
        versions=versions,
    )


def parse_manifest(data: object) -> Manifest:
    """Validate already-parsed YAML data and build a Manifest."""
    if not isinstance(data, dict):
        raise ManifestError("manifest: top level must be a mapping")
    _check_keys("manifest", data, _TOP_KEYS)
    if data["schema"] != SCHEMA:
        raise ManifestError(f"manifest: schema {data['schema']!r} is not supported (want {SCHEMA})")
    raw_families = data["families"]
    if not isinstance(raw_families, list) or not raw_families:
        raise ManifestError("manifest: families must be a non-empty list")
    families = tuple(_parse_family(i, f) for i, f in enumerate(raw_families))
    seen: set[str] = set()
    for f in families:
        if f.key in seen:
            raise ManifestError(f"family {f.key!r}: key: duplicate family")
        seen.add(f.key)
    return Manifest(families=families)


def load_manifest(path: Path) -> Manifest:
    """Read and validate `path`. Raises ManifestError on any schema violation."""
    try:
        text = path.read_text()
    except OSError as exc:
        raise ManifestError(f"manifest: cannot read {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"manifest: {path} is not valid YAML: {exc}") from exc
    return parse_manifest(data)


def _scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    # A JSON string is a valid YAML double-quoted scalar.
    return json.dumps(value)


def dump_manifest(m: Manifest) -> str:
    """Stable YAML for `m`; `load_manifest` of the result returns `m`."""
    lines = [HEADER.rstrip("\n"), f"schema: {SCHEMA}", "families:"]
    for f in m.families:
        lines += [
            f"  - key: {_scalar(f.key)}",
            f"    language: {_scalar(f.language)}",
            f"    token_prefix: {_scalar(f.token_prefix)}",
            f"    build_arg: {_scalar(f.build_arg)}",
            f"    automation: {_scalar(f.automation)}",
            "    versions:",
        ]
        for v in f.versions:
            lines += [
                f"      - version: {_scalar(v.version)}",
                f"        ga: {_scalar(v.ga)}",
                f"        eol: {_scalar(v.eol)}",
                f"        in_policy: {_scalar(v.in_policy)}",
                f"        runtime_published: {_scalar(v.runtime_published)}",
            ]
    return "\n".join(lines) + "\n"
