"""Hermetic unit tests for the leading-edge resolver. The redirect fetch is
INJECTED — no network (and no curl) is ever exercised here."""
import pytest

import resolve_latest as rl

TOOLS = {
    "shellcheck", "shfmt", "actionlint", "git-cliff", "hadolint",
    "opentofu", "nfpm", "trivy", "scorecard",
}


def _fetch(mapping):
    """Return a fetch(repo) that yields a canned `location` header value."""
    def fetch(repo):
        return mapping[repo]
    return fetch


def test_map_covers_exactly_the_expected_tools():
    assert set(rl.TOOL_REPOS) == TOOLS
    assert set(rl.TOOL_ARGS) == TOOLS


def test_resolve_parses_tag_and_strips_v_prefix():
    fetch = _fetch({"koalaman/shellcheck":
                    "https://github.com/koalaman/shellcheck/releases/tag/v0.12.0"})
    assert rl.resolve("koalaman/shellcheck", fetch=fetch) == "0.12.0"


def test_resolve_accepts_tag_without_v_prefix():
    fetch = _fetch({"x/y": "https://github.com/x/y/releases/tag/1.2.3"})
    assert rl.resolve("x/y", fetch=fetch) == "1.2.3"


def test_resolve_all_covers_every_tool():
    fetch = _fetch({repo: f"https://github.com/{repo}/releases/tag/v9.9.9"
                    for repo in rl.TOOL_REPOS.values()})
    got = rl.resolve_all(fetch=fetch)
    assert set(got) == TOOLS
    assert all(v == "9.9.9" for v in got.values())


def test_resolve_fails_loud_when_location_has_no_tag():
    with pytest.raises(rl.ResolutionError):
        rl.resolve("x/y", fetch=lambda repo: "https://github.com/x/y/releases")


def test_resolve_fails_loud_on_non_semver_tag():
    fetch = _fetch({"x/y": "https://github.com/x/y/releases/tag/nightly"})
    with pytest.raises(rl.ResolutionError):
        rl.resolve("x/y", fetch=fetch)


def test_curl_location_extracts_the_tag_location_header(monkeypatch):
    # Simulate `curl -fsSLI` header output; the default fetcher must pull the
    # location header that points at the release tag. No network runs.
    class _Proc:
        stdout = (
            "HTTP/2 302\n"
            "location: https://github.com/koalaman/shellcheck/releases/tag/v0.12.0\n"
            "HTTP/2 200\n"
            "content-type: text/html\n"
        )

    monkeypatch.setattr(rl.subprocess, "run", lambda *a, **k: _Proc())
    assert rl._curl_location("koalaman/shellcheck").endswith("/releases/tag/v0.12.0")


def test_curl_location_raises_when_no_location_header(monkeypatch):
    class _Proc:
        stdout = "HTTP/2 200\ncontent-type: text/html\n"

    monkeypatch.setattr(rl.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(rl.ResolutionError):
        rl._curl_location("x/y")


def test_rewrite_args_updates_only_changed_tools(tmp_path):
    (tmp_path / "common").mkdir()
    frag = tmp_path / "common" / "tools.dockerfile"
    frag.write_text("ARG SHELLCHECK_VERSION=0.11.0\nARG TRIVY_VERSION=0.72.0\n")
    changed = rl.rewrite_args(tmp_path, {"shellcheck": "0.12.0", "trivy": "0.72.0"})
    assert changed == {"shellcheck": ("0.11.0", "0.12.0")}
    text = frag.read_text()
    assert "ARG SHELLCHECK_VERSION=0.12.0" in text
    assert "ARG TRIVY_VERSION=0.72.0" in text


def test_rewrite_args_fails_loud_when_arg_missing(tmp_path):
    (tmp_path / "common").mkdir()
    (tmp_path / "common" / "tools.dockerfile").write_text("ARG SHELLCHECK_VERSION=0.11.0\n")
    with pytest.raises(rl.ResolutionError):
        rl.rewrite_args(tmp_path, {"nfpm": "2.48.0"})
