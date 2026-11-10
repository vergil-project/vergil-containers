"""PR CI's image build jobs (pr_jobs.py, epic vergil-project/.github#213 T6'):
the selected matrix entries grouped into one job per image tree and
architecture, a selected parent built in the same job as its descendants."""
import json

import pytest

import frozen
import generate as g
import pr_jobs as pj
from test_generate import _tree

ROOT = frozen.LIVE_ROOT
LIVE = json.loads((ROOT / g.MATRIX_JSON).read_text())["include"]
TREE = json.loads(g.render_matrix_json(_tree()))["include"]
# vergil-tooling lib/package/matrix.py RUNNERS: the native runner per arch.
RUNNERS = {"amd64": "ubuntu-24.04", "arm64": "ubuntu-24.04-arm"}
NO_SMOKE = {"pkg-ubuntu": None, "base": None, "python": None, "go": None}


def _pick(entries, *keys):
    return [e for e in entries if (e["language"], e["version"]) in keys]


def _entry_keys(job):
    return [(e["language"], e["version"]) for e in job["entries"]]


def test_each_entry_without_a_selected_parent_is_its_own_job_on_both_arches():
    selected = [e for e in TREE if e["language"] == "go"]
    jobs = pj.jobs(selected, NO_SMOKE)
    assert [(j["name"], j["arch"], j["runner"]) for j in jobs] == [
        ("go:1.26", "amd64", RUNNERS["amd64"]), ("go:1.26", "arm64", RUNNERS["arm64"])]
    for job in jobs:
        assert job["entries"] == [{**selected[0], "smoke": None, "parent-local": False, "push-local": False}]


def test_a_selected_parent_and_its_descendants_share_one_job():
    # pkg-ubuntu <- base <- python: one tree, so one job per arch, parents first.
    selected = [e for e in TREE if e["language"] != "go"]
    jobs = pj.jobs(selected, NO_SMOKE)
    assert [(j["name"], j["arch"]) for j in jobs] == [
        ("pkg-ubuntu:24.04 + 4 descendants", "amd64"), ("pkg-ubuntu:24.04 + 4 descendants", "arm64")]
    job = jobs[0]
    assert _entry_keys(job) == [("pkg-ubuntu", "24.04"), ("base", "latest"),
                                ("python", "3.14"), ("python", "3.13"), ("python", "3.12")]
    flags = {(e["language"], e["version"]): (e["parent-local"], e["push-local"]) for e in job["entries"]}
    assert flags == {("pkg-ubuntu", "24.04"): (False, True), ("base", "latest"): (True, True),
                     ("python", "3.14"): (True, False), ("python", "3.13"): (True, False),
                     ("python", "3.12"): (True, False)}


def test_children_selected_alone_build_on_the_published_parent():
    selected = _pick(TREE, ("python", "3.14"), ("python", "3.13"))
    jobs = pj.jobs(selected, NO_SMOKE)
    assert [(j["name"], j["arch"]) for j in jobs] == [
        ("python:3.14", "amd64"), ("python:3.14", "arm64"), ("python:3.13", "amd64"), ("python:3.13", "arm64")]
    for job in jobs:
        (entry,) = job["entries"]
        assert entry["parent"] == {"language": "base", "version": "latest"}
        assert (entry["parent-local"], entry["push-local"]) == (False, False)


def test_a_mid_tree_parent_groups_only_its_descendants():
    selected = [e for e in TREE if e["language"] in {"base", "python", "go"}]
    jobs = pj.jobs(selected, NO_SMOKE)
    assert [j["name"] for j in jobs[::2]] == ["go:1.26", "base:latest + 3 descendants"]
    base_job = jobs[2]
    assert base_job["entries"][0]["language"] == "base"
    assert base_job["entries"][0]["parent-local"] is False  # pkg-ubuntu is published
    assert base_job["entries"][0]["push-local"] is True


def test_parent_is_built_first_whatever_the_selection_order():
    selected = list(reversed([e for e in TREE if e["language"] in {"base", "python"}]))
    (job, _) = pj.jobs(selected, NO_SMOKE)
    assert [e["language"] for e in job["entries"]] == ["base", "python", "python", "python"]


def test_smoke_dirs_follow_the_manifest():
    dirs = pj.smoke_dirs(ROOT)
    assert dirs["cpp-clang"] == "cpp"
    assert dirs["cpp-gcc"] == "cpp"
    assert dirs["ts-node"] == "ts-node"
    assert dirs["python"] is None
    assert dirs["base"] is None
    # Toolchain images are build entries too, with no smoke test of their own.
    assert dirs["pkg-ubuntu"] is None
    assert dirs["pkg-rhel"] is None
    assert set(dirs) == {e["language"] for e in LIVE}


def test_entries_carry_their_smoke_dir():
    jobs = pj.jobs([e for e in LIVE if e["language"] in {"ts-node", "rust"}], pj.smoke_dirs(ROOT))
    smoke = {e["language"]: e["smoke"] for j in jobs for e in j["entries"]}
    assert smoke == {"ts-node": "ts-node", "rust": None}


def test_empty_selection_is_no_jobs():
    assert pj.jobs([], NO_SMOKE) == []


def test_unknown_entry_refused():
    with pytest.raises(pj.JobsError, match=r"tool:1: no manifest entry 'tool'"):
        pj.jobs([{"language": "tool", "version": "1", "build-args": {}, "parent": None, "depth": 0}], NO_SMOKE)


def test_duplicate_entry_refused():
    go = [e for e in TREE if e["language"] == "go"]
    with pytest.raises(pj.JobsError, match=r"duplicate entry go:1\.26"):
        pj.jobs(go + go, NO_SMOKE)


def _cli(tmp_path, capsys, text):
    selected = tmp_path / "selected.json"
    selected.write_text(text)
    rc = pj.main(["--selected", str(selected)])
    return rc, capsys.readouterr()


def test_cli_prints_the_jobs(tmp_path, capsys):
    rust = [e for e in LIVE if e["language"] == "rust"]
    rc, out = _cli(tmp_path, capsys, json.dumps({"include": rust}))
    assert rc == 0, out.err
    assert json.loads(out.out) == {"include": pj.jobs(rust, pj.smoke_dirs(ROOT))}
    assert len(json.loads(out.out)["include"]) == 2 * len(rust)


def test_cli_empty_selection_prints_no_jobs(tmp_path, capsys):
    rc, out = _cli(tmp_path, capsys, '{"include": []}')
    assert rc == 0, out.err
    assert json.loads(out.out) == {"include": []}


@pytest.mark.parametrize("text", ["not json", "{}", '{"include": "x"}', '{"include": [1]}'])
def test_cli_bad_selection_exits_nonzero(tmp_path, capsys, text):
    rc, out = _cli(tmp_path, capsys, text)
    assert rc == 2
    assert out.out == ""
    assert out.err.startswith("::error title=Image build jobs failed::")
