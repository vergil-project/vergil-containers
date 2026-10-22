import json
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import frozen
import generate as g
import manifest as mf
from lifecycle import core, publish
from lifecycle.adapters.go import GoAdapter
from lifecycle.adapters.python import PythonAdapter
from lifecycle.apply import ApplyError, apply_change, branch_name, parse_branch, pr_title, render_change
from lifecycle.core import Change, FamilyResult, TargetVersion
from lifecycle.publish import ADD_HOLD_ISSUE, ADD_HOLD_REPO, GhCli, GitCli, OpenPr, PublishError, sync_prs
from lifecycle.report import results_to_json
from lifecycle.runtime import AptIndex
from test_generate import repo  # noqa: F401  (fixture: a copy of every generated file)

HERE = Path(__file__).resolve().parent
ROOT = frozen.root()  # a repo tree whose generated files match SEED
FIXTURES = HERE / "fixtures"
TODAY = date(2026, 10, 21)
SEED = frozen.SEED  # the frozen test manifest, not the live one (#654)


def RUNTIME_314():
    """A vergil apt index publishing only the 3.14 runtime, as live today."""
    return AptIndex({("noble", "amd64"): frozenset({"vergil-python3.14"})})
RUN1 = "https://github.com/o/r/actions/runs/1"
RUN2 = "https://github.com/o/r/actions/runs/2"


def _family(m, key):
    (family,) = [f for f in m.families if f.key == key]
    return family


def _fixture_fetch(product, extra=()):
    def fetch(url):
        assert url == f"https://endoflife.date/api/{product}.json", url
        return json.dumps(list(extra) + json.loads((FIXTURES / f"endoflife-{product}.json").read_text())).encode()

    return fetch


def _adapters(go_extra=()):
    return {
        "python": PythonAdapter(
            fetch=_fixture_fetch("python"), tag_exists=lambda image, tag: True, runtime_index=RUNTIME_314
        ),
        "go": GoAdapter(fetch=_fixture_fetch("go", go_extra), tag_exists=lambda image, tag: True),
    }


def _pr_results(m=SEED, today=TODAY, go_extra=()):
    """Python and go checked from the fixtures, every other family in sync."""
    adapters = _adapters(go_extra)
    pr_only = mf.Manifest(families=tuple(f for f in m.families if f.key in adapters))
    checked = {r.family: r for r in core.run(pr_only, adapters, today)}
    return [checked.get(f.key, FamilyResult(f.key, (), None)) for f in m.families]


def _versions(m, key):
    return [v.version for v in _family(m, key).versions]


# --- apply_change ---------------------------------------------------------------------


def test_apply_add_python_315_inserts_newest_first():
    target = TargetVersion("3.15", date(2026, 10, 9), date(2031, 10, 31), True)
    after = apply_change(SEED, Change("python", "add", "3.15", "GA 2026-10-09"), target)
    assert _versions(after, "python") == ["3.15", "3.14", "3.13", "3.12"]
    added = _family(after, "python").versions[0]
    assert added == mf.ManifestVersion("3.15", date(2026, 10, 9), date(2031, 10, 31), True, False)
    # Every other family is untouched.
    assert [f for f in after.families if f.key != "python"] == [f for f in SEED.families if f.key != "python"]


def test_apply_add_without_runtime_records_null():
    target = TargetVersion("1.27", date(2026, 8, 19), None, True)
    after = apply_change(SEED, Change("go", "add", "1.27", ""), target)
    assert _versions(after, "go") == ["1.27", "1.26"]
    assert _family(after, "go").versions[0].runtime_published is None


def test_apply_add_in_the_middle_keeps_order():
    m = apply_change(SEED, Change("python", "drop", "3.13", ""))
    after = apply_change(m, Change("python", "add", "3.13", ""), TargetVersion("3.13", None, None, True))
    assert _versions(after, "python") == ["3.14", "3.13", "3.12"]


def test_apply_drop_removes_version():
    after = apply_change(SEED, Change("python", "drop", "3.12", "EOL reached"))
    assert _versions(after, "python") == ["3.14", "3.13"]


