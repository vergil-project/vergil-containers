"""Group PR CI's selected images into build jobs (epic
vergil-project/.github#213, task T6'; vergil-containers#514).

PR CI never pushes an image, so a child cannot be built FROM a parent built in
another job. Every selected entry whose parent is not also selected starts a
job, and the job builds it and then every selected entry built FROM it, at any
depth, parents first. A child whose parent is not selected builds on the
parent's published `dev-` image. Each job runs once per architecture, on that
architecture's native runner (no emulation).

`jobs` returns the matrix rows. Each row has `name`, `arch`, `runner` and
`entries`: the job's matrix entries, each with three more keys:

- `smoke`: the directory under docker/ whose smoke-test.sh runs on the image,
  or null (the rule `generate.smoke_test_dir` gives build.sh);
- `parent-local`: whether its parent is built earlier in the same job;
- `push-local`: whether an entry later in the job is built FROM it.

CLI: `pr_jobs.py --selected <file>` reads selection.py's `{"include": [...]}`
and prints `{"include": [<row>, ...]}`, `{"include": []}` when nothing is
selected. Any bad input exits 2 with an `::error::`, never a partial matrix."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import generate as gen
import manifest as mf

# vergil-tooling lib/package/matrix.py RUNNERS: the native runner per arch, as
# the publish workflow uses.
RUNNERS = (("amd64", "ubuntu-24.04"), ("arm64", "ubuntu-24.04-arm"))


class JobsError(ValueError):
    """The selection is malformed or names an entry the manifest lacks."""


def smoke_dirs(root: Path) -> dict[str, str | None]:
    """Each manifest entry's smoke-test directory under docker/, or None.
    ManifestError propagates."""
    m = mf.load_manifest(root / gen.MANIFEST)
    dirs: dict[str, str | None] = {f.key: gen.smoke_test_dir(root, f) for f in m.families}
    dirs[mf.BASE_KEY] = None
    return dirs


def _key(e: dict) -> tuple[str, str]:
    return (e["language"], e["version"])


def _name(key: tuple[str, str]) -> str:
    return f"{key[0]}:{key[1]}"


def _parent_key(e: dict) -> tuple[str, str] | None:
    parent = e["parent"]
    return None if parent is None else (parent["language"], parent["version"])


def _check(selected: object) -> list[dict]:
    if not isinstance(selected, list):
        raise JobsError("the selection must be a list of matrix entries")
    for index, e in enumerate(selected):
        if not isinstance(e, dict) or not isinstance(e.get("language"), str) or not isinstance(
                e.get("version"), str):
            raise JobsError(f"selection include[{index}]: not a matrix entry")
        parent = e.get("parent")
        if parent is not None and (not isinstance(parent, dict) or sorted(parent) != ["language", "version"]):
            raise JobsError(f"selection include[{index}]: parent must be null or a mapping of language and version")
        if type(e.get("depth")) is not int:
            raise JobsError(f"selection include[{index}]: depth must be an integer")
    return selected


def jobs(selected: list[dict], smoke: dict[str, str | None]) -> list[dict]:
    """The build jobs for `selected` (matrix entries), one per selected tree
    root and architecture, in selection order. See the module docstring."""
    entries = _check(selected)
    by_key: dict[tuple[str, str], dict] = {}
    for e in entries:
        if _key(e) in by_key:
            raise JobsError(f"duplicate entry {_name(_key(e))}")
        if e["language"] not in smoke:
            raise JobsError(f"{_name(_key(e))}: no manifest entry {e['language']!r}")
        by_key[_key(e)] = e

    def root_of(e: dict) -> tuple[str, str]:
        key = _key(e)
        seen = {key}
        while (pkey := _parent_key(by_key[key])) in by_key:
            if pkey in seen:
                raise JobsError(f"{_name(_key(e))}: its parents form a cycle")
            seen.add(pkey)
            key = pkey
        return key

    groups: dict[tuple[str, str], list[dict]] = {}
    for e in entries:
        groups.setdefault(root_of(e), []).append(e)
    parents = {_parent_key(e) for e in entries}

    rows = []
    for root, members in groups.items():
        # Parents first: a parent is always shallower than its children.
        members = sorted(members, key=lambda e: e["depth"])
        job_entries = [
            {**e, "smoke": smoke[e["language"]],
             "parent-local": _parent_key(e) in by_key,
             "push-local": _key(e) in parents}
            for e in members
        ]
        name = _name(root)
        if len(members) > 1:
            name += f" + {len(members) - 1} descendants"
        for arch, runner in RUNNERS:
            rows.append({"name": name, "arch": arch, "runner": runner, "entries": job_entries})
    return rows


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--selected", type=Path, required=True, help="selection.py's output")
    parser.add_argument("--root", type=Path, default=gen.ROOT, help="repo root (default: this checkout)")
    args = parser.parse_args(argv)
    try:
        try:
            data = json.loads(args.selected.read_text())
        except (OSError, ValueError) as exc:
            raise JobsError(f"cannot read {args.selected}: {exc}") from exc
        if not isinstance(data, dict) or "include" not in data:
            raise JobsError(f"{args.selected}: not a selection (no `include`)")
        rows = jobs(data["include"], smoke_dirs(args.root.resolve()))
    except (JobsError, mf.ManifestError) as exc:
        print(f"::error title=Image build jobs failed::{exc}", file=sys.stderr)
        return 2
    print(json.dumps({"include": rows}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
