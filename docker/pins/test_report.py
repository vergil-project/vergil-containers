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
    # where the binary tools (the #418/#422 set plus osv-scanner, #487) are
    # auto-managed.
    md = r.render(DOCKER, latest={}, installed={})
    assert "## Auto-managed" in md
    section = md.split("## Auto-managed", 1)[1]
    for tool in ("shellcheck", "shfmt", "actionlint", "git-cliff", "hadolint",
                 "opentofu", "nfpm", "trivy", "scorecard", "osv-scanner"):
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