@pytest.mark.parametrize(
    "change, target, needle",
    [
        (Change("python", "add", "3.15", ""), None, "needs its target"),
        (Change("python", "add", "3.15", ""), TargetVersion("3.16", None, None, True), "needs its target"),
        (Change("python", "add", "3.15", ""), TargetVersion("3.15", None, None, False), "not installable"),
        (Change("python", "add", "3.15", ""), TargetVersion("3.15", None, core.EOL_DATE_UNKNOWN, True), "EOL"),
        (Change("python", "add", "3.14", ""), TargetVersion("3.14", None, None, True), "already lists"),
        (Change("python", "drop", "3.11", ""), None, "does not list"),
        (Change("go", "drop", "1.26", ""), None, "no versions"),
        (Change("python", "blocked", "3.15", ""), None, "reported, not applied"),
        (Change("ruby", "drop", "3.2", ""), None, "no such family"),
    ],
)
def test_apply_rejects_what_it_cannot_apply_exactly(change, target, needle):
    with pytest.raises(ApplyError, match=needle):
        apply_change(SEED, change, target)


# --- names -------------------------------------------------------------------------------


def test_branch_names_and_titles():
    add = Change("python", "add", "3.15", "")
    drop = Change("cpp-clang", "drop", "19", "")
    assert branch_name(add) == "lifecycle/python-add-3.15"
    assert branch_name(drop) == "lifecycle/cpp-clang-drop-19"
    assert parse_branch("lifecycle/python-add-3.15") == ("python", "add", "3.15")
    assert parse_branch("lifecycle/cpp-clang-drop-19") == ("cpp-clang", "drop", "19")
    for other in ("lifecycle/python-blocked-3.15", "bot/bump-tools-1", "lifecycle/python-add-x"):
        assert parse_branch(other) is None
    assert pr_title(add, None) == "feat(versions): add python 3.15"
    assert pr_title(drop, date(2026, 9, 1)) == "feat(versions): drop cpp-clang 19 (EOL 2026-09-01)"
    assert pr_title(drop, None) == "feat(versions): drop cpp-clang 19 (EOL date unknown)"
    with pytest.raises(ApplyError, match="no pull request"):
        pr_title(Change("python", "eol_soon", "3.12", ""), None)


# --- regenerated files ---------------------------------------------------------------------


def test_apply_then_render_regenerates_all_files(repo):  # noqa: F811
    m = mf.load_manifest(repo / g.MANIFEST)
    target = TargetVersion("3.15", date(2026, 10, 9), date(2031, 10, 31), True)
    files = render_change(m, Change("python", "add", "3.15", ""), target, repo)
    assert set(files) == {
        g.MANIFEST,
        g.MATRIX_JSON,
        g.WINDOW_JSON,
        g.BUILD_SH,
        Path("docker/python/Dockerfile.template"),
        *g.DOC_TABLES,
    }
    for rel, content in files.items():
        assert (repo / rel).read_text() != content
        (repo / rel).write_text(content)
    assert g.main(["--check", "--root", str(repo)]) == 0
    assert _versions(mf.load_manifest(repo / g.MANIFEST), "python") == ["3.15", "3.14", "3.13", "3.12"]
    assert "ARG PYTHON_VERSION=3.15" in (repo / "docker/python/Dockerfile.template").read_text()
    assert "build python PYTHON_VERSION 3.15" in (repo / g.BUILD_SH).read_text()


def test_render_drop_of_an_older_version_leaves_the_arg_default(repo):  # noqa: F811
    m = mf.load_manifest(repo / g.MANIFEST)
    files = render_change(m, Change("python", "drop", "3.12", ""), None, repo)
    assert Path("docker/python/Dockerfile.template") not in files
    assert g.MANIFEST in files and g.MATRIX_JSON in files


# --- sync_prs: fakes ------------------------------------------------------------------------


