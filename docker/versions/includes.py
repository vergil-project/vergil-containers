"""Derive each image's build inputs from its `@include` directives
(epic vergil-project/.github#213, task T2).

`docker/generate.sh` expands a `docker/<key>/Dockerfile.template` into its
Dockerfile by replacing every `# @include <path>` line (a path relative to
`docker/`) with the fragment's own expansion; fragments nest. This module reads
the same directives, so the set of files an image is built from is derived from
the templates rather than maintained by hand. PR CI's selector (T5) maps a
change to the images it reaches with `dependency_map`.

There are no language branches here: the entries come from the manifest, and
everything else from each entry's files under `docker/`."""
from __future__ import annotations

import os
import re
from pathlib import Path

import generate as gen
import manifest as mf

# The directive shape generate.sh honours: `^# @include (.+)$`, matched against
# a whole line.
_INCLUDE_RE = re.compile(r"# @include (.+)")
TEMPLATE = "Dockerfile.template"


class IncludeError(ValueError):
    """An `@include` does not resolve. The message names the file and line."""


def _rel(path: Path, repo: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return str(path)


def _expand(file: Path, docker: Path, stack: tuple[Path, ...], found: set[str]) -> None:
    repo = docker.parent
    try:
        text = file.read_text()
    except OSError as exc:
        raise IncludeError(f"{_rel(file, repo)}: cannot read: {exc}") from exc
    for number, line in enumerate(text.split("\n"), start=1):
        match = _INCLUDE_RE.fullmatch(line)
        if match is None:
            continue
        where = f"{_rel(file, repo)}:{number}"
        target = os.path.normpath(match.group(1))
        if os.path.isabs(target) or target == ".." or target.startswith(".." + os.sep):
            raise IncludeError(f"{where}: @include {match.group(1)!r} is outside docker/")
        fragment = docker / target
        if not fragment.is_file():
            raise IncludeError(f"{where}: @include {match.group(1)!r}: no such file {_rel(fragment, repo)}")
        if fragment in stack:
            cycle = " -> ".join(_rel(p, repo) for p in (*stack[stack.index(fragment):], fragment))
            raise IncludeError(f"{where}: @include cycle {cycle}")
        found.add(_rel(fragment, repo))
        _expand(fragment, docker, (*stack, fragment), found)


def fragments_of(template: Path) -> frozenset[str]:
    """Every fragment `template` includes, directly or through another fragment,
    as repo-relative paths ("docker/common/validation-tools.dockerfile").

    `template` is `<repo>/docker/<key>/Dockerfile.template`; include paths
    resolve against its `docker/` directory, as in generate.sh. Raises
    IncludeError naming the file and line when an include does not resolve to
    an existing file under `docker/` or the includes form a cycle, and naming
    the template when it cannot be read."""
    docker = template.parent.parent
    found: set[str] = set()
    _expand(template, docker, (template,), found)
    return frozenset(found)


def _own_inputs(root: Path, key: str, smoke_dir: str | None) -> frozenset[str]:
    inputs = {f"docker/{key}/**", *fragments_of(root / "docker" / key / TEMPLATE)}
    if smoke_dir is not None:
        inputs.add(f"docker/{smoke_dir}/**")
    return frozenset(inputs)


def dependency_map(root: Path) -> dict[str, frozenset[str]]:
    """Each manifest entry (every family key, then `base`) mapped to its build
    inputs as repo-relative globs or paths: its `docker/<key>/**` context, every
    fragment its template includes, its smoke-test directory when it has one
    (the rule `generate.smoke_test_dir` gives build.sh, e.g. `docker/cpp/**` for
    both C++ families), and, transitively, every input of its manifest parent.

    The manifest is `<root>/docker/versions/manifest.yml`; ManifestError and
    IncludeError propagate."""
    m = mf.load_manifest(root / gen.MANIFEST)
    own = {f.key: _own_inputs(root, f.key, gen.smoke_test_dir(root, f)) for f in m.families}
    own[mf.BASE_KEY] = _own_inputs(root, mf.BASE_KEY, None)
    parents = {f.key: f.parent for f in m.families}
    parents[mf.BASE_KEY] = m.base_parent
    # load_manifest has already refused a missing parent and a cycle, so every
    # chain below ends at an entry with no parent.
    result: dict[str, frozenset[str]] = {}
    for key in own:
        inputs = set(own[key])
        parent = parents[key]
        while parent is not None:
            inputs |= own[parent.name]
            parent = parents[parent.name]
        result[key] = frozenset(inputs)
    return result
