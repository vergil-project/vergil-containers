import ast
import json
import re
from datetime import date
from pathlib import Path

import pytest

import manifest as mf
from lifecycle import check, core, report
from lifecycle.core import Change, FamilyResult, SourceError, TargetVersion, UpstreamRelease

HERE = Path(__file__).resolve().parent
TODAY = date(2026, 10, 21)


def _family(versions=("3.14", "3.13", "3.12"), automation="pr", key="fam", eols=None):
    eols = eols or {}
    return mf.Family(
        key=key,
        language=key,
        token_prefix="",
        build_arg="FAM_VERSION",
        automation=automation,
        versions=tuple(mf.ManifestVersion(v, None, eols.get(v), True, None) for v in versions),
    )


def _t(version, ga=date(2020, 1, 1), eol=None, installable=True):
    return TargetVersion(version, ga, eol, installable)


def _kinds(changes):
    return [(c.kind, c.version) for c in changes]


# --- classify ------------------------------------------------------------------


def test_add_when_ga_target_missing():
    target = [_t("3.15", ga=date(2026, 10, 9)), _t("3.14"), _t("3.13"), _t("3.12")]
    changes = core.classify(_family(), target, TODAY, 90)
    assert _kinds(changes) == [("add", "3.15")]
    assert changes[0].family == "fam"
    assert "GA 2026-10-09" in changes[0].detail


def test_no_backfill_skips_older_than_oldest():
    target = [_t("3.14"), _t("3.13"), _t("3.12"), _t("3.11")]
    assert core.classify(_family(), target, TODAY, 90) == []


def test_drop_past_eol():
    target = [_t("3.14"), _t("3.13"), _t("3.12", eol=date(2026, 10, 21))]
    changes = core.classify(_family(), target, TODAY, 90)
    assert _kinds(changes) == [("drop", "3.12")]
    assert "EOL reached" in changes[0].detail


def test_drop_past_manifest_eol_when_target_has_no_date():
    fam = _family(eols={"3.12": date(2026, 1, 1)})
    assert _kinds(core.classify(fam, [_t("3.14"), _t("3.13"), _t("3.12")], TODAY, 90)) == [("drop", "3.12")]


def test_drop_when_absent_from_target():
    changes = core.classify(_family(), [_t("3.14"), _t("3.13")], TODAY, 90)
    assert _kinds(changes) == [("drop", "3.12")]
    assert "not in the upstream support window" in changes[0].detail


def test_future_release_date_is_not_ga():
    target = [_t("3.16", ga=date(2027, 10, 1)), _t("3.14"), _t("3.13"), _t("3.12")]
    assert core.classify(_family(), target, TODAY, 90) == []


def test_missing_release_date_is_not_ga():
    target = [_t("3.15", ga=None), _t("3.14"), _t("3.13"), _t("3.12")]
    assert core.classify(_family(), target, TODAY, 90) == []


def test_blocked_when_not_installable():
    target = [_t("3.15", installable=False), _t("3.14"), _t("3.13"), _t("3.12")]
    changes = core.classify(_family(), target, TODAY, 90)
    assert _kinds(changes) == [("blocked", "3.15")]
    assert "not installable" in changes[0].detail


def test_report_family_drop_is_out_of_policy():
    fam = _family(automation="report")
    changes = core.classify(fam, [_t("3.14"), _t("3.13")], TODAY, 90)
    assert _kinds(changes) == [("out_of_policy", "3.12")]


def test_eol_soon_within_lookahead():
    target = [_t("3.14"), _t("3.13", eol=date(2027, 1, 19)), _t("3.12", eol=date(2027, 1, 20))]
    changes = core.classify(_family(), target, TODAY, 90)
    assert _kinds(changes) == [("eol_soon", "3.13")]
    assert "2027-01-19" in changes[0].detail


def test_empty_target_is_an_error_not_a_drop_all():
    with pytest.raises(SourceError, match="empty target window"):
        core.classify(_family(), [], TODAY, 90)


def test_target_without_any_ga_version_in_window_is_an_error():
    target = [_t("3.16", ga=date(2027, 10, 1)), _t("3.11")]
    with pytest.raises(SourceError, match="no GA target version"):
        core.classify(_family(), target, TODAY, 90)


def test_duplicate_target_version_is_an_error():
    with pytest.raises(SourceError, match="twice"):
        core.classify(_family(), [_t("3.14"), _t("3.14")], TODAY, 90)


def test_changes_are_ordered_adds_then_drops():
    target = [_t("3.16", installable=False), _t("3.15"), _t("3.14"), _t("3.13", eol=date(2026, 12, 1))]
    changes = core.classify(_family(), target, TODAY, 90)
    assert _kinds(changes) == [("blocked", "3.16"), ("add", "3.15"), ("eol_soon", "3.13"), ("drop", "3.12")]