class FakeGh:
    """An in-memory PR tracker implementing the PrClient protocol."""

    def __init__(self, hold_open=True):
        self.prs = {}  # number -> dict(head, title, body, open, comments, auto)
        self.calls = []
        self.hold_open = hold_open
        self._next = 500

    def seed(self, head, title="old", auto=False):
        n = self._next
        self._next += 1
        self.prs[n] = {"head": head, "title": title, "body": "old", "open": True, "comments": [], "auto": auto}
        return n

    def list_open_prs(self, head_prefix):
        self.calls.append(("list", head_prefix))
        return [OpenPr(n, p["head"]) for n, p in self.prs.items() if p["open"] and p["head"].startswith(head_prefix)]

    def create_pr(self, head, title, body):
        self.calls.append(("create", head))
        n = self.seed(head, title)
        self.prs[n]["body"] = body
        return n

    def update_pr(self, number, title, body):
        self.calls.append(("update", number))
        self.prs[number].update(title=title, body=body)

    def close_pr(self, number, comment):
        self.calls.append(("close", number))
        self.prs[number]["open"] = False
        self.prs[number]["comments"].append(comment)

    def issue_is_open(self, repo, number):
        self.calls.append(("hold", f"{repo}#{number}"))
        return self.hold_open

    def disable_auto_merge(self, number):
        was = self.prs[number]["auto"]
        self.prs[number]["auto"] = False
        return was

    def open_prs(self):
        return {p["head"]: p for p in self.prs.values() if p["open"]}


class FakeGit:
    """A remote holding branch -> files; a push happens only on a change."""

    def __init__(self):
        self.branches = {}
        self.pushes = []

    def publish_branch(self, branch, files, message):
        snapshot = (message, dict(files))
        if self.branches.get(branch) == snapshot:
            return False
        self.branches[branch] = snapshot
        self.pushes.append(branch)
        return True


def _sync(gh, git, results, run_url=RUN1, m=SEED, adapters=None):
    sync_prs(results, gh, git, manifest=m, adapters=adapters or _adapters(), root=ROOT, run_url=run_url)


# --- sync_prs: the pinned tests (plan Task 6) ---------------------------------------------------


def test_first_run_opens_one_pr_per_add():
    gh, git = FakeGh(), FakeGit()
    _sync(gh, git, _pr_results())
    prs = gh.open_prs()
    assert sorted(prs) == ["lifecycle/go-add-1.27", "lifecycle/python-add-3.15"]
    assert prs["lifecycle/python-add-3.15"]["title"] == "feat(versions): add python 3.15"
    assert prs["lifecycle/go-add-1.27"]["title"] == "feat(versions): add go 1.27"
    message, files = git.branches["lifecycle/python-add-3.15"]
    assert message == "feat(versions): add python 3.15"
    assert g.MANIFEST in files and g.WINDOW_JSON in files


def test_rerun_refreshes_existing_pr():
    gh, git = FakeGh(), FakeGit()
    results = _pr_results()
    _sync(gh, git, results, RUN1)
    (n,) = [k for k, p in gh.prs.items() if p["head"] == "lifecycle/python-add-3.15"]
    assert len(git.pushes) == 2

    _sync(gh, git, results, RUN2)
    assert [k for k, p in gh.prs.items() if p["head"] == "lifecycle/python-add-3.15"] == [n]
    assert len(gh.prs) == 2 and all(p["open"] for p in gh.prs.values())
    assert RUN2 in gh.prs[n]["body"] and RUN1 not in gh.prs[n]["body"]
    assert [c for c in gh.calls if c[0] == "create"] == [("create", "lifecycle/python-add-3.15"), ("create", "lifecycle/go-add-1.27")]
    assert ("update", n) in gh.calls
    # Same base, same change: the branch is not pushed again (no CI re-run).
    assert len(git.pushes) == 2


def test_rerun_after_the_base_moved_force_pushes_the_same_branch():
    gh, git = FakeGh(), FakeGit()
    _sync(gh, git, _pr_results())
    moved = apply_change(SEED, Change("python", "drop", "3.12", ""))
    _sync(gh, git, _pr_results(moved), m=moved)
    assert git.pushes.count("lifecycle/python-add-3.15") == 2
    assert [c[0] for c in gh.calls].count("create") == 2


