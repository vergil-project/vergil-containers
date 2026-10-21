"""The runtime-published signal (plan Task 13b): reading the vergil apt index,
the `runtime` and `runtime_missing` change kinds, and the runtime PR."""
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
import yaml

import generate as g
import manifest as mf
from lifecycle import core, runtime
from lifecycle.adapters.python import PythonAdapter, runtime_package
from lifecycle.apply import ApplyError, apply_change, branch_name, parse_branch, pr_title
from lifecycle.core import Change, NotFoundError, SourceError, TargetVersion
from lifecycle.publish import sync_issues, sync_prs
from lifecycle.report import results_from_json, results_to_json
from lifecycle.runtime import APT_URL, read_index, runtime_published

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FIXTURES = HERE / "fixtures"
TODAY = date(2026, 10, 21)
SEED = mf.load_manifest(HERE / "manifest.yml")
RUN = "https://github.com/o/r/actions/runs/1"
RELEASE = (FIXTURES / "apt-vergil-noble-Release").read_text()
PACKAGES = (FIXTURES / "apt-vergil-noble-amd64-Packages").read_text()
SLOTS = [(s, a) for s in runtime.SUITES for a in ("amd64", "arm64")]


def _stanza(name):
    return f"Package: {name}\nVersion: 1.0-1\nArchitecture: amd64\n"


def apt_fetch(extra=(), missing=(), releases=None, packages=None):
    """A fake vergil apt repository: the captured noble index (Release and
    amd64 Packages) served for every suite and architecture, plus the packages
    in `extra`, minus the (suite, arch, package) triples in `missing`."""
    calls = []

    def fetch(url):
        calls.append(url)
        for suite in runtime.SUITES:
            if url == f"{APT_URL}/dists/{suite}/Release":
                if releases is not None:
                    return releases[suite].encode()
                return RELEASE.replace("noble", suite).encode()
            for arch in ("amd64", "arm64"):
                if url == f"{APT_URL}/dists/{suite}/main/binary-{arch}/Packages":
                    if packages is not None:
                        return packages.encode()
                    stanzas = PACKAGES.strip().split("\n\n") + [_stanza(p) for p in extra]
                    kept = [
                        s for s in stanzas
                        if not any((suite, arch, name) == (ms, ma, s.splitlines()[0][len("Package: "):])
                                   for ms, ma, name in missing)
                    ]
                    return ("\n\n".join(s.strip() for s in kept) + "\n").encode()
        raise AssertionError(f"unexpected URL {url}")

    fetch.calls = calls
    return fetch


def _endoflife(url):
    assert url == "https://endoflife.date/api/python.json", url
    return (FIXTURES / "endoflife-python.json").read_bytes()


def _python(apt=None):
    """The Python adapter on the endoflife.date fixture, every slim tag present,
    reading its runtime evidence from `apt` (the captured index by default)."""
    apt = apt or apt_fetch()
    return PythonAdapter(fetch=_endoflife, tag_exists=lambda image, tag: True, runtime_index=lambda: read_index(apt))


def _family(m, key="python"):
    (family,) = [f for f in m.families if f.key == key]
    return family


def _check(m, apt=None):
    (result,) = core.run(mf.Manifest(families=(_family(m),)), {"python": _python(apt)}, TODAY)
    return result


def _kinds(changes):
    return [(c.kind, c.version) for c in changes]


WITH_315 = apply_change(
    SEED, Change("python", "add", "3.15", ""), TargetVersion("3.15", date(2026, 10, 9), date(2031, 10, 31), True)
)


# --- reading the index ------------------------------------------------------------------


def test_captured_index_lists_the_series_package_exactly():
    fetch = apt_fetch()
    index = read_index(fetch)
    assert sorted(index.listings) == sorted(SLOTS)
    assert index.published("vergil-python3.14") is True
    # The patch-pinned legacy package is a different package, not the series.
    assert index.published("vergil-python3.1") is False
    assert index.published("vergil-python3.15") is False
    # One Release per suite, one Packages per suite and architecture.
    assert len(fetch.calls) == len(runtime.SUITES) + len(SLOTS)


