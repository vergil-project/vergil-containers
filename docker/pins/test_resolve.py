"""Hermetic unit tests for the leading-edge resolver. The redirect fetch is
INJECTED — no network (and no curl) is ever exercised here."""
import re
from pathlib import Path

import pytest

import resolve_latest as rl

TOOLS = {
    "shellcheck", "shfmt", "actionlint", "git-cliff", "hadolint",
    "opentofu", "nfpm", "trivy", "scorecard", "uv", "cargo-nextest",
}

NEXTEST_ASSET = ("https://github.com/nextest-rs/nextest/releases/download/"
                 "cargo-nextest-0.9.152/cargo-nextest-0.9.152-x86_64-unknown-linux-gnu.tar.gz")


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
    def tag(tool):
        prefix = rl.TOOL_TAG_PREFIXES.get(tool)
        return f"{prefix}9.9.9" if prefix else "v9.9.9"

    fetch = _fetch({rl.TOOL_LATEST_URLS.get(tool, repo):
                    f"https://github.com/{repo}/releases/tag/{tag(tool)}"
                    for tool, repo in rl.TOOL_REPOS.items()})
    got = rl.resolve_all(fetch=fetch)
    assert set(got) == TOOLS
    assert all(v == "9.9.9" for v in got.values())


def test_cargo_nextest_resolves_from_get_nexte_st():
    # vergil-containers#885: nextest-rs/nextest's /releases/latest may be another
    # crate's release, so cargo-nextest resolves from nextest's documented
    # latest-binary URL, whose redirect names the release asset.
    seen = []

    def fetch(source):
        seen.append(source)
        return NEXTEST_ASSET

    got = rl.resolve_all({"cargo-nextest": rl.TOOL_REPOS["cargo-nextest"]}, fetch=fetch)
    assert got == {"cargo-nextest": "0.9.152"}
    assert seen == ["https://get.nexte.st/latest/linux"]


def test_cargo_nextest_fails_loud_on_another_crates_release():
    # A tag without the cargo-nextest- prefix (nextest-runner's, say) is never
    # taken for a cargo-nextest version.
    fetch = _fetch({rl.TOOL_LATEST_URLS["cargo-nextest"]:
                    "https://github.com/nextest-rs/nextest/releases/tag/nextest-runner-0.130.0"})
    with pytest.raises(rl.ResolutionError, match="does not start with 'cargo-nextest-'"):
        rl.resolve_all({"cargo-nextest": rl.TOOL_REPOS["cargo-nextest"]}, fetch=fetch)


def test_cargo_nextest_fails_loud_on_a_prerelease_tag():
    fetch = _fetch({rl.TOOL_LATEST_URLS["cargo-nextest"]: NEXTEST_ASSET.replace(
        "cargo-nextest-0.9.152/", "cargo-nextest-0.9.152-b.1/")})
    with pytest.raises(rl.ResolutionError, match="is not a cargo-nextest-v"):
        rl.resolve_all({"cargo-nextest": rl.TOOL_REPOS["cargo-nextest"]}, fetch=fetch)


def test_parse_tag_from_a_release_asset_location():
    assert rl.parse_tag_from_location(NEXTEST_ASSET) == "cargo-nextest-0.9.152"


def test_latest_url_takes_a_full_url_as_it_is():
    assert rl._latest_url("x/y") == "https://github.com/x/y/releases/latest"
    assert rl._latest_url("https://get.nexte.st/latest/linux") == "https://get.nexte.st/latest/linux"


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


def test_curl_location_takes_the_asset_location_not_the_cdn_one(monkeypatch):
    # get.nexte.st redirects to the release asset, which redirects again to a
    # CDN URL that names no release; the asset's location is the one returned.
    class _Proc:
        stdout = (
            "HTTP/2 302\n"
            f"location: {NEXTEST_ASSET}\n"
            "HTTP/2 302\n"
            "location: https://release-assets.githubusercontent.com/github-production-release-asset/1/2?sig=x\n"
            "HTTP/2 200\n"
        )

    calls = []
    monkeypatch.setattr(rl.subprocess, "run", lambda args, **k: calls.append(args) or _Proc())
    assert rl._curl_location("https://get.nexte.st/latest/linux") == NEXTEST_ASSET
    assert calls == [["curl", "-fsSLI", "https://get.nexte.st/latest/linux"]]


def test_rewrite_args_updates_only_changed_tools(tmp_path):
    (tmp_path / "common").mkdir()
    frag = tmp_path / "common" / "tools.dockerfile"
    frag.write_text("ARG SHELLCHECK_VERSION=0.11.0\nARG TRIVY_VERSION=0.72.0\n")
    changed = rl.rewrite_args(tmp_path, {"shellcheck": "0.12.0", "trivy": "0.72.0"})
    assert changed == {"shellcheck": ("0.11.0", "0.12.0")}
    text = frag.read_text()
    assert "ARG SHELLCHECK_VERSION=0.12.0" in text
    assert "ARG TRIVY_VERSION=0.72.0" in text


def test_uv_resolves_from_its_bare_release_tag():
    # uv tags its releases without a `v` (vergil-containers#728).
    fetch = _fetch({rl.TOOL_REPOS["uv"]:
                    "https://github.com/astral-sh/uv/releases/tag/0.13.7"})
    assert rl.resolve(rl.TOOL_REPOS["uv"], fetch=fetch) == "0.13.7"


def test_every_tool_arg_is_in_a_live_fragment():
    # rewrite_args with each tool's current source version changes nothing and
    # raises if any TOOL_ARGS entry has no `ARG <NAME>=` line in docker/common.
    docker = Path(__file__).resolve().parent.parent
    current = {}
    for tool, arg in rl.TOOL_ARGS.items():
        for frag in sorted((docker / "common").glob("*.dockerfile")):
            match = re.search(rf"^ARG {arg}=(\S+)$", frag.read_text(), re.MULTILINE)
            if match:
                current[tool] = match.group(1)
                break
    assert set(current) == TOOLS
    assert rl.rewrite_args(docker, current) == {}


def test_rewrite_args_fails_loud_when_arg_missing(tmp_path):
    (tmp_path / "common").mkdir()
    (tmp_path / "common" / "tools.dockerfile").write_text("ARG SHELLCHECK_VERSION=0.11.0\n")
    with pytest.raises(rl.ResolutionError):
        rl.rewrite_args(tmp_path, {"nfpm": "2.48.0"})