def test_drop_pr_body_lists_go_case_followup():
    # Go 1.28 ships on 2027-02-09 and 1.26 reaches EOL the same day.
    go128 = {"cycle": "1.28", "releaseDate": "2027-02-09", "eol": False, "latest": "1.28.0", "lts": False}
    today = date(2027, 2, 20)
    m = apply_change(SEED, Change("go", "add", "1.27", ""), TargetVersion("1.27", date(2026, 8, 19), None, True))
    results = _pr_results(m, today=today, go_extra=[go128])
    by_family = {r.family: r for r in results}
    # endoflife.date gives 1.26 no EOL date in the fixture, so the drop is by the window rule.
    assert [(c.kind, c.version) for c in by_family["go"].changes] == [("add", "1.28"), ("drop", "1.26")]

    gh, git = FakeGh(), FakeGit()
    _sync(gh, git, results, m=m)
    prs = gh.open_prs()
    drop = prs["lifecycle/go-drop-1.26"]
    assert drop["title"] == "feat(versions): drop go 1.26 (EOL date unknown)"
    assert "- [ ] remove the `case go1.26*)` branch from `docker/go/Dockerfile.template`" in drop["body"]
    assert "- [ ] retire or update the `go-test-coverage` pin in `docker/pins/pins.yml`" in drop["body"]
    assert "https://endoflife.date/go" in drop["body"]
    # A drop is not held; an add is.
    assert "Hold" not in drop["body"]
    assert f"{ADD_HOLD_REPO}#{ADD_HOLD_ISSUE}" in prs["lifecycle/go-add-1.28"]["body"]
    _, files = git.branches["lifecycle/go-drop-1.26"]
    assert "1.26" not in [v.version for v in _family(mf.parse_manifest(__import__("yaml").safe_load(files[g.MANIFEST])), "go").versions]


def test_drop_title_uses_the_upstream_eol_date():
    results = _pr_results(today=date(2028, 11, 5))
    py = next(r for r in results if r.family == "python")
    assert ("drop", "3.12") in [(c.kind, c.version) for c in py.changes]
    gh, git = FakeGh(), FakeGit()
    _sync(gh, git, results)
    assert gh.open_prs()["lifecycle/python-drop-3.12"]["title"] == "feat(versions): drop python 3.12 (EOL 2028-10-31)"


def test_report_family_never_gets_pr():
    rust = FamilyResult("rust", (Change("rust", "add", "1.99", ""), Change("rust", "out_of_policy", "1.92", "")), None)
    results = [rust if r.family == "rust" else FamilyResult(r.family, (), None) for r in _pr_results()]
    gh, git = FakeGh(), FakeGit()
    _sync(gh, git, results)
    assert gh.prs == {} and git.pushes == []
    # Nothing to add, so the hold is never even looked up.
    assert [c for c in gh.calls if c[0] == "hold"] == []


# --- sync_prs: body, hold, auto-merge ------------------------------------------------------------


def test_add_pr_body():
    gh, git = FakeGh(), FakeGit()
    _sync(gh, git, _pr_results())
    body = gh.open_prs()["lifecycle/python-add-3.15"]["body"]
    assert "`add` for `python` 3.15" in body
    assert "GA 2026-10-09, EOL 2031-10-31" in body
    assert "https://endoflife.date/python" in body
    assert "`docs/site/docs/languages/python.md`" in body
    assert "**not** set to auto-merge" in body
    assert f"do not merge while {ADD_HOLD_REPO}#{ADD_HOLD_ISSUE} is open" in body
    assert "`runtime_published: false`" in body
    assert "- `docker/versions/manifest.yml`" in body and "- `docker/versions/window.json`" in body
    assert "## Manual follow-ups\n\nNone." in body
    go_body = gh.open_prs()["lifecycle/go-add-1.27"]["body"]
    assert "runtime_published" not in go_body


def test_hold_lifts_when_the_validation_issue_closes():
    gh, git = FakeGh(hold_open=False), FakeGit()
    _sync(gh, git, _pr_results())
    body = gh.open_prs()["lifecycle/python-add-3.15"]["body"]
    assert "Hold" not in body and "**not** set to auto-merge" in body


def test_auto_merge_is_turned_off_on_a_held_add(capsys):
    gh, git = FakeGh(), FakeGit()
    n = gh.seed("lifecycle/python-add-3.15", auto=True)
    m = gh.seed("lifecycle/go-add-1.27", auto=False)
    _sync(gh, git, _pr_results())
    assert gh.prs[n]["auto"] is False and gh.prs[m]["auto"] is False
    assert f"#{n}: auto-merge was enabled" in capsys.readouterr().out


def test_auto_merge_left_alone_when_not_held():
    gh, git = FakeGh(hold_open=False), FakeGit()
    n = gh.seed("lifecycle/python-add-3.15", auto=True)
    _sync(gh, git, _pr_results())
    assert gh.prs[n]["auto"] is True


