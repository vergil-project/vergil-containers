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

# The unversioned base image is a manifest entry, but not a language family: it
# has its own optional `base:` section, which holds only its parent.
BASE_KEY = "base"
BASE_VERSION = "latest"
# The deepest image tree the publish workflow builds (cd-docker-publish.yml runs
# one tier per depth): `pkg-ubuntu` 0, `base` 1, language images 2.
MAX_DEPTH = 2

_TOP_KEYS = {"schema", "families"}
_TOP_OPTIONAL = {"base"}
_BASE_OPTIONAL = {"parent"}
_FAMILY_KEYS = {"key", "language", "token_prefix", "build_arg", "automation", "versions"}
_FAMILY_OPTIONAL = {"parent"}
_PARENT_KEYS = {"name", "version"}
_VERSION_KEYS = {"version", "ga", "eol", "in_policy", "runtime_published"}

_KEY_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_LANGUAGE_RE = re.compile(r"^[a-z0-9]+$")
_PREFIX_RE = re.compile(r"^([a-z]+-)?$")
_BUILD_ARG_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_VERSION_RE = re.compile(r"^\d+(\.\d+)?$")
# A parent's version is a family version, or `base`'s "latest".
_PARENT_VERSION_RE = re.compile(r"^(\d+(\.\d+)?|latest)$")

HEADER = (
    "# Version manifest: the single source of truth for every language version\n"
    "# this repo builds (epic vergil-project/.github#407).\n"
    "#\n"
    "# Every other version list is generated from this file. After editing it, run\n"
    "#   uv run docker/versions/generate.py\n"
    "# and commit the regenerated files. CI fails if they are out of date.\n"
    "#\n"
    "# Families are image suffixes (dev-<key>); versions are newest first.\n"
    "#\n"
    "# `ga` and `eol` hold the dates the family's lifecycle adapter records\n"
    "# (docker/versions/lifecycle/adapters/): `ga` is the date the version became\n"
    "# eligible under the family's GA rule, and `eol` is upstream's end of support.\n"
    "# A null `ga` or `eol` is intentional: upstream publishes no such date. Go and\n"
    "# Rust end a release's support when a later release ships, not on a date;\n"
    "# LLVM publishes no EOL; GCC closes a series without announcing a date.\n"
    "#\n"
    "# A family may name a `parent:` (another entry's `name` and one of its\n"
    "# `version`s) that its image is built FROM, and an optional top-level `base:`\n"
    "# section names base's. No parent means an upstream image. The publish builds\n"
    "# in tiers by depth in that tree, at most 2 deep (vergil-containers#773).\n"
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
class Parent:
    """The manifest entry an image is built `FROM`: a family key or `base`, at
    one of its versions."""
    name: str  # "base", "pkg-ubuntu"
    version: str  # "latest", "24.04"


@dataclass(frozen=True)
class Family:
    key: str  # image suffix: "python", "cpp-clang", "ts-node"
    language: str  # vergil primary-language: "python", "cpp", "typescript"
    token_prefix: str  # "", "clang-", "gcc-", "node-"
    build_arg: str  # "PYTHON_VERSION", "CLANG_VERSION", "NODE_MAJOR"
    automation: Literal["pr", "report"]
    versions: tuple[ManifestVersion, ...]  # newest first
    parent: Parent | None = None  # None: built on an upstream image


@dataclass(frozen=True)
class Manifest:
    families: tuple[Family, ...]
    base_parent: Parent | None = None  # `base`'s parent; None: an upstream image


def version_sort_key(version: str) -> tuple[int, ...]:
    """Semantic order of a version, ignoring any family prefix ("clang-20").

    Mirrors vergil-tooling's `_version_sort_key`: the runs of digits decide the
    order, so "3.14" sorts above "3.9" and "node-24" above "node-22"."""
    return tuple(int(n) for n in re.findall(r"\d+", version))


def _check_keys(where: str, data: dict, allowed: set[str], optional: frozenset[str] | set[str] = frozenset()) -> None:
    unknown = sorted(set(data) - allowed - set(optional))
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


def _parse_parent(where: str, data: object) -> Parent:
    where = f"{where}: parent"
    if not isinstance(data, dict):
        raise ManifestError(f"{where}: must be a mapping of name and version")
    _check_keys(where, data, _PARENT_KEYS)
    return Parent(
        name=_string(where, "name", data["name"], _KEY_RE),
        version=_string(where, "version", data["version"], _PARENT_VERSION_RE),
    )


def _parse_base(data: object) -> Parent | None:
    if not isinstance(data, dict):
        raise ManifestError("base: must be a mapping")
    _check_keys("base", data, set(), _BASE_OPTIONAL)
    return _parse_parent("base", data["parent"]) if "parent" in data else None


def _parse_family(index: int, data: object) -> Family:
    if not isinstance(data, dict):
        raise ManifestError(f"families[{index}]: must be a mapping")
    name = data.get("key")
    where = f"family {name!r}" if isinstance(name, str) else f"families[{index}]"
    _check_keys(where, data, _FAMILY_KEYS, _FAMILY_OPTIONAL)
    key = _string(where, "key", data["key"], _KEY_RE)
    if key == BASE_KEY:
        raise ManifestError(f"{where}: key: {BASE_KEY!r} is reserved for the base image")
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
        parent=_parse_parent(where, data["parent"]) if "parent" in data else None,
    )


