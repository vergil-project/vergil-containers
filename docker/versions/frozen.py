"""Frozen inputs for the version-lifecycle tests (vergil-containers#654).

The tests assert exact version lists ("add 3.15 gives 3.15, 3.14, 3.13, 3.12").
They used to read the live `docker/versions/manifest.yml`, so every add or drop
PR the lifecycle automation opened broke its own CI. They now read
`testdata/manifest.yml`, a snapshot that does not change when the real manifest
does, and a repo tree whose generated files match it.

The one check on the real manifest (it loads, is canonical, and the generated
files are up to date) is `test_generate.test_real_manifest_is_valid`; it asserts
no version list.
"""
import functools
import shutil
import tempfile
from pathlib import Path

import generate as g
import manifest as mf

HERE = Path(__file__).resolve().parent
LIVE_ROOT = HERE.parent.parent
MANIFEST = HERE / "testdata" / "manifest.yml"
SEED = mf.load_manifest(MANIFEST)


class FrozenRepoError(Exception):
    """The frozen repo tree could not be built consistently."""


def make_repo(dest: Path) -> Path:
    """Build at `dest` a copy of every file the generator reads or writes, with
    the frozen manifest in place of the live one and every generated block
    regenerated from it. Hand-written content (templates, workflow, docs prose)
    comes from the live checkout; only the version data is frozen."""
    rels = {g.MANIFEST, g.MATRIX_JSON, g.WINDOW_JSON, g.BUILD_SH, g.PACKAGE_CLEANUP, *g.DOC_TABLES}
    rels |= {Path("docker") / d / "Dockerfile.template" for d in (g.BASE_KEY, *(f.key for f in SEED.families))}
    rels |= {p.relative_to(LIVE_ROOT) for p in (LIVE_ROOT / "docker").glob("*/smoke-test.sh")}
    for rel in rels:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LIVE_ROOT / rel, dest / rel)
    shutil.copy2(MANIFEST, dest / g.MANIFEST)
    for path, content in g.render_all(SEED, dest).items():
        path.write_text(content)
    stale = [p for p, c in g.render_all(mf.load_manifest(dest / g.MANIFEST), dest).items() if p.read_text() != c]
    if stale:
        raise FrozenRepoError(f"the frozen repo at {dest} is not consistent with {MANIFEST}: {stale}")
    return dest


@functools.cache
def _root_dir() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="frozen-repo-")


@functools.cache
def root() -> Path:
    """A shared, read-only frozen repo tree (built once per test run, removed at
    exit). Tests that write to the tree must use `make_repo(tmp_path)` instead."""
    return make_repo(Path(_root_dir().name))
