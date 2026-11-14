"""Frozen inputs for the version-lifecycle tests (vergil-containers#654).

The tests assert exact version lists ("add 3.15 gives 3.15, 3.14, 3.13, 3.12").
They used to read the live `docker/versions/manifest.yml`, so every add or drop
PR the lifecycle automation opened broke its own CI. They now read
`testdata/manifest.yml`, a snapshot that does not change when the real manifest
does, and a repo tree whose generated files match it. The pins report tests
(`docker/pins/test_report.py`, vergil-containers#656) read their image matrix
from the same frozen tree. `testdata/toolchains.yml` freezes the toolchain pins
the matrix embeds (epic vergil-project/.github#649) the same way.

The one check on the real manifest (it loads, is canonical, and the generated
files are up to date) is `test_generate.test_real_manifest_is_valid`; it asserts
no version list.
"""
import functools
import shutil
import tempfile
from pathlib import Path

import generate as g  # first: it puts docker/pins on the import path
import generate_catalog
import manifest as mf
import resolve_toolchains as rt

HERE = Path(__file__).resolve().parent
LIVE_ROOT = HERE.parent.parent
MANIFEST = HERE / "testdata" / "manifest.yml"
SEED = mf.load_manifest(MANIFEST)
TOOLCHAINS = HERE / "testdata" / "toolchains.yml"
PINS = rt.load_toolchains(TOOLCHAINS)
CATALOG = Path("docker/pins/CATALOG.md")


class FrozenRepoError(Exception):
    """The frozen repo tree could not be built consistently."""


def make_repo(dest: Path) -> Path:
    """Build at `dest` a copy of every file the generator reads or writes, with
    the frozen manifest in place of the live one and every generated block
    regenerated from it. Hand-written content (templates, workflow, docs prose)
    comes from the live checkout; only the version data is frozen. The pin
    catalog's inputs (`pins.yml` and the `docker/common` fragments) are
    copied too, and `CATALOG.md` is rendered from the frozen pins, so a
    lifecycle change rendered on the tree has every file it compares against."""
    rels = {g.MANIFEST, g.MATRIX_JSON, g.WINDOW_JSON, g.BUILD_SH, g.PACKAGE_CLEANUP, g.PACKAGE_CACHE_WARM, *g.DOC_TABLES}
    rels |= {Path("docker") / d / "Dockerfile.template" for d in (g.BASE_KEY, *(f.key for f in SEED.families))}
    rels |= {p.relative_to(LIVE_ROOT) for p in (LIVE_ROOT / "docker").glob("*/smoke-test.sh")}
    rels |= {Path("docker/pins/pins.yml")}
    rels |= {p.relative_to(LIVE_ROOT) for p in (LIVE_ROOT / "docker" / "common").glob("*.dockerfile")}
    for rel in rels:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LIVE_ROOT / rel, dest / rel)
    shutil.copy2(MANIFEST, dest / g.MANIFEST)
    (dest / g.TOOLCHAINS).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TOOLCHAINS, dest / g.TOOLCHAINS)
    render_tree(dest, SEED, PINS)
    stale = [p for p, c in g.render_all(mf.load_manifest(dest / g.MANIFEST), dest, PINS).items() if p.read_text() != c]
    if stale:
        raise FrozenRepoError(f"the frozen repo at {dest} is not consistent with {MANIFEST}: {stale}")
    return dest


def render_tree(dest: Path, m: mf.Manifest, pins: rt.Toolchains) -> None:
    """Regenerate every generated file of the tree at `dest` (one `make_repo`
    built) from `m` and `pins`: each generated block and `CATALOG.md`. A test
    that writes its own manifest and pins to the tree calls it so the tree's
    generated files match them."""
    for path, content in g.render_all(m, dest, pins).items():
        path.write_text(content)
    (dest / CATALOG).write_text(generate_catalog.render(dest / "docker", pins))


@functools.cache
def _root_dir() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="frozen-repo-")


@functools.cache
def root() -> Path:
    """A shared, read-only frozen repo tree (built once per test run, removed at
    exit). Tests that write to the tree must use `make_repo(tmp_path)` instead."""
    return make_repo(Path(_root_dir().name))
