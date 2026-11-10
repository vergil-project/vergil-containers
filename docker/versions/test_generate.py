import json
import re
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import frozen
import generate as g
import includes
import manifest as mf
from test_manifest import CURRENT_MATRIX

# The live checkout: only `test_real_manifest_is_valid` reads it. Every other
# test runs on the frozen manifest and tree (`frozen.py`, #654).
LIVE_ROOT = frozen.LIVE_ROOT


def _seed() -> mf.Manifest:
    return frozen.SEED


@pytest.fixture
def repo(tmp_path):
    """A writable copy of every file the generator reads or writes, on the
    frozen manifest."""
    return frozen.make_repo(tmp_path)


MATRIX_KEYS = ["language", "version", "build-args", "parent", "depth"]


def test_render_matrix_json_equals_current_include_list():
    data = json.loads(g.render_matrix_json(_seed()))
    assert set(data) == {"include"}
    assert all(list(e) == MATRIX_KEYS for e in data["include"])
    families = data["include"][:-1]
    triples = [(e["language"], e["version"], *e["build-args"]) for e in families]
    assert sorted(triples) == sorted(CURRENT_MATRIX)
    assert len(triples) == len(CURRENT_MATRIX)
    # No entry of the frozen manifest names a parent: everything is tier 0.
    assert all(e["parent"] is None and e["depth"] == 0 for e in data["include"])


def test_build_args_map_replaces_build_arg():
    include = json.loads(g.render_matrix_json(_seed()))["include"]
    assert all("build-arg" not in e for e in include)
    python = [e for e in include if e["language"] == "python"]
    assert [e["build-args"] for e in python] == [
        {"PYTHON_VERSION": "3.14"}, {"PYTHON_VERSION": "3.13"}, {"PYTHON_VERSION": "3.12"}]
    for e in include[:-1]:
        assert list(e["build-args"].values()) == [e["version"]]


def test_base_build_args_empty():
    include = json.loads(g.render_matrix_json(_seed()))["include"]
    assert include[-1] == {"language": g.BASE_KEY, "version": g.BASE_VERSION, "build-args": {},
                           "parent": None, "depth": 0}
    assert [e for e in include if e["build-args"] == {}] == [include[-1]]
    assert [e for e in include if e["language"] == g.BASE_KEY] == [include[-1]]


def _tree() -> mf.Manifest:
    """A synthetic tree: `pkg-ubuntu` <- `base` <- `python`, with `go` on an
    upstream image. No real manifest entry has a parent yet (epic
    vergil-project/.github#649 sets them)."""
    seed = {f.key: f for f in _seed().families}
    pkg = replace(seed["go"], key="pkg-ubuntu", language="pkgubuntu", build_arg="UBUNTU_VERSION",
                  versions=(mf.ManifestVersion("24.04", None, None, True, None),))
    python = replace(seed["python"], parent=mf.Parent("base", "latest"))
    return mf.Manifest(families=(python, seed["go"], pkg), base_parent=mf.Parent("pkg-ubuntu", "24.04"))


def test_matrix_parent_and_depth_emitted():
    include = json.loads(g.render_matrix_json(_tree()))["include"]
    by = {(e["language"], e["version"]): e for e in include}
    assert by[("pkg-ubuntu", "24.04")]["parent"] is None
    assert by[("pkg-ubuntu", "24.04")]["depth"] == 0
    assert by[("base", "latest")]["parent"] == {"language": "pkg-ubuntu", "version": "24.04"}
    assert by[("base", "latest")]["depth"] == 1
    assert by[("python", "3.14")]["parent"] == {"language": "base", "version": "latest"}
    assert by[("python", "3.14")]["depth"] == 2
    assert by[("go", "1.26")] == {"language": "go", "version": "1.26", "build-args": {"GO_VERSION": "1.26"},
                                  "parent": None, "depth": 0}