# --- sync_prs: stale PRs and failures --------------------------------------------------------------


def test_pr_no_longer_reported_is_closed():
    gh, git = FakeGh(), FakeGit()
    stale = gh.seed("lifecycle/python-add-3.14")
    other = gh.seed("feature/123-something")
    gone = gh.seed("lifecycle/ruby-drop-3.2")
    _sync(gh, git, _pr_results())
    assert gh.prs[stale]["comments"] == [f"no longer reported in run {RUN1}"]
    assert gh.prs[gone]["comments"] == [f"no longer reported in run {RUN1}"]
    assert gh.prs[other]["open"]


def test_failing_family_keeps_its_prs_and_opens_none():
    gh, git = FakeGh(), FakeGit()
    kept = gh.seed("lifecycle/python-add-3.15")
    results = [
        FamilyResult("python", (), "SourceError: HTTP 503") if r.family == "python" else r for r in _pr_results()
    ]
    _sync(gh, git, results)
    assert gh.prs[kept]["open"] and gh.prs[kept]["body"] == "old"
    assert "lifecycle/python-add-3.15" not in git.branches
    assert "lifecycle/go-add-1.27" in gh.open_prs()


def test_sync_prs_rejects_bad_input():
    gh, git = FakeGh(), FakeGit()
    with pytest.raises(PublishError, match="run URL"):
        _sync(gh, git, [], run_url="")
    with pytest.raises(PublishError, match="'ruby'"):
        _sync(gh, git, [FamilyResult("ruby", (), None)])
    with pytest.raises(PublishError, match="two results"):
        _sync(gh, git, [FamilyResult("go", (), None), FamilyResult("go", (), None)])
    with pytest.raises(PublishError, match="no lifecycle adapter"):
        _sync(gh, git, _pr_results(), adapters={"python": _adapters()["python"]})


def test_sync_prs_fails_loud_on_an_inapplicable_change():
    # The manifest already lists 3.15: the add cannot be applied exactly.
    m = apply_change(SEED, Change("python", "add", "3.15", ""), TargetVersion("3.15", None, None, True))
    with pytest.raises(PublishError, match="python add 3.15: .*already lists"):
        _sync(FakeGh(), FakeGit(), _pr_results(), m=m)


def test_one_failing_change_does_not_block_the_others_or_close_its_pr():
    # Go has one version; dropping it alone cannot be applied.
    results = [
        FamilyResult("go", (Change("go", "drop", "1.26", "EOL reached"),), None) if r.family == "go" else r
        for r in _pr_results()
    ]
    gh, git = FakeGh(), FakeGit()
    existing = gh.seed("lifecycle/go-drop-1.26")
    with pytest.raises(PublishError, match="go drop 1.26: .*no versions"):
        _sync(gh, git, results)
    assert "lifecycle/python-add-3.15" in gh.open_prs()
    assert gh.prs[existing]["open"] and gh.prs[existing]["comments"] == []


def test_sync_prs_add_without_target_fails_loud():
    results = [
        replace(r, target=()) if r.family == "python" else r for r in _pr_results()
    ]
    with pytest.raises(PublishError, match="needs its target"):
        _sync(FakeGh(), FakeGit(), results)


# --- main --prs -------------------------------------------------------------------------------------


def _prs_argv(results):
    """`--prs` on the frozen manifest and the repo tree that matches it (#654)."""
    return ["--results", str(results), "--run-url", RUN1, "--prs",
            "--manifest", str(frozen.MANIFEST), "--root", str(ROOT)]


def test_main_prs_mode(tmp_path):
    path = tmp_path / "results.json"
    path.write_text(results_to_json(_pr_results(), TODAY))
    gh, git = FakeGh(), FakeGit()
    rc = publish.main(_prs_argv(path), gh=gh, git=git, adapters=_adapters())
    assert rc == 0
    assert sorted(gh.open_prs()) == ["lifecycle/go-add-1.27", "lifecycle/python-add-3.15"]


