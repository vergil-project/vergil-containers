"""PR CI's image selector (selection.py, epic vergil-project/.github#213 T5):
the matrix entries a change builds, from its paths and its matrix.json diff."""
import copy
import json

import pytest

import frozen
import generate as g
import selection as sel
from test_generate import _tree
from test_includes import _synthetic_repo

# The live checkout: its templates, fragments and matrix. The assertions name
# families, never version lists, so a lifecycle PR does not break them.
ROOT = frozen.LIVE_ROOT
LIVE = json.loads((ROOT / g.MATRIX_JSON).read_text())
ALL = {e["language"] for e in LIVE["include"]}


def _select(changed, base=LIVE, head=LIVE, root=ROOT):
    return sel.select_entries(root, changed, base, head)


def _languages(entries):
    return {e["language"] for e in entries}


def _keys(entries):
    return [(e["language"], e["version"]) for e in entries]


def test_single_family_template_selects_that_family():
    picked = _select(["docker/rust/Dockerfile.template"])
    assert _languages(picked) == {"rust"}
    assert picked == [e for e in LIVE["include"] if e["language"] == "rust"]


def test_single_family_fragment_selects_that_family():
    assert _languages(_select(["docker/common/typescript-analysis.dockerfile"])) == {"ts-node"}


def test_shared_fragment_fans_out_by_graph():
    assert _languages(_select(["docker/common/validation-tools.dockerfile"])) == ALL


def test_cpp_smoke_change_selects_both_cpp_families():
    assert _languages(_select(["docker/cpp/smoke-test.sh"])) == {"cpp-clang", "cpp-gcc"}
    assert _languages(_select(["docker/cpp/smoke/src/main.cpp"])) == {"cpp-clang", "cpp-gcc"}


def test_selection_keeps_head_matrix_order():
    picked = _select(["docker/rust/Dockerfile.template", "docker/python/Dockerfile.template"])
    assert picked == [e for e in LIVE["include"] if e["language"] in {"python", "rust"}]


def test_lifecycle_add_selects_new_entry():
    head = copy.deepcopy(LIVE)
    new = {"language": "python", "version": "3.99", "build-args": {"PYTHON_VERSION": "3.99"},
           "parent": None, "depth": 0}
    head["include"].insert(0, new)
    # The PR also edits the manifest and the regenerated matrix, which select
    # nothing by path: only the new entry is built.
    picked = _select(["docker/versions/manifest.yml", "docker/versions/matrix.json"], head=head)
    assert picked == [new]


def test_changed_build_args_select_that_entry():
    head = copy.deepcopy(LIVE)
    head["include"][0]["build-args"] = {**head["include"][0]["build-args"], "EXTRA": "1"}
    assert _select([], head=head) == [head["include"][0]]


def test_dropped_entry_selects_nothing():
    head = copy.deepcopy(LIVE)
    del head["include"][0]
    assert _select(["docker/versions/manifest.yml"], head=head) == []


@pytest.mark.parametrize("path", [
    ".trivyignore", "trivy.yaml", ".trivy/ignore-policy.rego", "docker/generate.sh",
    ".github/workflows/cd-docker-publish.yml", ".github/workflows/ci.yml",
    "scripts/bin/trivy-gate", "scripts/bin/trivy-image-scan",
])
def test_full_set_paths_select_everything(path):
    assert _select([path]) == LIVE["include"]


def test_trivyignore_selects_full():
    assert _select([".trivyignore"]) == LIVE["include"]


@pytest.mark.parametrize("path", [
    "README.md", "CHANGELOG.md", "docs/site/docs/index.md", "docker/pins/pins.yml",
    "docker/pins/CATALOG.md", "docker/common/README.md", "docker/versions/generate.py",
    "docker/versions/lifecycle/adapters/python.py", "docker/versions/testdata/manifest.yml",
    "docker/versions/fixtures/endoflife-python.json", "docker/versions/manifest.yml",
    "docker/versions/matrix.json", "docker/versions/window.json", "docker/build.sh",
    ".hadolint.yaml", "cliff.toml", "cliff-release-notes.toml", "vergil.toml",
    ".github/workflows/package-cleanup.yml", ".github/CODEOWNERS",
    "scripts/bin/validate-custom", "scripts/tests/trivy.test.sh", "LICENSE",
])
def test_no_build_paths_select_nothing(path):
    assert _select([path]) == []


def test_docs_and_pins_select_nothing():
    assert _select(["README.md", "docker/pins/pins.yml"]) == []


def test_no_change_selects_nothing():
    assert _select([]) == []