# --- window helpers --------------------------------------------------------------


def _r(version, ga=date(2020, 1, 1), eol=None, lts=False, lts_since=None):
    return UpstreamRelease(version, ga, eol, lts, lts_since)


def test_ga_not_eol():
    rs = [_r("4", ga=date(2027, 1, 1)), _r("3"), _r("2", eol=TODAY), _r("1", ga=None)]
    assert [r.version for r in core.ga_not_eol(rs, TODAY)] == ["3"]


def test_newest_n_semantic_order():
    rs = [_r("1.9"), _r("1.27"), _r("1.26"), _r("1.10")]
    assert [r.version for r in core.newest_n(rs, 2)] == ["1.27", "1.26"]
    with pytest.raises(ValueError):
        core.newest_n(rs, 0)


def test_lts_only_respects_lts_start_date():
    rs = [_r("26", lts=True, lts_since=date(2026, 10, 28)), _r("25"), _r("24", lts=True)]
    assert [r.version for r in core.lts_only(rs, TODAY)] == ["24"]
    assert [r.version for r in core.lts_only(rs, date(2026, 10, 29))] == ["26", "24"]


# --- run ---------------------------------------------------------------------------


class FakeAdapter:
    def __init__(self, key, target=None, exc=None):
        self.key = key
        self._target = target
        self._exc = exc

    def fetch(self):
        if self._exc:
            raise self._exc
        return []

    def target(self, releases, today):
        return self._target

    def extra_changes(self, change):
        return []


def _manifest(*families):
    return mf.Manifest(families=families)


def test_run_records_releases_and_target():
    releases = [UpstreamRelease("3.15", date(2026, 10, 9), None, False)]

    class Adapter(FakeAdapter):
        def fetch(self):
            return releases

    target = [_t("3.15"), _t("3.14"), _t("3.13"), _t("3.12")]
    (result,) = core.run(_manifest(_family(key="fam")), {"fam": Adapter("fam", target=target)}, TODAY)
    assert result.releases == tuple(releases)
    assert result.target == tuple(target)


def test_run_records_adapter_error_and_continues():
    m = _manifest(_family(key="first"), _family(key="second"))
    adapters = {
        "first": FakeAdapter("first", exc=SourceError("upstream down")),
        "second": FakeAdapter("second", target=[_t("3.15"), _t("3.14"), _t("3.13"), _t("3.12")]),
    }
    first, second = core.run(m, adapters, TODAY)
    assert first == FamilyResult("first", (), "SourceError: upstream down")
    assert second.error is None
    assert _kinds(second.changes) == [("add", "3.15")]


def test_run_records_empty_target_and_value_error_and_missing_adapter():
    m = _manifest(_family(key="empty"), _family(key="bad"), _family(key="orphan"))
    adapters = {"empty": FakeAdapter("empty", target=[]), "bad": FakeAdapter("bad", exc=ValueError("bad date"))}
    results = core.run(m, adapters, TODAY)
    assert [r.family for r in results] == ["empty", "bad", "orphan"]
    assert "empty target window" in results[0].error
    assert results[1].error == "ValueError: bad date"
    assert "no lifecycle adapter" in results[2].error
    assert all(r.changes == () for r in results)


def test_run_does_not_swallow_unexpected_exceptions():
    m = _manifest(_family(key="first"))
    with pytest.raises(KeyError):
        core.run(m, {"first": FakeAdapter("first", exc=KeyError("bug"))}, TODAY)


# --- report ------------------------------------------------------------------------


RESULTS = [
    FamilyResult(
        "a",
        (Change("a", "add", "3.15", "GA 2026-10-09, EOL 2031-10-31"),),
        None,
        (
            UpstreamRelease("3.15", date(2026, 10, 9), date(2031, 10, 31), False),
            UpstreamRelease("3.9", date(2020, 10, 5), core.EOL_DATE_UNKNOWN, True, date(2021, 1, 1)),
            UpstreamRelease("3.16", None, None, False),
        ),
        (TargetVersion("3.15", date(2026, 10, 9), date(2031, 10, 31), True), TargetVersion("3.16", None, None, False)),
    ),
    FamilyResult("b", (), None),
    FamilyResult("c", (), "SourceError: upstream down"),
]


def test_report_markdown_covers_every_family():
    text = report.render_markdown(RESULTS, TODAY)
    assert "| a | changes | add 3.15 |" in text
    assert "| b | in sync | - |" in text
    assert "| c | check failed | - |" in text
    assert "Check failed: SourceError: upstream down" in text
    assert "- `add` 3.15: GA 2026-10-09" in text


