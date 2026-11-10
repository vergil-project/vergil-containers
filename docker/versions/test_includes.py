from pathlib import Path

import pytest

import frozen
import includes
import manifest as mf
from test_generate import _tree

# The live checkout. These tests read its templates and family set, which a
# lifecycle PR (a version added or dropped) never changes.
ROOT = frozen.LIVE_ROOT

TS_ANALYSIS = "docker/common/typescript-analysis.dockerfile"
SECURITY_TOOLS = "docker/common/security-tools.dockerfile"


def test_ts_node_includes_typescript_analysis_python_does_not():
    assert TS_ANALYSIS in includes.fragments_of(ROOT / "docker/ts-node/Dockerfile.template")
    assert TS_ANALYSIS not in includes.fragments_of(ROOT / "docker/python/Dockerfile.template")
    dm = includes.dependency_map(ROOT)
    assert {k for k, v in dm.items() if TS_ANALYSIS in v} == {"ts-node"}


def test_nested_include_is_followed():
    # python includes node-markdownlint, which includes nodesource-node.
    frags = includes.fragments_of(ROOT / "docker/python/Dockerfile.template")
    assert "docker/common/node-markdownlint.dockerfile" in frags
    assert "docker/common/nodesource-node.dockerfile" in frags


def test_security_tools_scoped_to_base():
    dm = includes.dependency_map(ROOT)
    assert {k for k, v in dm.items() if SECURITY_TOOLS in v} == {"base"}


def test_cpp_families_depend_on_shared_smoke_dir():
    dm = includes.dependency_map(ROOT)
    assert "docker/cpp/**" in dm["cpp-clang"] and "docker/cpp/**" in dm["cpp-gcc"]


def test_every_entry_depends_on_its_own_context():
    for key, inputs in includes.dependency_map(ROOT).items():
        assert f"docker/{key}/**" in inputs


def test_every_family_and_base_present():
    assert set(includes.dependency_map(ROOT)) == {
        "python", "go", "rust", "cpp-clang", "cpp-gcc", "ts-node", "base",
        "pkg-ubuntu", "pkg-rhel"}


def test_toolchain_fragments_are_scoped_to_the_toolchain_images():
    # vergil-containers#728: uv and the marker are the package toolchain
    # images' own; the apt mirror is pkg-ubuntu's alone; nFPM is shared.
    dm = includes.dependency_map(ROOT)

    def users(fragment):
        return {k for k, v in dm.items() if f"docker/common/{fragment}" in v}

    assert users("uv.dockerfile") == {"pkg-ubuntu", "pkg-rhel"}
    assert users("package-toolchain-marker.dockerfile") == {"pkg-ubuntu", "pkg-rhel"}
    assert users("apt-mirror.dockerfile") == {"pkg-ubuntu"}
    assert {"pkg-ubuntu", "pkg-rhel", "base"} <= users("nfpm.dockerfile")


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_missing_fragment_raises(tmp_path):
    _write(tmp_path, "docker/x/Dockerfile.template", "FROM scratch\n# @include common/nope.dockerfile\n")
    with pytest.raises(includes.IncludeError, match=r"docker/x/Dockerfile\.template:2: .*common/nope\.dockerfile"):
        includes.fragments_of(tmp_path / "docker/x/Dockerfile.template")


def test_missing_template_raises(tmp_path):
    with pytest.raises(includes.IncludeError, match=r"docker/x/Dockerfile\.template"):
        includes.fragments_of(tmp_path / "docker/x/Dockerfile.template")


def test_include_cycle_raises(tmp_path):
    _write(tmp_path, "docker/common/a.dockerfile", "# @include common/b.dockerfile\n")
    _write(tmp_path, "docker/common/b.dockerfile", "# @include common/a.dockerfile\n")
    _write(tmp_path, "docker/x/Dockerfile.template", "# @include common/a.dockerfile\n")
    with pytest.raises(includes.IncludeError, match="cycle"):
        includes.fragments_of(tmp_path / "docker/x/Dockerfile.template")


