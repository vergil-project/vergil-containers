from pathlib import Path

import extract_pins
import check_pins
import generate_catalog

DOCKER = Path(__file__).resolve().parent.parent


def test_extractor_finds_known_exact_pins():
    tools = {p.tool for p in extract_pins.extract(DOCKER)}
    # exact-version pins that exist today (spec Appendix A)
    assert "shellcheck" in tools
    assert "trivy" in tools
    assert "uv" in tools
    assert "golangci-lint" in tools


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


def test_catalog_lists_every_documented_pin():
    md = generate_catalog.render(DOCKER)
    assert "| go-test-coverage |" in md
    assert "inducing" in md.lower()


def test_catalog_check_matches_committed_file():
    assert generate_catalog.render(DOCKER) == (DOCKER / "pins" / "CATALOG.md").read_text()