def test_runtime_published_reads_through_the_fetcher():
    assert runtime_published("vergil-python3.14", apt_fetch()) is True
    assert runtime_published("vergil-python3.15", apt_fetch()) is False
    assert runtime_published("vergil-python3.15", apt_fetch(extra=["vergil-python3.15"])) is True


def test_runtime_package_name():
    assert runtime_package("3.15") == "vergil-python3.15"


def test_partly_published_package_is_an_error():
    fetch = apt_fetch(extra=["vergil-python3.15"], missing=[("resolute", "arm64", "vergil-python3.15")])
    with pytest.raises(SourceError, match=r"vergil-python3\.15 is published, but not for resolute/arm64"):
        runtime_published("vergil-python3.15", fetch)


@pytest.mark.parametrize("exc", [SourceError("HTTP 503"), NotFoundError("HTTP 404")])
def test_runtime_index_unreachable_is_error(exc):
    def fetch(url):
        raise exc

    with pytest.raises(SourceError):
        read_index(fetch)
    # Through the check: the family fails loud, it never reads as "not published".
    result = _check(SEED, apt=fetch)
    assert result.changes == ()
    assert result.error is not None and str(exc) in result.error


@pytest.mark.parametrize(
    "release, needle",
    [
        ("", "empty Release file"),
        ("Origin: vergil\nCodename: jammy\nArchitectures: amd64\n", "Codename is 'jammy'"),
        ("Codename: {suite}\nComponents: main\n", "declares no architecture"),
        ("Codename: {suite}\nArchitectures: all\n", "declares no architecture"),
        ("Codename {suite}\n", "malformed line"),
    ],
)
def test_malformed_release_is_an_error(release, needle):
    releases = {s: release.format(suite=s) for s in runtime.SUITES}
    with pytest.raises(SourceError, match=needle):
        read_index(apt_fetch(releases=releases))


@pytest.mark.parametrize(
    "packages, needle",
    [
        ("", "lists no package"),
        ("\n\n", "lists no package"),
        ("Version: 1.0\n", "no Package field"),
        ("Package:\n", "no Package field"),
        (": orphan\n", "malformed line"),
    ],
)
def test_malformed_packages_is_an_error(packages, needle):
    with pytest.raises(SourceError, match=needle):
        read_index(apt_fetch(packages=packages))


def test_non_utf8_index_is_an_error():
    def fetch(url):
        return b"\xff\xfe"

    with pytest.raises(SourceError, match="not UTF-8"):
        read_index(fetch)


def test_architecture_all_is_not_a_slot():
    releases = {s: f"Codename: {s}\nArchitectures: all amd64\n" for s in runtime.SUITES}
    index = read_index(apt_fetch(releases=releases))
    assert sorted(index.listings) == [(s, "amd64") for s in sorted(runtime.SUITES)]


# --- the adapter's evidence ------------------------------------------------------------------


def test_python_target_carries_runtime_evidence():
    target = _python().target(_python().fetch(), TODAY)
    assert {t.version: t.runtime_published for t in target} == {
        "3.15": False, "3.14": True, "3.13": False, "3.12": False, "3.11": False,
    }


def test_python_reads_the_index_once_per_target():
    calls = []

    def index():
        calls.append(1)
        return read_index(apt_fetch())

    adapter = PythonAdapter(fetch=_endoflife, tag_exists=lambda image, tag: True, runtime_index=index)
    adapter.target(adapter.fetch(), TODAY)
    assert calls == [1]
    # An empty window reads nothing (the core reports it as an error).
    assert adapter.target([], TODAY) == [] and calls == [1]


def test_python_default_index_reads_through_the_fetcher():
    apt = apt_fetch()

    def fetch(url):
        return _endoflife(url) if url.startswith("https://endoflife.date/") else apt(url)

    adapter = PythonAdapter(fetch=fetch, tag_exists=lambda image, tag: True)
    assert {t.version: t.runtime_published for t in adapter.target(adapter.fetch(), TODAY)}["3.14"] is True
    assert apt.calls


# --- classification -------------------------------------------------------------------------


def test_seed_against_the_captured_index_has_no_runtime_change():
    assert _kinds(_check(SEED).changes) == [("add", "3.15")]


