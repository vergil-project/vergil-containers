"""Plan docker/build.sh's local builds from docker/versions/matrix.json, in the
publish workflow's tier order (vergil-containers#773, epic
vergil-project/.github#213 T7b).

With no family named, every matrix entry is built, shallowest tier first. With
families named, every version of each is built, after the entries they are
built FROM (their parents, transitively), so `build.sh python` gets its parents
first. Standard library only: build.sh runs on the host.

Each output line is tab-separated:

    <role> <language> <version> <parent> <build-args>

`role` is `build` (an entry asked for) or `parent` (needed only as a parent, so
build.sh may pull it instead). `parent` is `<language>:<version>` or `-`, and
`build-args` is space-separated `NAME=value` pairs or `-`. Any malformed matrix
or unknown family exits 2 with an error, never a partial plan."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MATRIX = Path(__file__).resolve().parent / "matrix.json"
_KEYS = ["language", "version", "build-args", "parent", "depth"]
_WORD_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
_ARG_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_ARG_VALUE_RE = re.compile(r"^[^\s=]+$")


class PlanError(ValueError):
    """matrix.json is malformed, or a named family is not in it."""


def _word(where: str, field: str, value: object) -> str:
    if not isinstance(value, str) or not _WORD_RE.match(value):
        raise PlanError(f"{where}: {field} {value!r} is not a valid name")
    return value


def _entry(index: int, data: object) -> dict:
    where = f"matrix.json include[{index}]"
    if not isinstance(data, dict) or sorted(data) != sorted(_KEYS):
        raise PlanError(f"{where}: must be a mapping of exactly {', '.join(_KEYS)}")
    _word(where, "language", data["language"])
    _word(where, "version", data["version"])
    args = data["build-args"]
    if not isinstance(args, dict):
        raise PlanError(f"{where}: build-args must be a mapping")
    for name, value in args.items():
        if not _ARG_NAME_RE.match(name) or not isinstance(value, str) or not _ARG_VALUE_RE.match(value):
            raise PlanError(f"{where}: build-args {name!r}: {value!r} is not a valid build argument")
    parent = data["parent"]
    if parent is not None:
        if not isinstance(parent, dict) or sorted(parent) != ["language", "version"]:
            raise PlanError(f"{where}: parent must be null or a mapping of language and version")
        _word(where, "parent language", parent["language"])
        _word(where, "parent version", parent["version"])
    depth = data["depth"]
    if type(depth) is not int or depth < 0:
        raise PlanError(f"{where}: depth {depth!r} must be a non-negative integer")
    return data


def load(path: Path) -> list[dict]:
    """The matrix entries, validated, in depth order (stable)."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise PlanError(f"cannot read {path}: {exc}") from exc
    include = data.get("include") if isinstance(data, dict) else None
    if not isinstance(include, list) or not include:
        raise PlanError(f"{path}: `include` must be a non-empty list")
    entries = [_entry(i, e) for i, e in enumerate(include)]
    by_key: dict[tuple[str, str], dict] = {}
    for e in entries:
        if _key(e) in by_key:
            raise PlanError(f"{path}: duplicate entry {_name(_key(e))}")
        by_key[_key(e)] = e
    # Every parent is another entry in a shallower tier, so building in depth
    # order always builds a parent before its children (and there is no cycle).
    for e in entries:
        if e["parent"] is None:
            continue
        pkey = _parent_key(e)
        if pkey not in by_key:
            raise PlanError(f"{_name(_key(e))}: parent {_name(pkey)} is not in {path}")
        if by_key[pkey]["depth"] >= e["depth"]:
            raise PlanError(f"{_name(_key(e))}: parent {_name(pkey)} is not in a shallower tier")
    return sorted(entries, key=lambda e: e["depth"])


def _key(e: dict) -> tuple[str, str]:
    return (e["language"], e["version"])


def _parent_key(e: dict) -> tuple[str, str]:
    return (e["parent"]["language"], e["parent"]["version"])


def _name(key: tuple[str, str]) -> str:
    return f"{key[0]}:{key[1]}"


def plan(entries: list[dict], families: list[str]) -> list[tuple[str, dict]]:
    """(role, entry) pairs in build order, from `load`'s entries. See the
    module docstring."""
    if not families:
        return [("build", e) for e in entries]
    known = sorted({e["language"] for e in entries})
    unknown = [f for f in families if f not in known]
    if unknown:
        raise PlanError(f"unknown family {', '.join(map(repr, unknown))} (matrix.json has {', '.join(known)})")
    by_key = {_key(e): e for e in entries}
    wanted = {_key(e) for e in entries if e["language"] in families}
    needed = set(wanted)
    for key in wanted:
        entry = by_key[key]
        while entry["parent"] is not None:
            entry = by_key[_parent_key(entry)]
            needed.add(_key(entry))
    return [("build" if _key(e) in wanted else "parent", e) for e in entries if _key(e) in needed]


def line(role: str, e: dict) -> str:
    parent = e["parent"]
    args = " ".join(f"{name}={value}" for name, value in e["build-args"].items())
    return "\t".join([
        role, e["language"], e["version"],
        f"{parent['language']}:{parent['version']}" if parent else "-",
        args or "-",
    ])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("families", nargs="*", help="families to build (default: every matrix entry)")
    parser.add_argument("--matrix", type=Path, default=MATRIX, help="matrix.json (default: this checkout's)")
    args = parser.parse_args(argv)
    try:
        steps = plan(load(args.matrix), args.families)
    except PlanError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for role, entry in steps:
        print(line(role, entry))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
