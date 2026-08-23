from pathlib import Path

import extract_pins
import check_pins
import generate_catalog

DOCKER = Path(__file__).resolve().parent.parent


def test_extractor_finds_known_exact_pins():
    tools = {p.tool for p in extract_pins.extract(DOCKER)}
    # exact-version pins that survive the #418 audit: binary release-tarball
    # tools kept as mechanism pins (shellcheck, hadolint, opentofu) and the
    # security scanners deferred to #422 (trivy). These exercise every surviving
    # install idiom (ARG tarball, ARG binary, security tarball).
    assert "shellcheck" in tools
    assert "hadolint" in tools
    assert "opentofu" in tools
    assert "trivy" in tools


def test_extractor_drops_freed_package_manager_pins():
    # #418 freed the package-manager tools (npm/pip/uv/go install/cargo) by
    # dropping the version. They must no longer surface as exact pins, or
    # check_pins would false-flag their (now-deleted) pins.yml entries.
    #
    # golangci-lint was in this list until #569: it is now a REAL pin again
    # (v2.13.0 raised its Go floor to 1.26, so the Go 1.25 image must hold
    # v2.12.2). It is documented in pins.yml as `active`, so check_pins accepts
    # it — being freed by #418 does not make a tool permanently unpinnable when
    # upstream later forces a hold. See test_golangci_lint_is_a_documented_pin.
    tools = {p.tool for p in extract_pins.extract(DOCKER)}
    for freed in ("uv", "markdownlint-cli", "yamllint",
                  "cargo-deny", "mkdocs-material", "pyyaml"):
        assert freed not in tools


def test_golangci_lint_is_a_documented_pin():
    # #569: re-pinned for Go 1.25 only. Guards the pairing this suite exists to
    # protect — an extracted pin with a matching pins.yml justification.
    pins = {p.tool: p.version for p in extract_pins.extract(DOCKER)}
    assert pins.get("golangci-lint") == "2.12.2"
    assert check_pins.load_pins(DOCKER)["golangci-lint"]["state"] == "active"


def test_extractor_excludes_major_only_matrix():
    tools = {p.tool for p in extract_pins.extract(DOCKER)}
    # NODE_MAJOR=22 and language matrix are least-specific, not exact pins
    assert "node" not in tools


def test_extractor_finds_conditional_shell_pin():
    # go-test-coverage's version lives in GTC_VERSION="v2.18.8", not inline @vX —
    # the shell-assignment pattern + _ALIASES must still surface it, or check_pins
    # would false-flag its pins.yml entry as stale and fail CI.
    tools = {p.tool for p in extract_pins.extract(DOCKER)}
    assert "go-test-coverage" in tools


def test_check_passes_when_every_pin_documented(tmp_path, monkeypatch):
    assert check_pins.main(DOCKER) == 0  # after Step 7 pins.yml is complete


def test_check_fails_on_undocumented_pin(tmp_path):
    # a fixture image dir with a pin but empty pins.yml. `tmp_path` mirrors the
    # real `docker/` layout: fragments under common/, catalog under pins/.
    (tmp_path / "common").mkdir()
    (tmp_path / "common" / "x.dockerfile").write_text("ARG FOO_VERSION=1.2.3\n")
    (tmp_path / "pins").mkdir()
    (tmp_path / "pins" / "pins.yml").write_text("pins: {}\n")
    assert check_pins.main(tmp_path) == 1


def _write_fixture(tmp_path, state):
    (tmp_path / "common").mkdir()
    (tmp_path / "common" / "x.dockerfile").write_text("ARG FOO_VERSION=1.2.3\n")
    (tmp_path / "pins").mkdir()
    (tmp_path / "pins" / "pins.yml").write_text(
        "pins:\n"
        f"  foo: {{constraint: latest, inducing_release: null, "
        f"deterministic: false, reason: r, state: {state}, tracking_issue: null}}\n"
    )


def test_check_accepts_auto_managed_state(tmp_path):
    # auto-managed (#435) is a legitimately pinned state; the gate must pass it.
    _write_fixture(tmp_path, "auto-managed")
    assert check_pins.main(tmp_path) == 0


def test_check_fails_on_unknown_state(tmp_path):
    # A typo'd or unmodelled state must fail loud — the reconciliation makes the
    # gate state-aware rather than silently accepting anything.
    _write_fixture(tmp_path, "bogus")
    assert check_pins.main(tmp_path) == 1


def test_auto_managed_is_a_valid_state():
    assert "auto-managed" in check_pins.VALID_STATES


def test_catalog_lists_every_documented_pin():
    md = generate_catalog.render(DOCKER)
    assert "| go-test-coverage |" in md
    assert "inducing" in md.lower()


def test_catalog_check_matches_committed_file():
    assert generate_catalog.render(DOCKER) == (DOCKER / "pins" / "CATALOG.md").read_text()
