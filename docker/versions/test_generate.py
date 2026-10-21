import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import generate as g
import manifest as mf
from test_manifest import CURRENT_MATRIX

ROOT = Path(__file__).resolve().parent.parent.parent


def _seed() -> mf.Manifest:
    return mf.load_manifest(ROOT / g.MANIFEST)


@pytest.fixture
def repo(tmp_path):
    """A copy of every file the generator reads or writes."""
    rels = {g.MANIFEST, g.MATRIX_JSON, g.WINDOW_JSON, g.BUILD_SH, g.PACKAGE_CLEANUP, *g.DOC_TABLES}
    rels |= {Path("docker") / d / "Dockerfile.template" for d in ("base", *(f.key for f in _seed().families))}
    rels |= {p.relative_to(ROOT) for p in (ROOT / "docker").glob("*/smoke-test.sh")}
    for rel in rels:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, tmp_path / rel)
    return tmp_path


def test_render_matrix_json_equals_current_include_list():
    data = json.loads(g.render_matrix_json(_seed()))
    assert set(data) == {"include"}
    triples = [(e["language"], e["version"], e["build-arg"]) for e in data["include"]]
    assert all(set(e) == {"language", "version", "build-arg"} for e in data["include"])
    assert sorted(triples) == sorted(CURRENT_MATRIX)
    assert len(triples) == len(CURRENT_MATRIX)


def test_render_build_sh_block():
    text = g.render_build_sh(_seed(), ROOT)
    block = text.split("# BEGIN generated: versions\n")[1].split("# END generated: versions")[0]
    lines = block.splitlines()
    builds = [tuple(line.split()[1:]) for line in lines if line.startswith("build ")]
    assert sorted((k, v, a) for k, a, v in builds) == sorted(CURRENT_MATRIX)
    # Smoke tests come from the family's or its language's smoke-test.sh.
    smokes = [line for line in lines if "smoke-test.sh" in line]
    assert smokes == [
        '"${script_dir}/cpp/smoke-test.sh" "dev-cpp-clang:20" "$runtime"',
        '"${script_dir}/cpp/smoke-test.sh" "dev-cpp-clang:19" "$runtime"',
        '"${script_dir}/cpp/smoke-test.sh" "dev-cpp-gcc:14" "$runtime"',
        '"${script_dir}/cpp/smoke-test.sh" "dev-cpp-gcc:13" "$runtime"',
        '"${script_dir}/ts-node/smoke-test.sh" "dev-ts-node:24" "$runtime"',
        '"${script_dir}/ts-node/smoke-test.sh" "dev-ts-node:22" "$runtime"',
    ]
    assert len(lines) == len(CURRENT_MATRIX) + len(smokes)
    # The hand-written base build stays outside the block.
    assert '"$runtime" build -t "dev-base:latest"' in text.split("# END generated: versions")[1]


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
    text = g.render_package_cleanup(_seed(), ROOT)
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


def test_render_docs_tables(repo):
    out = g.render_all(_seed(), repo)
    for rel in g.DOC_TABLES:
        text = out[repo / rel]
        block = text.split("<!-- BEGIN generated: versions -->\n")[1].split("<!-- END")[0]
        rows = block.splitlines()
        assert rows[0].split("|")[1:5] == [" Image           ", " Language   ",
                                           " Versions         ", " Base                      "]
        assert "| `dev-python`    | python     | 3.14, 3.13, 3.12 | `python:<v>-slim`         |" in rows
        assert "| `dev-cpp-clang` | cpp        | 20, 19           | `debian:trixie-slim`      |" in rows
        assert "| `dev-ts-node`   | typescript | 24, 22           | `debian:trixie-slim`      |" in rows
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
    assert "ruby" in data["languages"]


def test_committed_files_are_up_to_date(capsys):
    assert g.main(["--check", "--root", str(ROOT)]) == 0


def test_check_mode_reports_drift(repo, capsys):
    assert g.main(["--check", "--root", str(repo)]) == 0
    build_sh = repo / g.BUILD_SH
    build_sh.write_text(build_sh.read_text().replace("build go GO_VERSION 1.26", "build go GO_VERSION 1.25"))
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
    for rel in (g.MATRIX_JSON, g.WINDOW_JSON, g.BUILD_SH, Path("docker/go/Dockerfile.template"),
                *g.DOC_TABLES):
        assert str(rel) in out
    # Package names do not depend on versions.
    assert str(g.PACKAGE_CLEANUP) not in out


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