def test_matrix_ordered_by_depth():
    include = json.loads(g.render_matrix_json(_tree()))["include"]
    assert [(e["language"], e["version"], e["depth"]) for e in include] == [
        ("go", "1.26", 0),
        ("pkg-ubuntu", "24.04", 0),
        ("base", "latest", 1),
        ("python", "3.14", 2),
        ("python", "3.13", 2),
        ("python", "3.12", 2),
    ]


def test_matrix_refuses_a_bad_tree():
    seed = _seed()
    bad = mf.Manifest(families=seed.families, base_parent=mf.Parent("pkg-ubuntu", "24.04"))
    with pytest.raises(mf.ManifestError, match=r"base: parent: no manifest entry 'pkg-ubuntu'"):
        g.render_matrix_json(bad)


def test_render_build_sh_block():
    text = g.render_build_sh(_seed(), frozen.root())
    block = text.split("# BEGIN generated: versions\n")[1].split("# END generated: versions")[0]
    # The builds come from matrix.json at run time; the block holds only the
    # smoke-test table, from the family's or its language's smoke-test.sh.
    assert block.splitlines() == ['smoke_tests="cpp-clang:cpp cpp-gcc:cpp ts-node:ts-node"']
    assert "build python" not in text


def test_render_arg_defaults_newest(repo):
    seed = _seed()
    for f in seed.families:
        text = g.render_arg_default(f, repo)
        assert f"ARG {f.build_arg}={f.versions[0].version}\n" in text
    # A newer version at the head of the family moves the default.
    python = next(f for f in seed.families if f.key == "python")
    newer = replace(python, versions=(replace(python.versions[0], version="3.15"), *python.versions))
    assert "ARG PYTHON_VERSION=3.15\n" in g.render_arg_default(newer, repo)


def test_render_arg_default_requires_one_anchor(repo):
    python = next(f for f in _seed().families if f.key == "python")
    template = repo / "docker/python/Dockerfile.template"
    template.write_text(template.read_text().replace("ARG PYTHON_VERSION=", "ARG PY="))
    with pytest.raises(g.GenerateError, match="docker/python/Dockerfile.template.*ARG PYTHON_VERSION"):
        g.render_arg_default(python, repo)


def test_render_package_cleanup_includes_all_families():
    text = g.render_package_cleanup(_seed(), frozen.root())
    keys = ["base"] + [f.key for f in _seed().families]
    cleanup = text.split("# BEGIN generated: versions (cleanup)\n")[1].split("# END")[0]
    assert [line.strip() for line in cleanup.splitlines() if line.strip()] == (
        [f"- dev-{k}" for k in keys] + [f"- prod-{k}" for k in keys]
    )
    for missing_before in ("cpp-clang", "cpp-gcc", "ts-node"):
        assert f"- dev-{missing_before}" in cleanup
        assert f"- prod-{missing_before}" in cleanup
    reap = text.split("# BEGIN generated: versions (reap)\n")[1].split("# END")[0]
    pairs = [line.strip() for line in reap.splitlines() if line.strip()]
    assert pairs[:2] == ["- package: prod-base", 'older_than: "30 days"']
    assert "- package: dev-ts-node" in pairs
    assert pairs[-1] == 'older_than: "7 days"'
    assert len(pairs) == 2 * 2 * len(keys)


def test_render_package_cache_warm_lists_the_cleanup_packages():
    keys = ["base"] + [f.key for f in _seed().families]
    text = g.render_package_cache_warm(_seed(), frozen.root())
    warm = text.split("# BEGIN generated: versions (warm)\n")[1].split("# END")[0]
    assert [line.strip() for line in warm.splitlines() if line.strip()] == (
        [f"- dev-{k}" for k in keys] + [f"- prod-{k}" for k in keys]
    )


