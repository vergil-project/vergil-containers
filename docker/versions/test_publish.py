import json
from datetime import date

import pytest

from lifecycle import core, publish
from lifecycle.core import Change, FamilyResult, SourceError
from lifecycle.publish import LABEL, GhCli, OpenIssue, PublishError, sync_issues
from lifecycle.report import results_to_json

RUN1 = "https://github.com/o/r/actions/runs/1"
RUN2 = "https://github.com/o/r/actions/runs/2"
RUN3 = "https://github.com/o/r/actions/runs/3"
AUTOMATION = {"python": "pr", "go": "pr", "rust": "report", "cpp-gcc": "report"}


class FakeGh:
    """An in-memory issue tracker implementing the GhClient protocol."""

    def __init__(self):
        self.issues = {}  # number -> dict(title, body, labels, open, comments)
        self.calls = []
        self._next = 100

    def seed(self, title, labels=(LABEL,), body="old"):
        n = self._next
        self._next += 1
        self.issues[n] = {"title": title, "body": body, "labels": list(labels), "open": True, "comments": []}
        return n

    def list_open_issues(self, label):
        self.calls.append(("list", label))
        return [OpenIssue(n, i["title"]) for n, i in self.issues.items() if i["open"] and label in i["labels"]]

    def create_issue(self, title, body, labels):
        self.calls.append(("create", title))
        return self.seed(title, labels, body)

    def update_issue(self, number, body):
        self.calls.append(("update", number))
        self.issues[number]["body"] = body

    def close_issue(self, number, comment):
        self.calls.append(("close", number))
        self.issues[number]["open"] = False
        self.issues[number]["comments"].append(comment)

    def open_titles(self):
        return sorted(i["title"] for i in self.issues.values() if i["open"])

    def numbers_titled(self, title):
        return [n for n, i in self.issues.items() if i["title"] == title]


def _result(family, *changes, error=None):
    return FamilyResult(family, tuple(Change(family, k, v, f"detail {k} {v}") for k, v in changes), error)


def _sync(gh, results, run_url=RUN1):
    sync_issues(results, gh, automation=AUTOMATION, run_url=run_url)


# --- The pinned tests (plan Task 5) ---------------------------------------------------


def test_report_family_change_opens_issue():
    gh = FakeGh()
    _sync(gh, [_result("rust", ("add", "1.99"), ("out_of_policy", "1.92"))])
    assert gh.open_titles() == [
        "language lifecycle: rust add 1.99",
        "language lifecycle: rust out_of_policy 1.92",
    ]
    (n,) = gh.numbers_titled("language lifecycle: rust add 1.99")
    issue = gh.issues[n]
    assert issue["labels"] == [LABEL]
    assert "detail add 1.99" in issue["body"] and RUN1 in issue["body"]


def test_existing_issue_is_updated_not_duplicated():
    gh = FakeGh()
    results = [_result("rust", ("add", "1.99"))]
    _sync(gh, results, RUN1)
    _sync(gh, results, RUN2)
    (n,) = gh.numbers_titled("language lifecycle: rust add 1.99")
    assert gh.issues[n]["open"]
    assert RUN2 in gh.issues[n]["body"]
    assert [c for c in gh.calls if c[0] == "create"] == [("create", "language lifecycle: rust add 1.99")]


def test_failure_issue_refreshed_then_closed():
    gh = FakeGh()
    title = "lifecycle check failing for rust"

    _sync(gh, [_result("rust", error="SourceError: HTTP 429 Too Many Requests")], RUN1)
    (n,) = gh.numbers_titled(title)
    assert gh.issues[n]["open"] and "HTTP 429 Too Many Requests" in gh.issues[n]["body"]

    _sync(gh, [_result("rust", error="SourceError: HTTP 503 Service Unavailable")], RUN2)
    assert gh.numbers_titled(title) == [n]
    assert gh.issues[n]["open"] and "HTTP 503" in gh.issues[n]["body"] and RUN2 in gh.issues[n]["body"]

    _sync(gh, [_result("rust")], RUN3)
    assert gh.numbers_titled(title) == [n]
    assert not gh.issues[n]["open"]
    assert gh.issues[n]["comments"] == [f"recovered in run {RUN3}"]


def test_stale_change_issue_closed():
    gh = FakeGh()
    _sync(gh, [_result("rust", ("add", "1.99"), ("add", "1.98"))], RUN1)
    _sync(gh, [_result("rust", ("add", "1.99"))], RUN2)
    (stale,) = gh.numbers_titled("language lifecycle: rust add 1.98")
    assert not gh.issues[stale]["open"]
    assert gh.issues[stale]["comments"] == [f"no longer reported in run {RUN2}"]
    assert gh.open_titles() == ["language lifecycle: rust add 1.99"]


def test_pr_family_changes_open_no_issue():
    gh = FakeGh()
    _sync(gh, [_result("python", ("add", "3.15")), _result("go", ("drop", "1.25"))])
    assert gh.issues == {}


