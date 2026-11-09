"""Every script a caller runs declares its third-party dependencies inline
(PEP 723) and is run with plain `uv run` (epic vergil-project/.github#649,
Task 3).

An entry point that imports pyyaml without declaring it works only while the
interpreter happens to carry pyyaml; these tests make a missing declaration
fail PR CI instead of a nightly job. Library modules the entry points import
(`manifest.py`, `lifecycle/adapters/go.py`, ...) carry no block: PEP 723 applies
only to the script `uv run` is given, so each entry point names its full import
closure, including what it reaches through local modules.
"""
from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCKER = REPO / "docker"

# Entry point (repo-relative) -> the distributions its PEP 723 block declares.
ENTRY_POINTS: dict[str, list[str]] = {
    "docker/pins/check_pins.py": ["pyyaml"],
    "docker/pins/generate_catalog.py": ["pyyaml"],
    "docker/pins/report_exposure.py": ["packaging", "pyyaml"],
    "docker/versions/generate.py": ["pyyaml"],
    "docker/versions/selection.py": ["pyyaml"],
    "docker/versions/lifecycle/check.py": ["pyyaml"],
    "docker/versions/lifecycle/publish.py": ["pyyaml"],
}

# Import name -> distribution name, where they differ.
DISTRIBUTIONS = {"yaml": "pyyaml"}

# Directories a local module is imported from: each script's own directory is
# on sys.path, and report_exposure.py and lifecycle/*.py add docker/versions.
LOCAL_ROOTS = [DOCKER / "pins", DOCKER / "versions"]

# The reference regex from PEP 723.
_BLOCK_RE = re.compile(
    r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$"
)


def script_metadata(path: Path) -> dict:
    blocks = [m for m in _BLOCK_RE.finditer(path.read_text()) if m.group("type") == "script"]
    assert len(blocks) == 1, f"{path}: expected one PEP 723 `script` block, found {len(blocks)}"
    content = "".join(
        line[2:] if line.startswith("# ") else line[1:]
        for line in blocks[0].group("content").splitlines(keepends=True)
    )
    return tomllib.loads(content)


def _local_module(name: str) -> Path | None:
    parts = name.split(".")
    for root in LOCAL_ROOTS:
        base = root.joinpath(*parts)
        for candidate in (base.with_suffix(".py"), base / "__init__.py"):
            if candidate.is_file():
                return candidate
    return None


def _imported_modules(path: Path) -> set[str]:
    """Every module `path` imports, anywhere in the file (lazy imports in
    functions included), as absolute dotted names."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path}:{node.lineno}: relative import not handled"
            assert node.module is not None
            names.add(node.module)
            # `from pkg import mod` imports a submodule when `mod` is one.
            names.update(
                f"{node.module}.{alias.name}"
                for alias in node.names
                if _local_module(f"{node.module}.{alias.name}") is not None
            )
    return names


def third_party_closure(entry: Path) -> set[str]:
    """The distributions `entry` needs: every non-stdlib, non-local top-level
    module it imports, directly or through local modules under docker/."""
    found: set[str] = set()
    seen: set[Path] = set()
    pending = [entry]
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        for name in _imported_modules(path):
            top = name.split(".")[0]
            if top == "__future__" or top in sys.stdlib_module_names:
                continue
            # Importing a.b.c runs a/__init__.py and a/b/__init__.py too.
            parts = name.split(".")
            local = [_local_module(".".join(parts[: i + 1])) for i in range(len(parts))]
            if local[0] is None:
                found.add(DISTRIBUTIONS.get(top, top))
                continue
            assert all(local), f"{path}: cannot resolve local import {name}"
            pending.extend(p for p in local if p is not None)
    return found


def test_each_entry_point_has_a_pep723_block():
    for rel, deps in ENTRY_POINTS.items():
        meta = script_metadata(REPO / rel)
        assert sorted(meta.get("dependencies", [])) == sorted(deps), rel


def test_declared_deps_cover_imports():
    for rel in ENTRY_POINTS:
        path = REPO / rel
        declared = set(script_metadata(path).get("dependencies", []))
        assert third_party_closure(path) == declared, rel


def test_closure_finds_imports_through_local_modules():
    # generate.py imports pyyaml only through manifest.py, and check.py reaches
    # lifecycle/adapters/go.py only through a lazy `from lifecycle.adapters
    # import ADAPTERS` and the package's __init__.py.
    assert "pyyaml" in third_party_closure(DOCKER / "versions" / "generate.py")
    assert third_party_closure(DOCKER / "versions" / "lifecycle" / "check.py") == {"pyyaml"}


def test_no_caller_runs_an_entry_point_with_python3():
    names = "|".join(re.escape(Path(rel).name) for rel in ENTRY_POINTS)
    pattern = re.compile(rf"\bpython3?(\s+-\S+)*\s+[\"']?\S*?\b({names})\b")
    offenders = []
    for top in ("scripts", "docker", ".github"):
        for path in sorted((REPO / top).rglob("*")):
            if not path.is_file() or path == Path(__file__).resolve():
                continue
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(REPO)}:{lineno}: {line.strip()}")
    assert not offenders, "run these with `uv run`:\n" + "\n".join(offenders)
