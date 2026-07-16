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


def test_harvest_parses_probe_output():
    def probe(image, tool):
        return "shellcheck 0.11.0" if tool == "shellcheck" else ""

    got = harvest_installed.harvest(["prod-base:latest"], ["shellcheck"], probe=probe)
    assert got["prod-base:latest"]["shellcheck"] == "0.11.0"