def entry_depths(m: Manifest) -> dict[str, int]:
    """Each manifest entry's depth in the image tree, keyed by entry name (every
    family key, then `base`): 0 for an entry with no parent, else its parent's
    depth plus one.

    Raises ManifestError naming the entry when its parent does not exist (or not
    at that version), when the parents form a cycle, or when the depth exceeds
    MAX_DEPTH. `parse_manifest` runs it, so a loaded manifest always passes."""
    entries: dict[str, tuple[str, Parent | None, tuple[str, ...]]] = {
        f.key: (f"family {f.key!r}", f.parent, tuple(v.version for v in f.versions)) for f in m.families
    }
    entries[BASE_KEY] = (BASE_KEY, m.base_parent, (BASE_VERSION,))
    depths: dict[str, int] = {}
    for name, (where, _, _) in entries.items():
        chain = [name]
        current = name
        while True:
            parent = entries[current][1]
            if parent is None:
                break
            if parent.name not in entries:
                raise ManifestError(f"{entries[current][0]}: parent: no manifest entry {parent.name!r}")
            if parent.version not in entries[parent.name][2]:
                raise ManifestError(
                    f"{entries[current][0]}: parent: {parent.name!r} has no version {parent.version!r}"
                )
            if parent.name in chain:
                cycle = chain[chain.index(parent.name):] + [parent.name]
                raise ManifestError(f"{entries[cycle[0]][0]}: parent: cycle {' -> '.join(cycle)}")
            chain.append(parent.name)
            current = parent.name
        depth = len(chain) - 1
        if depth > MAX_DEPTH:
            raise ManifestError(f"{where}: parent: depth {depth} exceeds the maximum of {MAX_DEPTH}")
        depths[name] = depth
    return depths


def parse_manifest(data: object) -> Manifest:
    """Validate already-parsed YAML data and build a Manifest."""
    if not isinstance(data, dict):
        raise ManifestError("manifest: top level must be a mapping")
    _check_keys("manifest", data, _TOP_KEYS, _TOP_OPTIONAL)
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
    base_parent = _parse_base(data["base"]) if "base" in data else None
    m = Manifest(families=families, base_parent=base_parent)
    entry_depths(m)
    return m


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


def _dump_parent(p: Parent, indent: str) -> list[str]:
    return [
        f"{indent}parent:",
        f"{indent}  name: {_scalar(p.name)}",
        f"{indent}  version: {_scalar(p.version)}",
    ]


def dump_manifest(m: Manifest) -> str:
    """Stable YAML for `m`; `load_manifest` of the result returns `m`."""
    lines = [HEADER.rstrip("\n"), f"schema: {SCHEMA}"]
    if m.base_parent is not None:
        lines += ["base:", *_dump_parent(m.base_parent, "  ")]
    lines.append("families:")
    for f in m.families:
        lines += [
            f"  - key: {_scalar(f.key)}",
            f"    language: {_scalar(f.language)}",
            f"    token_prefix: {_scalar(f.token_prefix)}",
            f"    build_arg: {_scalar(f.build_arg)}",
            f"    automation: {_scalar(f.automation)}",
        ]
        if f.parent is not None:
            lines += _dump_parent(f.parent, "    ")
        lines.append("    versions:")
        for v in f.versions:
            lines += [
                f"      - version: {_scalar(v.version)}",
                f"        ga: {_scalar(v.ga)}",
                f"        eol: {_scalar(v.eol)}",
                f"        in_policy: {_scalar(v.in_policy)}",
                f"        runtime_published: {_scalar(v.runtime_published)}",
            ]
    return "\n".join(lines) + "\n"