def test_render_docs_tables(repo):
    out = g.render_all(_seed(), repo)
    for rel in g.DOC_TABLES:
        text = out[repo / rel]
        block = text.split("<!-- BEGIN generated: versions -->\n")[1].split("<!-- END")[0]
        rows = block.splitlines()
        assert rows[0].split("|")[1:5] == [" Image           ", " Language   ",
                                           " Versions         ", " Base                 "]
        assert "| `dev-python`    | python     | 3.14, 3.13, 3.12 | `python:<v>-slim`    |" in rows
        assert "| `dev-cpp-clang` | cpp        | 20, 19           | `debian:trixie-slim` |" in rows
        assert "| `dev-ts-node`   | typescript | 24, 22           | `debian:trixie-slim` |" in rows
        assert rows[-1].startswith("| `dev-base`") and "`python:3.14-slim`" in rows[-1]
        assert len(rows) == 2 + len(_seed().families) + 1


def test_window_json_schema():
    python = mf.Family(
        key="python", language="python", token_prefix="", build_arg="PYTHON_VERSION",
        automation="pr",
        versions=(mf.ManifestVersion("3.14", date(2025, 10, 7), date(2030, 10, 31), True, True),),
    )
    clang = mf.Family(
        key="cpp-clang", language="cpp", token_prefix="clang-", build_arg="CLANG_VERSION",
        automation="report", versions=(mf.ManifestVersion("20", None, None, False, None),),
    )
    gcc = replace(clang, key="cpp-gcc", token_prefix="gcc-", build_arg="GCC_VERSION",
                  versions=(mf.ManifestVersion("14", None, None, True, None),))
    data = json.loads(g.render_window_json(mf.Manifest((python, clang, gcc))))
    assert data == {
        "schema": 1,
        "languages": {
            "python": {"families": [
                {"key": "python", "token_prefix": "",
                 "versions": [{"version": "3.14", "eol": "2030-10-31",
                               "in_policy": True, "runtime_published": True}]}]},
            "cpp": {"families": [
                {"key": "cpp-clang", "token_prefix": "clang-",
                 "versions": [{"version": "20", "eol": None,
                               "in_policy": False, "runtime_published": None}]},
                {"key": "cpp-gcc", "token_prefix": "gcc-",
                 "versions": [{"version": "14", "eol": None,
                               "in_policy": True, "runtime_published": None}]}]},
        },
    }


def test_window_json_covers_every_family_newest_first():
    seed = _seed()
    data = json.loads(g.render_window_json(seed))
    families = [fam for lang in data["languages"].values() for fam in lang["families"]]
    assert [f["key"] for f in families] == [f.key for f in seed.families]
    for fam, family in zip(families, seed.families):
        assert [v["version"] for v in fam["versions"]] == [v.version for v in family.versions]


def _committed_window() -> dict:
    """window.json as generated from the frozen manifest."""
    return json.loads((frozen.root() / g.WINDOW_JSON).read_text())


def _window_families(window: dict) -> dict:
    return {fam["key"]: [v["version"] for v in fam["versions"]]
            for lang in window["languages"].values() for fam in lang["families"]}


def test_window_has_no_ruby():
    window = _committed_window()
    assert "ruby" not in window["languages"]
    assert "ruby" not in _window_families(window)


def test_cpp_gcc_window_is_14_only():
    assert _window_families(_committed_window())["cpp-gcc"] == ["14"]


def test_real_manifest_is_valid(capsys):
    # The one test on the live docker/versions/manifest.yml (#654). It must
    # never assert which versions the manifest lists: lifecycle add and drop
    # PRs change those, and must not break their own CI.
    real = LIVE_ROOT / g.MANIFEST
    m = mf.load_manifest(real)
    # Canonical: automated edits go through dump_manifest, so they never
    # reformat the whole file.
    assert mf.dump_manifest(m) == real.read_text()
    # Every generated file is up to date with it.
    assert g.main(["--check", "--root", str(LIVE_ROOT)]) == 0