def test_unknown_docker_path_fails_closed_to_full(capsys):
    assert _select(["docker/new-thing/x"]) == LIVE["include"]
    assert "::warning" in capsys.readouterr().err
    # A fragment no template includes yet, and an unknown file in versions/.
    assert _select(["docker/common/new.dockerfile", "docker/versions/notes.txt"]) == LIVE["include"]
    err = capsys.readouterr().err
    assert "docker/common/new.dockerfile" in err and "docker/versions/notes.txt" in err


def test_family_context_beats_no_build_glob():
    # docker/<key>/** is the build context, so even a README there is an input.
    assert _languages(_select(["docker/cpp-clang/README.md"])) == {"cpp-clang"}


# The synthetic tree: pkg-ubuntu:24.04 <- base:latest <- python (every
# version), and go on an upstream image.
def _tree_matrix():
    return json.loads(g.render_matrix_json(_tree()))


def test_selecting_parent_selects_descendants(tmp_path):
    root = _synthetic_repo(tmp_path)
    base = _tree_matrix()
    head = copy.deepcopy(base)
    pkg = next(e for e in head["include"] if e["language"] == "pkg-ubuntu")
    pkg["build-args"] = {**pkg["build-args"], "EXTRA": "1"}
    # Only pkg-ubuntu's entry differs; base is built FROM it and python FROM
    # base, so all three are rebuilt, and go is not.
    picked = sel.select_entries(root, [], base, head)
    assert _keys(picked) == [("pkg-ubuntu", "24.04"), ("base", "latest"),
                             ("python", "3.14"), ("python", "3.13"), ("python", "3.12")]


@pytest.mark.parametrize(("changed", "expected"), [
    ("3.13", [("python", "3.13"), ("tool", "1")]),
    ("3.14", [("python", "3.14")]),
])
def test_descendants_follow_the_parent_version(tmp_path, changed, expected):
    root = _synthetic_repo(tmp_path)
    base = _tree_matrix()
    # A synthetic child of python 3.13 only.
    base["include"].append({"language": "tool", "version": "1", "build-args": {},
                            "parent": {"language": "python", "version": "3.13"}, "depth": 3})
    head = copy.deepcopy(base)
    for e in head["include"]:
        if (e["language"], e["version"]) == ("python", changed):
            e["build-args"] = {**e["build-args"], "EXTRA": "1"}
    assert _keys(sel.select_entries(root, [], base, head)) == expected


def test_parent_path_change_selects_descendants_by_graph(tmp_path):
    root = _synthetic_repo(tmp_path)
    m = _tree_matrix()
    picked = sel.select_entries(root, ["docker/common/base-only.dockerfile"], m, m)
    assert _keys(picked) == [("base", "latest"), ("python", "3.14"), ("python", "3.13"), ("python", "3.12")]


@pytest.mark.parametrize("bad", [
    [], {"include": "x"}, {"include": [1]}, {"include": [{"language": "python"}]},
    {"include": [{"language": "python", "version": "3.14", "build-args": {}, "parent": "base", "depth": 0}]},
])
def test_malformed_head_matrix_refused(bad):
    with pytest.raises(sel.SelectionError, match="head matrix"):
        _select([], head=bad)


def test_malformed_base_matrix_refused():
    with pytest.raises(sel.SelectionError, match="base matrix"):
        _select([], base={"include": None})


def _cli(tmp_path, capsys, changed, base=LIVE, head=LIVE):
    files = {}
    for name, data in (("base", base), ("head", head)):
        files[name] = tmp_path / f"{name}.json"
        files[name].write_text(json.dumps(data))
    files["changed"] = tmp_path / "changed.txt"
    files["changed"].write_text(changed)
    code = sel.main(["--root", str(ROOT), "--base-matrix", str(files["base"]),
                     "--head-matrix", str(files["head"]), "--changed-files", str(files["changed"])])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_prints_selected_include(tmp_path, capsys):
    code, out, _ = _cli(tmp_path, capsys, "docker/rust/Dockerfile.template\n\n")
    assert code == 0
    assert json.loads(out) == {"include": [e for e in LIVE["include"] if e["language"] == "rust"]}


def test_cli_empty_selection(tmp_path, capsys):
    code, out, _ = _cli(tmp_path, capsys, "README.md\n")
    assert code == 0
    assert json.loads(out) == {"include": []}


def test_cli_error_exits_nonzero(tmp_path, capsys):
    code, out, err = _cli(tmp_path, capsys, "README.md\n", head={"include": "x"})
    assert code == 2
    assert out == ""
    assert "::error" in err


def test_cli_missing_file_exits_nonzero(tmp_path, capsys):
    code = sel.main(["--root", str(ROOT), "--base-matrix", str(tmp_path / "nope.json"),
                     "--head-matrix", str(tmp_path / "nope.json"), "--changed-files", str(tmp_path / "nope")])
    assert code == 2
    assert "::error" in capsys.readouterr().err
