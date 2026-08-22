from pathlib import Path

import harvest_installed
import report_exposure as r

DOCKER = Path(__file__).resolve().parent.parent


def test_flags_pin_when_leading_edge_moved_past_inducer():
    pins = {"foo": {"inducing_release": "2.0.0", "state": "active", "constraint": "<2.0.0", "reason": "x", "deterministic": True}}
    due = r.due_for_reevaluation(pins, latest={"foo": "2.1.0"})
    assert "foo" in due


def test_not_flagged_when_inducer_still_leading():
    pins = {"foo": {"inducing_release": "2.0.0", "state": "active", "constraint": "<2.0.0", "reason": "x", "deterministic": True}}
    assert r.due_for_reevaluation(pins, latest={"foo": "2.0.0"}) == []


def test_harvest_joins_into_report():
    installed = {"prod-go:1.26": {"golangci-lint": "2.12.2", "goimports": "0.45.0"}}
    md = r.render(DOCKER, latest={}, installed=installed)
    assert "prod-go:1.26" in md and "golangci-lint: 2.12.2" in md


def test_auto_managed_surfaced_as_own_category():
    # #435: the report must distinguish auto-managed tools in a dedicated section,
    # separate from the active-pin re-evaluation list. Uses the real pins.yml,
    # where the binary tools (the #418/#422 set) are auto-managed.
    md = r.render(DOCKER, latest={}, installed={})
    assert "## Auto-managed" in md
    section = md.split("## Auto-managed", 1)[1]
    for tool in ("shellcheck", "shfmt", "actionlint", "git-cliff", "hadolint",
                 "opentofu", "nfpm", "trivy", "scorecard"):
        assert f"- {tool}:" in section


def test_auto_managed_not_flagged_for_reevaluation():
    # auto-managed pins carry no inducing_release and are not `active`, so they
    # never appear in the due-for-re-evaluation list even when upstream moves.
    pins = {"foo": {"inducing_release": None, "state": "auto-managed",
                    "constraint": "latest", "reason": "x", "deterministic": False}}
    assert r.due_for_reevaluation(pins, latest={"foo": "9.9.9"}) == []


def test_matrix_includes_cpp_images():
    # #480: the exposure matrix must cover the published C++ images so their
    # installed tool versions are harvested alongside the other languages.
    images = r._image_matrix("prod")
    for image in ("prod-cpp-clang:20", "prod-cpp-clang:19",
                  "prod-cpp-gcc:14", "prod-cpp-gcc:13"):
        assert image in images


def test_harvest_parses_probe_output():
    def probe(image, tool):
        return "shellcheck 0.11.0" if tool == "shellcheck" else ""

    got = harvest_installed.harvest(["prod-base:latest"], ["shellcheck"], probe=probe)
    assert got["prod-base:latest"]["shellcheck"] == "0.11.0"


# --- #574: auto-managed drift is its own signal ----------------------------
# The report had no way to say "an auto-managed tool is behind", which is how
# five bump PRs stacked unnoticed for a month while trivy sat on 0.72.0.

AUTO = {"state": "auto-managed", "inducing_release": None,
        "constraint": "latest, auto-bumped weekly", "reason": "x",
        "deterministic": False}


def test_auto_managed_behind_flags_unmerged_bump():
    pins = {"trivy": dict(AUTO)}
    got = r.auto_managed_behind(pins, pinned={"trivy": "0.72.0"},
                                latest={"trivy": "0.74.0"})
    assert got == [("trivy", "0.72.0", "0.74.0")]


def test_auto_managed_behind_silent_when_current():
    pins = {"trivy": dict(AUTO)}
    assert r.auto_managed_behind(pins, pinned={"trivy": "0.74.0"},
                                 latest={"trivy": "0.74.0"}) == []


def test_auto_managed_behind_ignores_non_auto_managed():
    # An `active` break-hold is BEHIND on purpose — that is what a hold is.
    # Flagging it here would duplicate (and contradict) due_for_reevaluation.
    pins = {"go-test-coverage": {"state": "active", "inducing_release": "2.18.4",
                                 "constraint": "==2.18.3 on Go 1.25", "reason": "x",
                                 "deterministic": True}}
    assert r.auto_managed_behind(pins, pinned={"go-test-coverage": "2.18.3"},
                                 latest={"go-test-coverage": "2.19.0"}) == []


def test_auto_managed_behind_skips_unknown_upstream():
    # Unresolvable upstream must never raise a false alarm.
    pins = {"trivy": dict(AUTO)}
    assert r.auto_managed_behind(pins, pinned={"trivy": "0.72.0"}, latest={}) == []


def test_two_signals_stay_separate():
    # The whole point of #574: a behind auto-managed tool is NOT "due for
    # re-evaluation", and vice versa. Regression guard on conflating them.
    pins = {"trivy": dict(AUTO)}
    assert r.due_for_reevaluation(pins, latest={"trivy": "0.74.0"}) == []
    assert r.auto_managed_behind(pins, pinned={"trivy": "0.72.0"},
                                 latest={"trivy": "0.74.0"})


def test_source_pins_takes_newest_when_tool_pinned_per_image():
    # go-test-coverage is pinned per Go version (v2.18.3 on 1.25). The
    # version-of-record is the newest pin; the older one is a deliberate hold.
    pinned = r.source_pins(DOCKER)
    assert pinned["trivy"]
    assert "." in pinned["trivy"]


def test_report_renders_behind_section():
    md = r.render(DOCKER, latest={}, installed={})
    assert "## Auto-managed tools behind the leading edge" in md