def test_only_exact_directive_shape_counts(tmp_path):
    # generate.sh matches `^# @include (.+)$`: no leading space, one space each.
    _write(tmp_path, "docker/common/a.dockerfile", "")
    _write(tmp_path, "docker/x/Dockerfile.template",
           " # @include common/missing.dockerfile\n#@include common/missing.dockerfile\n"
           "RUN echo '# @include common/missing.dockerfile'\n# @include common/a.dockerfile\n")
    assert includes.fragments_of(tmp_path / "docker/x/Dockerfile.template") == frozenset(
        {"docker/common/a.dockerfile"})


def _synthetic_repo(root: Path) -> Path:
    """`_tree()`'s manifest (`pkg-ubuntu` <- `base` <- `python`, `go` on an
    upstream image) with a template per entry, each including its own fragment."""
    _write(root, "docker/versions/manifest.yml", mf.dump_manifest(_tree()))
    for key in ("pkg-ubuntu", "base", "python", "go"):
        _write(root, f"docker/common/{key}-only.dockerfile", "")
        _write(root, f"docker/{key}/Dockerfile.template", f"FROM scratch\n# @include common/{key}-only.dockerfile\n")
    return root


def test_parent_inputs_are_inherited(tmp_path):
    dm = includes.dependency_map(_synthetic_repo(tmp_path))
    pkg = {"docker/pkg-ubuntu/**", "docker/common/pkg-ubuntu-only.dockerfile"}
    base = {"docker/base/**", "docker/common/base-only.dockerfile"}
    python = {"docker/python/**", "docker/common/python-only.dockerfile"}
    go = {"docker/go/**", "docker/common/go-only.dockerfile"}
    assert dm == {"pkg-ubuntu": frozenset(pkg), "base": frozenset(pkg | base),
                  "python": frozenset(pkg | base | python), "go": frozenset(go)}


def test_missing_entry_template_raises(tmp_path):
    _synthetic_repo(tmp_path)
    (tmp_path / "docker/go/Dockerfile.template").unlink()
    with pytest.raises(includes.IncludeError, match=r"docker/go/Dockerfile\.template"):
        includes.dependency_map(tmp_path)


def _toolchain_repo(root: Path) -> Path:
    """`_synthetic_repo` with `pkg-ubuntu` as a toolchain (not a family) and
    `base` built FROM it, as epic vergil-project/.github#649 sets the manifest."""
    _synthetic_repo(root)
    tree = _tree()
    m = mf.Manifest(
        families=tuple(f for f in tree.families if f.key != "pkg-ubuntu"),
        base_parent=tree.base_parent,
        toolchains=(mf.Toolchain("pkg-ubuntu", "UBUNTU_VERSION", ("26.04", "24.04")),),
    )
    _write(root, "docker/versions/manifest.yml", mf.dump_manifest(m))
    return root


def test_dependency_map_includes_toolchains(tmp_path):
    # vergil-containers#727: without the toolchain keys, #213's selector would
    # fail every docker/pkg-*/** path closed to the full set.
    dm = includes.dependency_map(_toolchain_repo(tmp_path))
    pkg = {"docker/pkg-ubuntu/**", "docker/common/pkg-ubuntu-only.dockerfile"}
    base = {"docker/base/**", "docker/common/base-only.dockerfile"}
    assert dm["pkg-ubuntu"] == frozenset(pkg)
    assert dm["base"] == frozenset(pkg | base)
    assert set(dm) == {"python", "go", "pkg-ubuntu", "base"}


def test_toolchain_smoke_dir_is_an_input(tmp_path):
    root = _toolchain_repo(tmp_path)
    _write(root, "docker/pkg-ubuntu/smoke-test.sh", "#!/bin/sh\n")
    assert includes.dependency_map(root)["pkg-ubuntu"] == frozenset(
        {"docker/pkg-ubuntu/**", "docker/common/pkg-ubuntu-only.dockerfile"})