def test_main_prs_needs_base(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    path = tmp_path / "results.json"
    path.write_text(results_to_json([], TODAY))
    assert publish.main(["--results", str(path), "--run-url", RUN1, "--prs"]) == 1
    assert "--prs needs --base" in capsys.readouterr().err


def test_main_prs_failure_exits_1(tmp_path, capsys):
    path = tmp_path / "results.json"
    path.write_text(results_to_json(_pr_results(), TODAY))

    class BrokenGit:
        def publish_branch(self, branch, files, message):
            raise PublishError("git push failed (exit 1): permission denied")

    rc = publish.main(_prs_argv(path), gh=FakeGh(), git=BrokenGit(), adapters=_adapters())
    assert rc == 1
    assert "permission denied" in capsys.readouterr().err


def test_main_prs_default_clients(tmp_path, monkeypatch):
    built = {}

    class Gh(FakeGh):
        def __init__(self, repo, runner=None, base=None):
            super().__init__()
            built["gh"] = (repo, base)

    class Git(FakeGit):
        def __init__(self, root):
            super().__init__()
            built["git"] = root

    monkeypatch.setattr(publish, "GhCli", Gh)
    monkeypatch.setattr(publish, "GitCli", Git)
    path = tmp_path / "results.json"
    path.write_text(results_to_json([FamilyResult(f.key, (), None) for f in SEED.families], TODAY))
    rc = publish.main(["--results", str(path), "--run-url", RUN1, "--prs", "--repo", "o/r", "--base", "develop",
                      "--manifest", str(frozen.MANIFEST)])
    assert rc == 0
    assert built == {"gh": ("o/r", "develop"), "git": publish.REPO_ROOT}


# --- GhCli PR commands ---------------------------------------------------------------------------------


class Recorder:
    def __init__(self, *outputs):
        self.calls = []
        self._outputs = list(outputs)

    def __call__(self, args, stdin):
        self.calls.append((args, stdin))
        return self._outputs.pop(0) if self._outputs else ""


def test_ghcli_list_open_prs_filters_by_prefix():
    out = json.dumps([{"number": 1, "headRefName": "lifecycle/python-add-3.15"}, {"number": 2, "headRefName": "bot/x"}])
    rec = Recorder(out)
    assert GhCli("o/r", rec, base="develop").list_open_prs("lifecycle/") == [OpenPr(1, "lifecycle/python-add-3.15")]
    args, _ = rec.calls[0]
    assert args[:2] == ["pr", "list"] and ["--base", "develop"] == args[args.index("--base"):args.index("--base") + 2]


@pytest.mark.parametrize("out", ["nope", json.dumps([{"number": 1}])])
def test_ghcli_list_open_prs_rejects_malformed(out):
    with pytest.raises(PublishError, match="malformed"):
        GhCli("o/r", Recorder(out), base="develop").list_open_prs("lifecycle/")


def test_ghcli_list_open_prs_refuses_a_full_page(monkeypatch):
    monkeypatch.setattr(publish, "LIST_LIMIT", 1)
    with pytest.raises(PublishError, match="incomplete"):
        GhCli("o/r", Recorder(json.dumps([{"number": 1, "headRefName": "a"}])), base="d").list_open_prs("lifecycle/")


def test_ghcli_pr_methods_need_a_base():
    with pytest.raises(PublishError, match="base branch"):
        GhCli("o/r", Recorder()).create_pr("h", "t", "b")


def test_ghcli_create_update_close_pr():
    rec = Recorder("https://github.com/o/r/pull/77\n")
    cli = GhCli("o/r", rec, base="develop")
    assert cli.create_pr("lifecycle/python-add-3.15", "feat(versions): add python 3.15", "body") == 77
    cli.update_pr(77, "t2", "body2")
    cli.close_pr(78, "no longer reported in run x")
    assert rec.calls[0] == (
        ["pr", "create", "--repo", "o/r", "--base", "develop", "--head", "lifecycle/python-add-3.15",
         "--title", "feat(versions): add python 3.15", "--body-file", "-"],
        "body",
    )
    assert rec.calls[1] == (["pr", "edit", "77", "--repo", "o/r", "--title", "t2", "--body-file", "-"], "body2")
    assert rec.calls[2] == (
        ["pr", "close", "78", "--repo", "o/r", "--delete-branch", "--comment", "no longer reported in run x"], None
    )


def test_ghcli_create_pr_without_url_fails():
    with pytest.raises(PublishError, match="no PR URL"):
        GhCli("o/r", Recorder("oops"), base="develop").create_pr("h", "t", "b")


@pytest.mark.parametrize("state, expected", [("OPEN", True), ("CLOSED", False)])
def test_ghcli_issue_is_open(state, expected):
    rec = Recorder(json.dumps({"state": state}))
    assert GhCli("o/r", rec).issue_is_open("x/y", 9) is expected
    assert rec.calls[0][0] == ["issue", "view", "9", "--repo", "x/y", "--json", "state"]


@pytest.mark.parametrize("out, needle", [("nope", "malformed"), ("{}", "malformed"), ('{"state": "MERGED"}', "unexpected state")])
def test_ghcli_issue_is_open_fails_loud(out, needle):
    with pytest.raises(PublishError, match=needle):
        GhCli("o/r", Recorder(out)).issue_is_open("x/y", 9)


def test_ghcli_disable_auto_merge():
    rec = Recorder(json.dumps({"autoMergeRequest": {"enabledAt": "x"}}))
    assert GhCli("o/r", rec).disable_auto_merge(5) is True
    assert rec.calls[1][0] == ["pr", "merge", "5", "--repo", "o/r", "--disable-auto"]
    rec = Recorder(json.dumps({"autoMergeRequest": None}))
    assert GhCli("o/r", rec).disable_auto_merge(5) is False
    assert len(rec.calls) == 1
    with pytest.raises(PublishError, match="malformed"):
        GhCli("o/r", Recorder("nope")).disable_auto_merge(5)


# --- GitCli, against a real local repository and remote ---------------------------------------------


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def checkout(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    _git(tmp_path, "init", "-q", "-b", "develop", str(work))
    _git(work, "config", "user.name", "t")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "commit.gpgsign", "false")
    (work / "docker/versions").mkdir(parents=True)
    (work / "docker/versions/manifest.yml").write_text("base\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "base")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "-q", "origin", "develop")
    return work, remote


def test_gitcli_pushes_once_then_only_on_change(checkout):
    work, remote = checkout
    git = GitCli(work)
    files = {Path("docker/versions/manifest.yml"): "added\n", Path("docker/new/file.txt"): "new\n"}
    assert git.publish_branch("lifecycle/python-add-3.15", files, "feat(versions): add python 3.15") is True
    first = _git(remote, "rev-parse", "refs/heads/lifecycle/python-add-3.15")
    assert _git(remote, "show", f"{first}:docker/versions/manifest.yml") == "added"
    assert _git(remote, "log", "-1", "--format=%an <%ae>|%s", first) == f"{publish.BOT_NAME} <{publish.BOT_EMAIL}>|feat(versions): add python 3.15"
    assert _git(remote, "rev-parse", f"{first}^") == _git(work, "rev-parse", "HEAD")

    # A rerun on the same base builds the identical commit: nothing to push.
    assert git.publish_branch("lifecycle/python-add-3.15", files, "feat(versions): add python 3.15") is False
    # The main checkout and its worktree list are untouched.
    assert _git(work, "status", "--porcelain") == ""
    assert len(_git(work, "worktree", "list").splitlines()) == 1

    # Changed content (or a moved base) force-pushes the same branch.
    files[Path("docker/versions/manifest.yml")] = "added again\n"
    assert git.publish_branch("lifecycle/python-add-3.15", files, "feat(versions): add python 3.15") is True
    second = _git(remote, "rev-parse", "refs/heads/lifecycle/python-add-3.15")
    assert second != first and _git(remote, "rev-parse", f"{second}^") == _git(work, "rev-parse", "HEAD")


def test_gitcli_refuses_a_change_that_writes_nothing(checkout):
    work, _ = checkout
    git = GitCli(work)
    with pytest.raises(PublishError, match="writes nothing new"):
        git.publish_branch("lifecycle/x-add-1", {Path("docker/versions/manifest.yml"): "base\n"}, "m")
    with pytest.raises(PublishError, match="nothing to commit"):
        git.publish_branch("lifecycle/x-add-1", {}, "m")
    assert len(_git(work, "worktree", "list").splitlines()) == 1


def test_gitcli_push_failure_raises(checkout, tmp_path):
    work, _ = checkout
    git = GitCli(work, remote=str(tmp_path / "missing.git"))
    with pytest.raises(PublishError, match="git"):
        git.publish_branch("lifecycle/x-add-1", {Path("docker/versions/manifest.yml"): "new\n"}, "m")