def test_report_json_roundtrip():
    text = report.results_to_json(RESULTS, TODAY)
    assert json.loads(text)["today"] == "2026-10-21"
    assert report.results_from_json(text) == RESULTS


@pytest.mark.parametrize(
    "doc",
    [
        {"schema": 1, "results": []},
        {"schema": 2},
        {"schema": 2, "results": [{"family": "a"}]},
        {"schema": 2, "results": [{"family": "a", "error": None, "changes": [{"kind": "nope"}]}]},
        {"schema": 2, "results": [{"family": "a", "error": None, "changes": [dict(family="a", kind="bad", version="1", detail="")]}]},
        {"schema": 2, "results": [{"family": "a", "error": None, "changes": [], "releases": []}]},
        {"schema": 2, "results": [{"family": "a", "error": None, "changes": [], "releases": [], "target": [
            {"version": "1", "ga": "not a date", "eol": None, "installable": True}]}]},
        {"schema": 2, "results": [{"family": "a", "error": None, "changes": [], "releases": [], "target": [
            {"version": "1", "ga": 20261009, "eol": None, "installable": True}]}]},
        {"schema": 2, "results": [{"family": "a", "error": None, "changes": [], "releases": [], "target": [
            {"version": "1", "ga": None, "eol": None, "installable": "yes"}]}]},
    ],
)
def test_report_json_rejects_malformed(doc):
    with pytest.raises(ValueError):
        report.results_from_json(json.dumps(doc))


# --- check.py CLI -------------------------------------------------------------------


def _write_manifest(tmp_path, *families):
    path = tmp_path / "manifest.yml"
    path.write_text(mf.dump_manifest(_manifest(*families)))
    return path


def test_check_writes_outputs_and_exits_0_when_clean(tmp_path, capsys):
    path = _write_manifest(tmp_path, _family(key="fam"))
    adapters = {"fam": FakeAdapter("fam", target=[_t("3.15"), _t("3.14"), _t("3.13"), _t("3.12")])}
    rc = check.main(
        ["--manifest", str(path), "--today", "2026-10-21", "--report", str(tmp_path / "r.md"), "--json", str(tmp_path / "r.json")],
        adapters=adapters,
    )
    assert rc == 0
    assert "| fam | changes | add 3.15 |" in (tmp_path / "r.md").read_text()
    (result,) = report.results_from_json((tmp_path / "r.json").read_text())
    assert _kinds(result.changes) == [("add", "3.15")]
    assert "add 3.15" in capsys.readouterr().out


def test_check_exits_1_on_family_error_after_writing_outputs(tmp_path, capsys):
    path = _write_manifest(tmp_path, _family(key="ok"), _family(key="broken"))
    adapters = {
        "ok": FakeAdapter("ok", target=[_t("3.14"), _t("3.13"), _t("3.12")]),
        "broken": FakeAdapter("broken", exc=SourceError("upstream down")),
    }
    rc = check.main(
        ["--manifest", str(path), "--today", "2026-10-21", "--report", str(tmp_path / "r.md"), "--json", str(tmp_path / "r.json")],
        adapters=adapters,
    )
    assert rc == 1
    assert "| broken | check failed |" in (tmp_path / "r.md").read_text()
    assert [r.error for r in report.results_from_json((tmp_path / "r.json").read_text())] == [
        None,
        "SourceError: upstream down",
    ]
    assert "lifecycle check failed for broken: SourceError: upstream down" in capsys.readouterr().err


def test_check_bad_manifest_exits_1(tmp_path, capsys):
    path = tmp_path / "manifest.yml"
    path.write_text("schema: 1\nfamilies: []\n")
    assert check.main(["--manifest", str(path)], adapters={}) == 1
    assert "families must be a non-empty list" in capsys.readouterr().err


def test_registry_covers_python_and_go():
    from lifecycle.adapters import ADAPTERS

    assert {"python", "go"} <= set(ADAPTERS)
    assert all(key == adapter.key for key, adapter in ADAPTERS.items())


# --- principle 7: no language branches in shared code ------------------------------

LANGUAGE_WORDS = re.compile(r"\b(python|go|golang|rust|java|clang|gcc|node|ruby)\b", re.IGNORECASE)
SHARED = ["core.py", "sources.py", "report.py", "publish.py", "apply.py"]


@pytest.mark.parametrize("name", SHARED)
def test_core_has_no_language_literals(name):
    tree = ast.parse((HERE / "lifecycle" / name).read_text())
    offending = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and LANGUAGE_WORDS.search(node.value)
    ]
    assert offending == []


def test_language_literal_check_detects_a_literal():
    tree = ast.parse('X = "dev-python"\nY = f"{z} for Go"\n')
    hits = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and LANGUAGE_WORDS.search(n.value)]
    assert hits == ["dev-python", " for Go"]