def test_runtime_flag_flips_when_package_appears():
    # 3.15 is added with runtime_published: false; nothing is published yet.
    assert _family(WITH_315).versions[0].runtime_published is False
    assert _kinds(_check(WITH_315).changes) == []

    # vergil-python publishes the 3.15 series: the next run reports it...
    result = _check(WITH_315, apt=apt_fetch(extra=["vergil-python3.15"]))
    assert _kinds(result.changes) == [("runtime", "3.15")]
    (change,) = result.changes
    target = next(t for t in result.target if t.version == "3.15")

    # ...and applying it records the flag, in the manifest and the published window.
    after = apply_change(WITH_315, change, target)
    assert [(v.version, v.runtime_published) for v in _family(after).versions] == [
        ("3.15", True), ("3.14", True), ("3.13", False), ("3.12", False),
    ]
    assert [f for f in after.families if f.key != "python"] == [f for f in WITH_315.families if f.key != "python"]
    (python,) = json.loads(g.render_window_json(after))["languages"]["python"]["families"]
    assert [(v["version"], v["runtime_published"]) for v in python["versions"]][:2] == [("3.15", True), ("3.14", True)]
    # Once recorded, the same evidence is in sync.
    assert _check(after, apt=apt_fetch(extra=["vergil-python3.15"])).changes == ()


def test_runtime_missing_when_a_recorded_package_disappears():
    result = _check(SEED, apt=apt_fetch(missing=[(s, a, "vergil-python3.14") for s, a in SLOTS]))
    assert _kinds(result.changes) == [("add", "3.15"), ("runtime_missing", "3.14")]
    assert "package index does not list it" in result.changes[1].detail


def test_dropped_version_gets_no_runtime_change():
    # On 2028-11-05 3.12 is past EOL; publishing its runtime then changes nothing.
    (result,) = core.run(
        mf.Manifest(families=(_family(WITH_315),)),
        {"python": _python(apt_fetch(extra=["vergil-python3.12", "vergil-python3.15"]))},
        date(2028, 11, 5),
    )
    assert ("drop", "3.12") in _kinds(result.changes)
    assert ("runtime", "3.12") not in _kinds(result.changes)
    assert ("runtime", "3.15") in _kinds(result.changes)


def _fam(runtime_published):
    return mf.Family(
        key="fam", language="fam", token_prefix="", build_arg="FAM_VERSION", automation="pr",
        versions=(mf.ManifestVersion("2", None, None, True, runtime_published),
                  mf.ManifestVersion("1", None, None, True, runtime_published)),
    )


def _tv(version, runtime_published, ga=date(2020, 1, 1)):
    return TargetVersion(version, ga, None, True, runtime_published)


def test_runtime_family_without_evidence_is_an_error():
    with pytest.raises(SourceError, match="gives no runtime evidence for 2"):
        core.classify(_fam(False), [_tv("2", None), _tv("1", False)], TODAY, 90)


def test_evidence_for_a_family_without_runtime_is_an_error():
    with pytest.raises(SourceError, match="manifest records no runtime package"):
        core.classify(_fam(None), [_tv("2", True), _tv("1", None)], TODAY, 90)


def test_non_ga_target_evidence_is_not_checked_or_used():
    target = [_tv("3", None, ga=None), _tv("2", True), _tv("1", False)]
    assert _kinds(core.classify(_fam(False), target, TODAY, 90)) == [("runtime", "2")]


def test_runtime_changes_come_after_the_others():
    eols = TargetVersion("1", date(2020, 1, 1), date(2026, 11, 1), True, True)
    changes = core.classify(_fam(False), [_tv("3", False), _tv("2", True), eols], TODAY, 90)
    assert _kinds(changes) == [("add", "3"), ("eol_soon", "1"), ("runtime", "2"), ("runtime", "1")]


# --- apply, names, results JSON -------------------------------------------------------------------


