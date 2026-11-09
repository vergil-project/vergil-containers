"""Select the images a change affects, for PR CI (epic
vergil-project/.github#213, task T5).

A PR builds and scans only the `matrix.json` entries its change reaches.
`select_entries` returns them, in the head matrix's order, as the union of:

1. the full set, when a changed path matches `FULL_GLOBS`: an input of every
   image, or of the build-and-scan pipeline itself;
2. the matrix diff: every head entry that is new or differs from the base
   matrix (a lifecycle add, a build-args change; a dropped entry selects
   nothing);
3. the graph: every entry of each manifest entry whose
   `includes.dependency_map` inputs match a changed path;

and then every descendant of a selected entry (an entry built FROM it, at any
depth), since a rebuilt parent changes its children.

A path that reaches no image (`NO_BUILD_GLOBS`) selects nothing. Any other path
under `docker/` is unclassified and fails closed: it selects the full set and
is named in a `::warning::`. Globs match repo-relative POSIX paths with
`fnmatch`, so `*` also matches `/`.

CLI: `selection.py --base-matrix <file> --head-matrix <file> --changed-files
<file>` (one path per line) prints `{"include": [...]}`, `{"include": []}` when
nothing is selected. Warnings go to stderr; any bad input exits 2 with an
`::error::`, never a partial selection."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable
from fnmatch import fnmatchcase
from pathlib import Path

import generate as gen
import includes
import manifest as mf

# Inputs of every image, or of the build-and-scan pipeline: the Dockerfile
# expander, the publish and PR workflows, and the Trivy scan and gate with
# their configuration. A scan-config change is re-proved by scanning every
# image.
FULL_GLOBS = (
    "docker/generate.sh",
    ".github/workflows/cd-docker-publish.yml",
    ".github/workflows/ci.yml",
    "scripts/bin/trivy-*",
    ".trivyignore",
    "trivy.yaml",
    ".trivy/**",
)

# Paths that are no image's input, or are re-checked by another CI job.
# `manifest.yml` and `matrix.json` reach the images through the matrix diff
# (and the regenerated templates, which the graph sees).
NO_BUILD_GLOBS = (
    "docs/**",
    "*.md",
    "docker/pins/**",
    "docker/versions/*.py",
    "docker/versions/test*/**",
    "docker/versions/fixtures/**",
    "docker/versions/manifest.yml",
    "docker/versions/matrix.json",
    "docker/versions/window.json",
    "docker/build.sh",
    ".hadolint.yaml",
    "cliff*.toml",
    "vergil.toml",
    ".github/**",
    "scripts/**",
)

_KEYS = ("language", "version", "build-args", "parent", "depth")


class SelectionError(ValueError):
    """A matrix or the changed-file list is malformed."""


def _matches(path: str, globs: Iterable[str]) -> bool:
    return any(fnmatchcase(path, glob) for glob in globs)


def _include(matrix: object, which: str) -> list[dict]:
    include = matrix.get("include") if isinstance(matrix, dict) else None
    if not isinstance(include, list) or not all(isinstance(e, dict) for e in include):
        raise SelectionError(f"{which} matrix: `include` must be a list of mappings")
    return include


def _key(e: dict) -> tuple[str, str]:
    return (e["language"], e["version"])


def _head_entries(matrix: object) -> list[dict]:
    include = _include(matrix, "head")
    seen: set[tuple[str, str]] = set()
    for index, e in enumerate(include):
        where = f"head matrix include[{index}]"
        if sorted(e) != sorted(_KEYS):
            raise SelectionError(f"{where}: must be a mapping of exactly {', '.join(_KEYS)}")
        if not isinstance(e["language"], str) or not isinstance(e["version"], str):
            raise SelectionError(f"{where}: language and version must be strings")
        parent = e["parent"]
        if parent is not None and (
            not isinstance(parent, dict) or sorted(parent) != ["language", "version"]
        ):
            raise SelectionError(f"{where}: parent must be null or a mapping of language and version")
        if _key(e) in seen:
            raise SelectionError(f"{where}: duplicate entry {e['language']}:{e['version']}")
        seen.add(_key(e))
    return include


def _warn(message: str) -> None:
    print(f"::warning::{message}", file=sys.stderr)


def select_entries(
    root: Path,
    changed: Iterable[str],
    base_matrix: dict,
    head_matrix: dict,
    warn: Callable[[str], None] = _warn,
) -> list[dict]:
    """The `head_matrix` entries to build for a change to `changed`
    (repo-relative paths), in `head_matrix` order. See the module docstring.
    Raises SelectionError on a malformed matrix; ManifestError and IncludeError
    from the dependency graph propagate."""
    head = _head_entries(head_matrix)
    base = _include(base_matrix, "base")
    graph = includes.dependency_map(root)

    full = False
    selected: set[tuple[str, str]] = {_key(e) for e in head if e not in base}
    families: set[str] = set()
    unclassified: list[str] = []
    for path in changed:
        if _matches(path, FULL_GLOBS):
            full = True
            continue
        reached = {key for key, inputs in graph.items() if _matches(path, inputs)}
        if reached:
            families |= reached
        elif not _matches(path, NO_BUILD_GLOBS) and path.startswith("docker/"):
            unclassified.append(path)
    if unclassified:
        warn(f"unclassified path(s) under docker/, building every image: {', '.join(unclassified)}")
        full = True
    if full:
        return list(head)

    selected |= {_key(e) for e in head if e["language"] in families}
    # Descendants: an entry whose parent is selected is selected, at any depth.
    grew = True
    while grew:
        grew = False
        for e in head:
            parent = e["parent"]
            if _key(e) not in selected and parent is not None and (
                (parent["language"], parent["version"]) in selected
            ):
                selected.add(_key(e))
                grew = True
    return [e for e in head if _key(e) in selected]


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise SelectionError(f"cannot read {path}: {exc}") from exc


def _read_changed(path: Path) -> list[str]:
    try:
        text = path.read_text()
    except OSError as exc:
        raise SelectionError(f"cannot read {path}: {exc}") from exc
    return [line for line in text.splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-matrix", type=Path, required=True, help="the PR base's matrix.json")
    parser.add_argument("--head-matrix", type=Path, required=True, help="the PR head's matrix.json")
    parser.add_argument("--changed-files", type=Path, required=True, help="changed paths, one per line")
    parser.add_argument("--root", type=Path, default=gen.ROOT, help="repo root (default: this checkout)")
    args = parser.parse_args(argv)
    try:
        picked = select_entries(
            args.root.resolve(),
            _read_changed(args.changed_files),
            _read_json(args.base_matrix),
            _read_json(args.head_matrix),
        )
    except (SelectionError, includes.IncludeError, mf.ManifestError) as exc:
        print(f"::error title=Image selection failed::{exc}", file=sys.stderr)
        return 2
    print(json.dumps({"include": picked}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