def test_pr_family_change_no_pr_can_carry_opens_issue():
    """A blocked or EOL-soon version on a `pr` family gets no PR, so it needs an issue."""
    gh = FakeGh()
    _sync(gh, [_result("python", ("add", "3.15"), ("blocked", "3.16"), ("eol_soon", "3.12"))])
    assert gh.open_titles() == [
        "language lifecycle: python blocked 3.16",
        "language lifecycle: python eol_soon 3.12",
    ]


# --- Edges -----------------------------------------------------------------------


def test_pr_family_failure_still_opens_failure_issue():
    gh = FakeGh()
    _sync(gh, [_result("python", error="boom")])
    assert gh.open_titles() == ["lifecycle check failing for python"]


def test_failing_family_keeps_its_change_issues_open():
    gh = FakeGh()
    _sync(gh, [_result("rust", ("add", "1.99"))], RUN1)
    _sync(gh, [_result("rust", error="boom")], RUN2)
    assert gh.open_titles() == ["language lifecycle: rust add 1.99", "lifecycle check failing for rust"]


def test_failure_issue_for_family_gone_from_manifest_is_closed():
    gh = FakeGh()
    n = gh.seed("lifecycle check failing for ruby")
    _sync(gh, [_result("rust")])
    assert not gh.issues[n]["open"]
    assert "no longer in the manifest" in gh.issues[n]["comments"][0]


def test_change_issue_for_family_gone_from_manifest_is_closed():
    gh = FakeGh()
    n = gh.seed("language lifecycle: ruby drop 3.2")
    _sync(gh, [_result("rust")])
    assert gh.issues[n]["comments"] == [f"no longer reported in run {RUN1}"]


@pytest.mark.parametrize(
    "title",
    [
        "something a human labelled",
        "language lifecycle: not a managed title",
        "lifecycle check failing for two words",
        "lifecycle check failing for ",
    ],
)
def test_unmanaged_labelled_issues_are_left_alone(title):
    gh = FakeGh()
    n = gh.seed(title)
    _sync(gh, [_result("rust")])
    assert gh.issues[n]["open"] and gh.issues[n]["comments"] == []


def test_issues_without_the_label_are_not_seen():
    gh = FakeGh()
    n = gh.seed("language lifecycle: rust add 1.99", labels=())
    _sync(gh, [_result("rust", ("add", "1.99"))])
    assert len(gh.numbers_titled("language lifecycle: rust add 1.99")) == 2
    assert gh.issues[n]["body"] == "old"


def test_duplicate_open_issues_are_collapsed_onto_the_oldest():
    gh = FakeGh()
    first = gh.seed("language lifecycle: rust add 1.99")
    second = gh.seed("language lifecycle: rust add 1.99")
    _sync(gh, [_result("rust", ("add", "1.99"))])
    assert gh.issues[first]["open"] and RUN1 in gh.issues[first]["body"]
    assert not gh.issues[second]["open"]
    assert gh.issues[second]["comments"][0].startswith(f"duplicate of #{first}")


def test_result_for_unknown_family_is_an_error():
    with pytest.raises(PublishError, match="'ruby'"):
        _sync(FakeGh(), [_result("ruby")])


def test_duplicate_result_family_is_an_error():
    with pytest.raises(PublishError, match="two results"):
        _sync(FakeGh(), [_result("rust"), _result("rust")])


def test_run_url_is_required():
    with pytest.raises(PublishError, match="run URL"):
        sync_issues([], FakeGh(), automation=AUTOMATION, run_url="")


def test_rate_limited_registry_becomes_a_failure_issue():
    """A Docker Hub (or GitHub API) rate limit must reach the tracker as a
    failure issue, never read as 'not installable' or 'in sync'."""

    class RateLimited:
        key = "rust"

        def fetch(self):
            raise SourceError("https://hub.docker.com/v2/x: HTTP 429 Too Many Requests")

        def target(self, releases, today):  # pragma: no cover - never reached
            raise AssertionError

        def extra_changes(self, change):  # pragma: no cover
            return []

    import manifest as mf

    fam = mf.Family("rust", "rust", "", "RUST_VERSION", "report", (mf.ManifestVersion("1.93", None, None, True, None),))
    results = core.run(mf.Manifest((fam,)), {"rust": RateLimited()}, date(2026, 10, 21))
    gh = FakeGh()
    _sync(gh, results)
    (n,) = gh.numbers_titled("lifecycle check failing for rust")
    assert "HTTP 429" in gh.issues[n]["body"]


# --- main -----------------------------------------------------------------------------


def _write_results(tmp_path, results):
    path = tmp_path / "results.json"
    path.write_text(results_to_json(results, date(2026, 10, 21)))
    return path