def test_check_mode_reports_drift(repo, capsys):
    assert g.main(["--check", "--root", str(repo)]) == 0
    build_sh = repo / g.BUILD_SH
    build_sh.write_text(build_sh.read_text().replace("cpp-gcc:cpp ", ""))
    capsys.readouterr()
    assert g.main(["--check", "--root", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "docker/build.sh" in out
    assert "README.md" not in out
    # Write mode repairs the drift.
    assert g.main(["--root", str(repo)]) == 0
    assert g.main(["--check", "--root", str(repo)]) == 0


def test_manifest_change_flows_to_every_target(repo, capsys):
    path = repo / g.MANIFEST
    path.write_text(path.read_text().replace('version: "1.26"', 'version: "1.27"'))
    assert g.main(["--check", "--root", str(repo)]) == 1
    out = capsys.readouterr().out
    for rel in (g.MATRIX_JSON, g.WINDOW_JSON, Path("docker/go/Dockerfile.template"),
                *g.DOC_TABLES):
        assert str(rel) in out
    # build.sh reads its builds from matrix.json; package names do not depend
    # on versions.
    assert str(g.BUILD_SH) not in out
    assert str(g.PACKAGE_CLEANUP) not in out
    assert str(g.PACKAGE_CACHE_WARM) not in out


def test_missing_marker_fails_loud(repo, capsys):
    readme = repo / "README.md"
    readme.write_text(readme.read_text().replace("<!-- END generated: versions -->\n", ""))
    assert g.main(["--check", "--root", str(repo)]) == 2
    err = capsys.readouterr().err
    assert "README.md" in err and "END generated: versions" in err


def test_bad_manifest_fails_loud(repo, capsys):
    path = repo / g.MANIFEST
    path.write_text(path.read_text().replace('automation: "pr"', 'automation: "auto"', 1))
    assert g.main(["--check", "--root", str(repo)]) == 2
    assert "automation 'auto'" in capsys.readouterr().err


# --- Toolchains (vergil-containers#727, epic vergil-project/.github#607 T3) ---

PKG_UBUNTU = mf.Toolchain(key="pkg-ubuntu", build_arg="UBUNTU_VERSION", versions=("26.04", "24.04"))


def _with_toolchain() -> mf.Manifest:
    return replace(_seed(), toolchains=(PKG_UBUNTU,))


def _toolchain_repo(root: Path) -> Path:
    """The frozen repo plus a `pkg-ubuntu` template, with no smoke test."""
    template = root / "docker/pkg-ubuntu/Dockerfile.template"
    template.parent.mkdir(parents=True)
    template.write_text("ARG UBUNTU_VERSION=24.04\nFROM ubuntu:${UBUNTU_VERSION}\n")
    return root


def test_matrix_json_appends_toolchain_entries():
    include = json.loads(g.render_matrix_json(_with_toolchain()))["include"]
    assert include[-3:] == [
        {"language": "pkg-ubuntu", "version": "26.04", "build-args": {"UBUNTU_VERSION": "26.04"},
         "parent": None, "depth": 0},
        {"language": "pkg-ubuntu", "version": "24.04", "build-args": {"UBUNTU_VERSION": "24.04"},
         "parent": None, "depth": 0},
        {"language": g.BASE_KEY, "version": g.BASE_VERSION, "build-args": {}, "parent": None, "depth": 0},
    ]
    # Every family entry is unchanged and comes first.
    assert include[:-3] == json.loads(g.render_matrix_json(_seed()))["include"][:-1]


def test_matrix_json_toolchain_as_parent():
    # Epic vergil-project/.github#649: base built FROM pkg-ubuntu:24.04.
    m = replace(_with_toolchain(), base_parent=mf.Parent("pkg-ubuntu", "24.04"))
    include = json.loads(g.render_matrix_json(m))["include"]
    assert [(e["language"], e["depth"]) for e in include if e["depth"] == 0][-2:] == [
        ("pkg-ubuntu", 0), ("pkg-ubuntu", 0)]
    assert include[-1] == {"language": g.BASE_KEY, "version": g.BASE_VERSION, "build-args": {},
                           "parent": {"language": "pkg-ubuntu", "version": "24.04"}, "depth": 1}


def test_window_json_excludes_toolchains():
    window = g.render_window_json(_with_toolchain())
    assert "pkg-ubuntu" not in window
    assert window == g.render_window_json(_seed())


def test_package_cleanup_includes_toolchains():
    text = g.render_package_cleanup(_with_toolchain(), frozen.root())
    keys = ["base"] + [f.key for f in _seed().families] + ["pkg-ubuntu"]
    cleanup = text.split("# BEGIN generated: versions (cleanup)\n")[1].split("# END")[0]
    assert [line.strip() for line in cleanup.splitlines() if line.strip()] == (
        [f"- dev-{k}" for k in keys] + [f"- prod-{k}" for k in keys]
    )
    reap = text.split("# BEGIN generated: versions (reap)\n")[1].split("# END")[0]
    assert "- package: prod-pkg-ubuntu" in reap and "- package: dev-pkg-ubuntu" in reap
    warm = g.render_package_cache_warm(_with_toolchain(), frozen.root())
    assert "- prod-pkg-ubuntu\n" in warm


def test_toolchain_arg_default_and_docs_row(repo):
    root = _toolchain_repo(repo)
    out = g.render_all(_with_toolchain(), root)
    template = out[root / "docker/pkg-ubuntu/Dockerfile.template"]
    assert template.startswith("ARG UBUNTU_VERSION=26.04\n")
    for rel in g.DOC_TABLES:
        block = out[root / rel].split("<!-- BEGIN generated: versions -->\n")[1].split("<!-- END")[0]
        rows = block.splitlines()
        (row,) = [r for r in rows if "`dev-pkg-ubuntu`" in r]
        assert [c.strip() for c in row.split("|")[1:5]] == ["`dev-pkg-ubuntu`", "—", "26.04, 24.04", "`ubuntu:<v>`"]
        # After the families, before base.
        assert rows.index(row) == len(rows) - 2
    # No smoke test for the toolchain, so build.sh's table is unchanged.
    assert out[root / g.BUILD_SH] == (root / g.BUILD_SH).read_text()
    # The whole tree regenerates, and --check then passes.
    for path, content in out.items():
        path.write_text(content)
    (root / g.MANIFEST).write_text(mf.dump_manifest(_with_toolchain()))
    assert g.main(["--check", "--root", str(root)]) == 0


def test_toolchain_smoke_test_from_its_own_directory(repo):
    root = _toolchain_repo(repo)
    (root / "docker/pkg-ubuntu/smoke-test.sh").write_text("#!/bin/sh\n")
    text = g.render_build_sh(_with_toolchain(), root)
    assert 'smoke_tests="cpp-clang:cpp cpp-gcc:cpp ts-node:ts-node pkg-ubuntu:pkg-ubuntu"' in text


# --- Toolchain templates (vergil-containers#728, epic vergil-project/.github#607 T4) ---

# Dockerfile instructions are case-insensitive; a comment line is not one.
_INHERITED_CONFIG_RE = re.compile(r"^\s*(ENTRYPOINT|CMD|USER|WORKDIR)\b", re.IGNORECASE | re.MULTILINE)


def test_pkg_templates_set_no_inherited_config():
    # Epic vergil-project/.github#649 builds base and every language image on
    # pkg-ubuntu:24.04, so a toolchain template must set none of the image
    # config a child inherits: a child gets only what the upstream image sets.
    # Every fragment the template includes is checked too, since its
    # instructions land in the image just the same.
    for key in ("pkg-ubuntu", "pkg-rhel"):
        template = LIVE_ROOT / "docker" / key / "Dockerfile.template"
        files = [template, *(LIVE_ROOT / rel for rel in sorted(includes.fragments_of(template)))]
        for path in files:
            found = _INHERITED_CONFIG_RE.findall(path.read_text())
            assert found == [], f"{path.relative_to(LIVE_ROOT)} sets {found}"


def test_inherited_config_check_catches_each_instruction():
    for instruction in ('ENTRYPOINT ["x"]', 'CMD ["/bin/bash"]', "USER 1000", "workdir /workspace"):
        assert _INHERITED_CONFIG_RE.findall(f"FROM ubuntu\n{instruction}\n")
    assert not _INHERITED_CONFIG_RE.findall("FROM ubuntu\n# CMD is inherited\nRUN echo USER\n")