@pytest.mark.parametrize(
    "m, change, target, needle",
    [
        (WITH_315, Change("python", "runtime", "3.15", ""), None, "needs a target version"),
        (WITH_315, Change("python", "runtime", "3.15", ""), TargetVersion("3.14", None, None, True, True), "needs a target"),
        (WITH_315, Change("python", "runtime", "3.15", ""), TargetVersion("3.15", None, None, True, False), "needs a target"),
        (WITH_315, Change("python", "runtime", "3.15", ""), TargetVersion("3.15", None, None, True, None), "needs a target"),
        (SEED, Change("python", "runtime", "3.14", ""), TargetVersion("3.14", None, None, True, True), "not false"),
        (SEED, Change("python", "runtime", "3.16", ""), TargetVersion("3.16", None, None, True, True), "does not list"),
        (SEED, Change("go", "runtime", "1.26", ""), TargetVersion("1.26", None, None, True, True), "no runtime package"),
        (SEED, Change("python", "runtime_missing", "3.14", ""), None, "reported, not applied"),
    ],
)
def test_apply_runtime_rejects_what_it_cannot_apply_exactly(m, change, target, needle):
    with pytest.raises(ApplyError, match=needle):
        apply_change(m, change, target)


def test_runtime_branch_and_title():
    change = Change("python", "runtime", "3.15", "")
    assert branch_name(change) == "lifecycle/python-runtime-3.15"
    assert parse_branch("lifecycle/python-runtime-3.15") == ("python", "runtime", "3.15")
    assert parse_branch("lifecycle/python-runtime_missing-3.15") is None
    assert pr_title(change, None) == "feat(versions): record the published python 3.15 runtime"
    with pytest.raises(ApplyError, match="has no pull request"):
        pr_title(Change("python", "runtime_missing", "3.14", ""), None)


def test_results_json_carries_runtime_evidence():
    result = _check(WITH_315, apt=apt_fetch(extra=["vergil-python3.15"]))
    (back,) = results_from_json(results_to_json([result], TODAY))
    assert back == result
    assert {t.version: t.runtime_published for t in back.target}["3.15"] is True


# --- publishing ----------------------------------------------------------------------------------


class FakePrs:
    def __init__(self):
        self.created = {}
        self.hold_checked = False

    def list_open_prs(self, head_prefix):
        return []

    def create_pr(self, head, title, body):
        self.created[head] = (title, body)
        return 700 + len(self.created)

    def update_pr(self, number, title, body):
        raise AssertionError("no PR is open")

    def close_pr(self, number, comment):
        raise AssertionError("no PR is open")

    def issue_is_open(self, repo, number):
        self.hold_checked = True
        return True

    def disable_auto_merge(self, number):
        return False


class FakeGit:
    def __init__(self):
        self.branches = {}

    def publish_branch(self, branch, files, message):
        self.branches[branch] = (message, dict(files))
        return True


def test_runtime_change_opens_a_pr_citing_the_package_index():
    result = _check(WITH_315, apt=apt_fetch(extra=["vergil-python3.15"]))
    other = [core.FamilyResult(f.key, (), None) for f in WITH_315.families if f.key != "python"]
    gh, git = FakePrs(), FakeGit()
    sync_prs([result, *other], gh, git, manifest=WITH_315, adapters={"python": _python()}, root=ROOT, run_url=RUN)

    title, body = gh.created["lifecycle/python-runtime-3.15"]
    assert title == "feat(versions): record the published python 3.15 runtime"
    assert f"- Upstream evidence: {APT_URL}" in body
    assert "records `runtime_published: true`" in body
    # The add hold applies to version adds only.
    assert "Hold" not in body and gh.hold_checked is False
    message, files = git.branches["lifecycle/python-runtime-3.15"]
    recorded = mf.parse_manifest(yaml.safe_load(files[g.MANIFEST]))
    assert _family(recorded).versions[0] == replace(_family(WITH_315).versions[0], runtime_published=True)
    assert g.WINDOW_JSON in files


def test_runtime_missing_opens_an_issue_not_a_pr():
    result = _check(SEED, apt=apt_fetch(missing=[(s, a, "vergil-python3.14") for s, a in SLOTS]))

    class Issues:
        def __init__(self):
            self.created = []

        def list_open_issues(self, label):
            return []

        def create_issue(self, title, body, labels):
            self.created.append(title)
            return 1

    gh = Issues()
    sync_issues([result], gh, automation={"python": "pr"}, run_url=RUN)
    assert gh.created == ["language lifecycle: python runtime_missing 3.14"]