def test_main_syncs_from_results_json_against_the_real_manifest(tmp_path):
    path = _write_results(tmp_path, [_result("rust", ("add", "1.99")), _result("python", ("add", "3.15"))])
    gh = FakeGh()
    assert publish.main(["--results", str(path), "--run-url", RUN1], gh=gh) == 0
    assert gh.open_titles() == ["language lifecycle: rust add 1.99"]


def test_main_malformed_results_fails(tmp_path, capsys):
    path = tmp_path / "results.json"
    path.write_text(json.dumps({"schema": 99}))
    assert publish.main(["--results", str(path), "--run-url", RUN1], gh=FakeGh()) == 1
    assert "lifecycle publish:" in capsys.readouterr().err


def test_main_missing_results_file_fails(tmp_path):
    assert publish.main(["--results", str(tmp_path / "nope.json"), "--run-url", RUN1], gh=FakeGh()) == 1


def test_main_without_repo_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    path = _write_results(tmp_path, [_result("rust")])
    assert publish.main(["--results", str(path), "--run-url", RUN1]) == 1
    assert "no repository" in capsys.readouterr().err


def test_main_gh_failure_fails(tmp_path, monkeypatch):
    def failing(args, stdin=None):
        raise PublishError("gh label create failed (exit 1): HTTP 403")

    monkeypatch.setattr(publish, "run_gh", failing)
    path = _write_results(tmp_path, [_result("rust")])
    assert publish.main(["--results", str(path), "--run-url", RUN1, "--repo", "o/r"]) == 1


# --- GhCli (command construction, with an injected runner) -------------------------------


class Recorder:
    def __init__(self, *outputs):
        self.calls = []
        self._outputs = list(outputs)

    def __call__(self, args, stdin):
        self.calls.append((args, stdin))
        return self._outputs.pop(0) if self._outputs else ""


def test_ghcli_list_open_issues():
    rec = Recorder(json.dumps([{"number": 7, "title": "t"}]))
    assert GhCli("o/r", rec).list_open_issues(LABEL) == [OpenIssue(7, "t")]
    args, _ = rec.calls[0]
    assert args[:2] == ["issue", "list"] and ["--label", LABEL] == args[args.index("--label"):args.index("--label") + 2]
    assert "--repo" in args and "o/r" in args and "open" in args


@pytest.mark.parametrize("out", ["not json", json.dumps([{"title": "no number"}]), json.dumps([None])])
def test_ghcli_list_rejects_malformed_output(out):
    with pytest.raises(PublishError, match="malformed"):
        GhCli("o/r", Recorder(out)).list_open_issues(LABEL)


def test_ghcli_list_refuses_a_full_page(monkeypatch):
    monkeypatch.setattr(publish, "LIST_LIMIT", 2)
    out = json.dumps([{"number": 1, "title": "a"}, {"number": 2, "title": "b"}])
    with pytest.raises(PublishError, match="incomplete"):
        GhCli("o/r", Recorder(out)).list_open_issues(LABEL)


def test_ghcli_create_issue_parses_number_and_passes_body_on_stdin():
    rec = Recorder("https://github.com/o/r/issues/42\n")
    assert GhCli("o/r", rec).create_issue("t", "the body", [LABEL]) == 42
    args, stdin = rec.calls[0]
    assert stdin == "the body"
    assert args[:2] == ["issue", "create"] and "--body-file" in args and LABEL in args


def test_ghcli_create_issue_without_url_fails():
    with pytest.raises(PublishError, match="no issue URL"):
        GhCli("o/r", Recorder("something else")).create_issue("t", "b", [LABEL])


def test_ghcli_update_close_and_label_commands():
    rec = Recorder()
    cli = GhCli("o/r", rec)
    cli.update_issue(5, "new body")
    cli.close_issue(6, "recovered in run x")
    cli.ensure_label(LABEL)
    assert rec.calls[0] == (["issue", "edit", "5", "--repo", "o/r", "--body-file", "-"], "new body")
    assert rec.calls[1] == (["issue", "close", "6", "--repo", "o/r", "--comment", "recovered in run x"], None)
    assert rec.calls[2][0][:3] == ["label", "create", LABEL] and "--force" in rec.calls[2][0]


def test_run_gh_raises_on_nonzero_exit(monkeypatch):
    class Proc:
        returncode = 1
        stdout = ""
        stderr = "HTTP 403: Resource not accessible by integration\n"

    monkeypatch.setattr(publish.subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(PublishError, match="Resource not accessible"):
        publish.run_gh(["issue", "list"])


def test_run_gh_returns_stdout(monkeypatch):
    seen = {}

    class Proc:
        returncode = 0
        stdout = "out"
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["input"] = cmd, kwargs["input"]
        return Proc()

    monkeypatch.setattr(publish.subprocess, "run", fake_run)
    assert publish.run_gh(["issue", "edit"], "body") == "out"
    assert seen == {"cmd": ["gh", "issue", "edit"], "input": "body"}
