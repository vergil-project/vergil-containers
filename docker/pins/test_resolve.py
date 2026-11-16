"""Hermetic unit tests for the leading-edge resolver. The redirect fetch is
INJECTED — no network (and no curl) is ever exercised here."""
import re
from pathlib import Path

import pytest

import resolve_latest as rl

TOOLS = {
    "shellcheck", "shfmt", "actionlint", "git-cliff", "hadolint",
    "opentofu", "nfpm", "trivy", "scorecard", "uv", "cargo-nextest", "yq",
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


# --- workflow image pins (vergil-containers#914) ------------------------------

REGISTRY_REPO = "distribution/distribution"


def test_workflow_pins_cover_exactly_the_registry():
    assert rl.WORKFLOW_PIN_REPOS == {"registry": REGISTRY_REPO}
    assert set(rl.WORKFLOW_PIN_NAMES) == set(rl.WORKFLOW_PIN_REPOS)
    # A workflow image pin is not a fragment ARG: rewrite_args never sees it.
    assert not set(rl.WORKFLOW_PIN_REPOS) & set(rl.TOOL_REPOS)


def test_every_workflow_pin_is_in_the_live_file():
    docker = Path(__file__).resolve().parent.parent
    current = {tool: rl.read_workflow_pin(docker, tool) for tool in rl.WORKFLOW_PIN_REPOS}
    assert re.fullmatch(r"3\.\d+\.\d+", current["registry"])
    assert rl.plan_workflow_pins(docker, current) == {}


def _workflow_pins(root: Path, text: str) -> Path:
    (root / "pins").mkdir(parents=True, exist_ok=True)
    path = root / "pins" / "workflow-images.txt"
    path.write_text(text)
    return path


def test_a_bump_within_the_major_is_planned_and_written(tmp_path):
    path = _workflow_pins(tmp_path, "# keep me\nREGISTRY_VERSION=3.1.2\n")
    changed = rl.plan_workflow_pins(tmp_path, {"registry": "3.2.0"})
    assert changed == {"registry": ("3.1.2", "3.2.0")}
    assert path.read_text() == "# keep me\nREGISTRY_VERSION=3.1.2\n"  # planning writes nothing
    rl.write_workflow_pins(tmp_path, changed)
    assert path.read_text() == "# keep me\nREGISTRY_VERSION=3.2.0\n"


def test_an_unchanged_pin_plans_nothing(tmp_path):
    _workflow_pins(tmp_path, "REGISTRY_VERSION=3.1.2\n")
    assert rl.plan_workflow_pins(tmp_path, {"registry": "3.1.2"}) == {}


@pytest.mark.parametrize("old, new", [("3.1.2", "4.0.0"), ("3.1.2", "2.8.3"), ("3.9.9", "30.0.0")])
def test_a_major_version_change_is_refused(tmp_path, old, new):
    path = _workflow_pins(tmp_path, f"REGISTRY_VERSION={old}\n")
    with pytest.raises(rl.MajorVersionError, match=rf"registry: its newest release, {re.escape(new)}, "
                                                    rf"is not in the major version of the pinned {re.escape(old)}"):
        rl.plan_workflow_pins(tmp_path, {"registry": new})
    assert path.read_text() == f"REGISTRY_VERSION={old}\n"


def test_the_major_guard_is_a_resolution_error():
    # The refresh hook fails on it as on any other resolution failure.
    assert issubclass(rl.MajorVersionError, rl.ResolutionError)


@pytest.mark.parametrize("text", [
    None, "", "REGISTRY_VERSION=3.1\n", "REGISTRY_VERSION=v3.1.2\n",
    "REGISTRY_VERSION=3.1.2\nREGISTRY_VERSION=3.1.3\n",
])
def test_reading_a_missing_or_malformed_workflow_pin_fails_loud(tmp_path, text):
    if text is None:
        (tmp_path / "pins").mkdir()
    else:
        _workflow_pins(tmp_path, text)
    with pytest.raises(rl.ResolutionError, match="workflow-images.txt"):
        rl.read_workflow_pin(tmp_path, "registry")


def _refresh_tree(root: Path, registry: str) -> Path:
    """A docker/ tree with every fragment ARG at 1.0.0 and the registry at
    `registry`; returns the fragment."""
    (root / "common").mkdir()
    fragment = root / "common" / "tools.dockerfile"
    fragment.write_text("".join(f"ARG {arg}=1.0.0\n" for arg in rl.TOOL_ARGS.values()))
    _workflow_pins(root, f"REGISTRY_VERSION={registry}\n")
    return fragment


def _refresh_fetch(registry_tag: str):
    def tag(tool):
        return f"{rl.TOOL_TAG_PREFIXES.get(tool, 'v')}1.0.1"
    mapping = {rl.TOOL_LATEST_URLS.get(tool, repo): f"https://github.com/{repo}/releases/tag/{tag(tool)}"
               for tool, repo in rl.TOOL_REPOS.items()}
    mapping[REGISTRY_REPO] = f"https://github.com/{REGISTRY_REPO}/releases/tag/{registry_tag}"
    return _fetch(mapping)


def test_refresh_moves_the_registry_within_its_major(tmp_path, capsys):
    fragment = _refresh_tree(tmp_path, "3.1.2")
    assert rl.main(["--write"], docker_root=tmp_path, fetch=_refresh_fetch("v3.1.3")) == 0
    assert (tmp_path / "pins" / "workflow-images.txt").read_text() == "REGISTRY_VERSION=3.1.3\n"
    assert "ARG TRIVY_VERSION=1.0.1\n" in fragment.read_text()
    assert "bumped registry: 3.1.2 -> 3.1.3" in capsys.readouterr().out


def test_refresh_fails_on_a_new_major_before_writing_anything(tmp_path):
    fragment = _refresh_tree(tmp_path, "3.1.2")
    before = fragment.read_text()
    with pytest.raises(rl.MajorVersionError):
        rl.main(["--write"], docker_root=tmp_path, fetch=_refresh_fetch("v4.0.0"))
    assert fragment.read_text() == before
    assert (tmp_path / "pins" / "workflow-images.txt").read_text() == "REGISTRY_VERSION=3.1.2\n"


def test_refresh_dry_run_lists_the_registry(tmp_path, capsys):
    _refresh_tree(tmp_path, "3.1.2")
    assert rl.main([], docker_root=tmp_path, fetch=_refresh_fetch("v3.1.3")) == 0
    assert "registry\t3.1.3\n" in capsys.readouterr().out
