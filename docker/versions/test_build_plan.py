"""docker/build.sh's build plan (build_plan.py, vergil-containers#773): the
matrix.json entries in tier order, and a named family's parents first."""
import json

import pytest

import build_plan as bp
import frozen
import generate as g
import manifest as mf
from test_generate import _tree


def _write(tmp_path, m: mf.Manifest):
    path = tmp_path / "matrix.json"
    path.write_text(g.render_matrix_json(m, frozen.PINS))
    return path


def _pins(family: str, version: str) -> str:
    """The toolchain build args generate.py appends for `family` at `version`."""
    args = frozen.rt.build_args(frozen.PINS, family, version)
    return "".join(f" {name}={value}" for name, value in args.items())


def _run(capsys, *argv):
    code = bp.main(list(argv))
    out = capsys.readouterr()
    return code, out.out.splitlines(), out.err


def test_every_entry_in_matrix_order_by_default(tmp_path, capsys):
    path = _write(tmp_path, frozen.SEED)
    code, lines, _ = _run(capsys, "--matrix", str(path))
    assert code == 0
    include = json.loads(path.read_text())["include"]
    assert [tuple(line.split("\t")[1:3]) for line in lines] == [(e["language"], e["version"]) for e in include]
    assert lines[0] == "build\tpython\t3.14\t-\tPYTHON_VERSION=3.14" + _pins("python", "3.14")
    # base takes no build argument.
    assert lines[-1] == "build\tbase\tlatest\t-\t-"
    assert all(line.startswith("build\t") for line in lines)


def test_tree_builds_in_tier_order(tmp_path, capsys):
    code, lines, _ = _run(capsys, "--matrix", str(_write(tmp_path, _tree())))
    assert code == 0
    assert lines == [
        "build\tgo\t1.26\t-\tGO_VERSION=1.26" + _pins("go", "1.26"),
        "build\tpkg-ubuntu\t24.04\t-\tUBUNTU_VERSION=24.04",
        "build\tbase\tlatest\tpkg-ubuntu:24.04\t-",
        "build\tpython\t3.14\tbase:latest\tPYTHON_VERSION=3.14" + _pins("python", "3.14"),
        "build\tpython\t3.13\tbase:latest\tPYTHON_VERSION=3.13" + _pins("python", "3.13"),
        "build\tpython\t3.12\tbase:latest\tPYTHON_VERSION=3.12" + _pins("python", "3.12"),
    ]


def test_a_family_gets_its_parents_first(tmp_path, capsys):
    code, lines, _ = _run(capsys, "--matrix", str(_write(tmp_path, _tree())), "python")
    assert code == 0
    assert [line.split("\t")[:3] for line in lines] == [
        ["parent", "pkg-ubuntu", "24.04"],
        ["parent", "base", "latest"],
        ["build", "python", "3.14"],
        ["build", "python", "3.13"],
        ["build", "python", "3.12"],
    ]


def test_a_named_parent_is_built_not_pulled(tmp_path, capsys):
    code, lines, _ = _run(capsys, "--matrix", str(_write(tmp_path, _tree())), "python", "base")
    assert code == 0
    assert [line.split("\t")[:2] for line in lines][:2] == [["parent", "pkg-ubuntu"], ["build", "base"]]


def test_a_family_with_no_parent_is_alone(tmp_path, capsys):
    code, lines, _ = _run(capsys, "--matrix", str(_write(tmp_path, _tree())), "go")
    assert code == 0
    assert lines == ["build\tgo\t1.26\t-\tGO_VERSION=1.26" + _pins("go", "1.26")]


def test_unknown_family_refused(tmp_path, capsys):
    code, lines, err = _run(capsys, "--matrix", str(_write(tmp_path, _tree())), "cobol")
    assert code == 2
    assert lines == []
    assert "unknown family 'cobol'" in err


def _entry(**over):
    e = {"language": "python", "version": "3.14", "build-args": {"PYTHON_VERSION": "3.14"},
         "parent": None, "depth": 0}
    e.update(over)
    return e


@pytest.mark.parametrize(("include", "message"), [
    ([], "non-empty"),
    ([{"language": "python"}], "exactly"),
    ([_entry(depth="0")], "depth"),
    ([_entry(depth=-1)], "depth"),
    ([_entry(**{"build-args": {"PYTHON_VERSION": "3 14"}})], "build argument"),
    ([_entry(**{"build-args": {"python": "3.14"}})], "build argument"),
    ([_entry(**{"build-args": ["PYTHON_VERSION"]})], "mapping"),
    ([_entry(language="Py thon")], "language"),
    ([_entry(parent="base")], "parent"),
    ([_entry(parent={"language": "base", "version": "latest"}, depth=1)], "is not in"),
    ([_entry(), _entry()], "duplicate"),
    ([_entry(language="base", version="latest", depth=1),
      _entry(parent={"language": "base", "version": "latest"}, depth=1)], "shallower"),
])
def test_malformed_matrix_refused(tmp_path, capsys, include, message):
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps({"include": include}))
    code, lines, err = _run(capsys, "--matrix", str(path))
    assert code == 2
    assert lines == []
    assert message in err


def test_unreadable_matrix_refused(tmp_path, capsys):
    code, _, err = _run(capsys, "--matrix", str(tmp_path / "absent.json"))
    assert code == 2
    assert "cannot read" in err
    (tmp_path / "bad.json").write_text("not json")
    code, _, err = _run(capsys, "--matrix", str(tmp_path / "bad.json"))
    assert code == 2


def test_live_matrix_plans():
    assert bp.plan(bp.load(frozen.LIVE_ROOT / g.MATRIX_JSON), [])
