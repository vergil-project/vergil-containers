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
    fragment.write_text("".join(f"ARG {arg}=1.0.0\n" for arg in rl.TOOL_ARGS.values())
                        + f"ARG CARGO_NEXTEST_SHA256_AMD64={HEX_A}\nARG CARGO_NEXTEST_SHA256_ARM64={HEX_B}\n")
    _workflow_pins(root, f"REGISTRY_VERSION={registry}\n")
    return fragment


def _refresh_fetch(registry_tag: str):
    def tag(tool):
        return f"{rl.TOOL_TAG_PREFIXES.get(tool, 'v')}1.0.1"
    mapping = {rl.TOOL_LATEST_URLS.get(tool, repo): f"https://github.com/{repo}/releases/tag/{tag(tool)}"
               for tool, repo in rl.TOOL_REPOS.items()}
    mapping[REGISTRY_REPO] = f"https://github.com/{REGISTRY_REPO}/releases/tag/{registry_tag}"
    return _fetch(mapping)


def _refresh_sums():
    """nextest's checksums at the 1.0.1 the refresh tree floats it to."""
    return _text_fetch(_nextest_sums({"AMD64": HEX_A, "ARM64": HEX_B}, version="1.0.1"))


def test_refresh_moves_the_registry_within_its_major(tmp_path, capsys):
    fragment = _refresh_tree(tmp_path, "3.1.2")
    assert rl.main(["--write"], docker_root=tmp_path, fetch_text=_refresh_sums(), fetch=_refresh_fetch("v3.1.3")) == 0
    assert (tmp_path / "pins" / "workflow-images.txt").read_text() == "REGISTRY_VERSION=3.1.3\n"
    assert "ARG TRIVY_VERSION=1.0.1\n" in fragment.read_text()
    assert "bumped registry: 3.1.2 -> 3.1.3" in capsys.readouterr().out


def test_refresh_fails_on_a_new_major_before_writing_anything(tmp_path):
    fragment = _refresh_tree(tmp_path, "3.1.2")
    before = fragment.read_text()
    with pytest.raises(rl.MajorVersionError):
        rl.main(["--write"], docker_root=tmp_path, fetch_text=_refresh_sums(), fetch=_refresh_fetch("v4.0.0"))
    assert fragment.read_text() == before
    assert (tmp_path / "pins" / "workflow-images.txt").read_text() == "REGISTRY_VERSION=3.1.2\n"


def test_refresh_dry_run_lists_the_registry(tmp_path, capsys):
    _refresh_tree(tmp_path, "3.1.2")
    assert rl.main([], docker_root=tmp_path, fetch_text=_refresh_sums(), fetch=_refresh_fetch("v3.1.3")) == 0
    assert "registry\t3.1.3\n" in capsys.readouterr().out

# --- Pinned digests (epic vergil-project/.github#1165, spec §6.3) ---------------

NEXTEST_RELEASES = "https://github.com/nextest-rs/nextest/releases/download/"
NEXTEST_DOWNLOAD = f"{NEXTEST_RELEASES}cargo-nextest-0.9.153/"
NEXTEST_TRIPLES = {"AMD64": "x86_64-unknown-linux-gnu", "ARM64": "aarch64-unknown-linux-gnu"}
HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64


def _nextest_sums(digests, version="0.9.153"):
    """Canned checksum bodies for cargo-nextest `version`, in nextest's own
    `<digest>  <asset>` format, keyed by URL."""
    base = f"{NEXTEST_RELEASES}cargo-nextest-{version}/cargo-nextest-{version}"
    return {
        f"{base}-{triple}.sha256": f"{digests[arch]}  cargo-nextest-{version}-{triple}.tar.gz\n"
        for arch, triple in NEXTEST_TRIPLES.items() if arch in digests
    }


def _text_fetch(bodies):
    def fetch(url):
        if url not in bodies:
            raise rl.ResolutionError(f"curl failed fetching {url}: HTTP 404")
        return bodies[url]
    return fetch


def _nextest_fragment(tmp_path, version="0.9.152", amd64=HEX_A, arm64=HEX_B, extra=""):
    (tmp_path / "common").mkdir(exist_ok=True)
    frag = tmp_path / "common" / "cargo-nextest.dockerfile"
    frag.write_text(
        f"ARG CARGO_NEXTEST_VERSION={version}\n"
        f"ARG CARGO_NEXTEST_SHA256_AMD64={amd64}\n"
        f"ARG CARGO_NEXTEST_SHA256_ARM64={arm64}\n" + extra
    )
    return frag


def test_tool_digests_cover_only_registered_tools():
    assert set(rl.TOOL_DIGESTS) == {"cargo-nextest"}
    assert set(rl.TOOL_DIGESTS) <= set(rl.TOOL_REPOS)
    for source in rl.TOOL_DIGESTS.values():
        assert set(source.checksum_urls) == set(rl.ARCHES) == set(source.assets)


def test_resolve_digests_nextest():
    got = rl.resolve_digests("cargo-nextest", "0.9.153",
                             fetch=_text_fetch(_nextest_sums({"AMD64": HEX_A, "ARM64": HEX_B})))
    assert got == {"AMD64": HEX_A, "ARM64": HEX_B}


def test_resolve_digests_accepts_a_bare_digest_and_binary_mode():
    bodies = {
        f"{NEXTEST_DOWNLOAD}cargo-nextest-0.9.153-x86_64-unknown-linux-gnu.sha256": HEX_A.upper(),
        f"{NEXTEST_DOWNLOAD}cargo-nextest-0.9.153-aarch64-unknown-linux-gnu.sha256":
            f"{HEX_B} *cargo-nextest-0.9.153-aarch64-unknown-linux-gnu.tar.gz\n",
    }
    assert rl.resolve_digests("cargo-nextest", "0.9.153", fetch=_text_fetch(bodies)) == {
        "AMD64": HEX_A, "ARM64": HEX_B}


def test_resolve_digests_missing_arch_raises():
    # The release has no checksum for aarch64: the error names the tool and
    # the architecture.
    fetch = _text_fetch(_nextest_sums({"AMD64": HEX_A}))
    with pytest.raises(rl.ResolutionError, match=r"cargo-nextest 0\.9\.153 ARM64: no checksum"):
        rl.resolve_digests("cargo-nextest", "0.9.153", fetch=fetch)


@pytest.mark.parametrize("body,match", [
    ("", "expected one checksum line, got 0"),
    (f"{HEX_A}  a.tar.gz\n{HEX_B}  b.tar.gz\n", "expected one checksum line, got 2"),
    ("not-a-digest  cargo-nextest-0.9.153-aarch64-unknown-linux-gnu.tar.gz", "is not a SHA-256"),
    (f"{HEX_B}  cargo-nextest-0.9.153-x86_64-unknown-linux-gnu.tar.gz", "the checksum is for"),
    (f"{HEX_B}  cargo-nextest-0.9.153-aarch64-unknown-linux-gnu.tar.gz extra", "expected '<sha256>'"),
])
def test_resolve_digests_malformed_checksum_raises(body, match):
    bodies = _nextest_sums({"AMD64": HEX_A})
    bodies[f"{NEXTEST_DOWNLOAD}cargo-nextest-0.9.153-aarch64-unknown-linux-gnu.sha256"] = body
    with pytest.raises(rl.ResolutionError, match=match) as exc:
        rl.resolve_digests("cargo-nextest", "0.9.153", fetch=_text_fetch(bodies))
    assert "cargo-nextest 0.9.153 ARM64" in str(exc.value)


def test_resolve_digests_unknown_tool_raises():
    with pytest.raises(rl.ResolutionError, match="no digest source"):
        rl.resolve_digests("shellcheck", "0.12.0", fetch=_text_fetch({}))


def test_rewrite_digests_updates_both_arches(tmp_path):
    frag = _nextest_fragment(tmp_path, extra="RUN echo ${CARGO_NEXTEST_SHA256_AMD64}\n")
    assert rl.rewrite_digests(tmp_path, "cargo-nextest", {"AMD64": HEX_C, "ARM64": HEX_A}) is True
    assert frag.read_text() == (
        "ARG CARGO_NEXTEST_VERSION=0.9.152\n"
        f"ARG CARGO_NEXTEST_SHA256_AMD64={HEX_C}\n"
        f"ARG CARGO_NEXTEST_SHA256_ARM64={HEX_A}\n"
        "RUN echo ${CARGO_NEXTEST_SHA256_AMD64}\n"
    )
    assert rl.rewrite_digests(tmp_path, "cargo-nextest", {"AMD64": HEX_C, "ARM64": HEX_A}) is False


def test_rewrite_digests_missing_arg_raises(tmp_path):
    frag = tmp_path / "common" / "cargo-nextest.dockerfile"
    (tmp_path / "common").mkdir()
    frag.write_text(f"ARG CARGO_NEXTEST_VERSION=0.9.152\nARG CARGO_NEXTEST_SHA256_AMD64={HEX_A}\n")
    with pytest.raises(rl.ResolutionError, match="CARGO_NEXTEST_SHA256_ARM64"):
        rl.rewrite_digests(tmp_path, "cargo-nextest", {"AMD64": HEX_C, "ARM64": HEX_C})
    assert frag.read_text() == f"ARG CARGO_NEXTEST_VERSION=0.9.152\nARG CARGO_NEXTEST_SHA256_AMD64={HEX_A}\n"


def test_rewrite_digests_wants_the_version_fragment_and_every_arch(tmp_path):
    (tmp_path / "common").mkdir()
    with pytest.raises(rl.ResolutionError, match="no 'ARG CARGO_NEXTEST_VERSION='"):
        rl.rewrite_digests(tmp_path, "cargo-nextest", {"AMD64": HEX_A, "ARM64": HEX_B})
    _nextest_fragment(tmp_path)
    with pytest.raises(rl.ResolutionError, match="want"):
        rl.rewrite_digests(tmp_path, "cargo-nextest", {"AMD64": HEX_A})
    with pytest.raises(rl.ResolutionError, match="is not a SHA-256"):
        rl.rewrite_digests(tmp_path, "cargo-nextest", {"AMD64": HEX_A, "ARM64": "zz"})


def _main_fixture(tmp_path):
    """A docker root with every TOOL_ARGS tool pinned at 1.0.0 (cargo-nextest
    at 0.9.152 with digests), and a location fetcher that floats only
    cargo-nextest, to 0.9.153."""
    _nextest_fragment(tmp_path)
    other = tmp_path / "common" / "tools.dockerfile"
    other.write_text("".join(f"ARG {arg}=1.0.0\n" for tool, arg in rl.TOOL_ARGS.items()
                             if tool != "cargo-nextest"))
    _workflow_pins(tmp_path, "REGISTRY_VERSION=1.0.0\n")

    def fetch(source):
        if source == rl.TOOL_LATEST_URLS["cargo-nextest"]:
            return NEXTEST_DOWNLOAD + "cargo-nextest-0.9.153-x86_64-unknown-linux-gnu.tar.gz"
        return f"https://github.com/{source}/releases/tag/v1.0.0"

    return other, fetch


def test_write_pins_versions_and_digests_together(tmp_path, capsys):
    other, fetch = _main_fixture(tmp_path)
    before = other.read_text()
    assert rl.main(["--write"], docker_root=tmp_path, fetch=fetch,
                   fetch_text=_text_fetch(_nextest_sums({"AMD64": HEX_C, "ARM64": HEX_A}))) == 0
    assert (tmp_path / "common" / "cargo-nextest.dockerfile").read_text() == (
        "ARG CARGO_NEXTEST_VERSION=0.9.153\n"
        f"ARG CARGO_NEXTEST_SHA256_AMD64={HEX_C}\n"
        f"ARG CARGO_NEXTEST_SHA256_ARM64={HEX_A}\n"
    )
    assert other.read_text() == before
    out = capsys.readouterr()
    assert "bumped cargo-nextest: 0.9.152 -> 0.9.153" in out.out
    assert "pinned cargo-nextest 0.9.153 digests" in out.out
    assert "::warning::" not in out.err


def test_write_warns_on_a_digest_change_without_a_version_change(tmp_path, capsys):
    _, fetch = _main_fixture(tmp_path)
    _nextest_fragment(tmp_path, version="0.9.153")
    assert rl.main(["--write"], docker_root=tmp_path, fetch=fetch,
                   fetch_text=_text_fetch(_nextest_sums({"AMD64": HEX_C, "ARM64": HEX_B}))) == 0
    out = capsys.readouterr()
    assert "bumped" not in out.out
    assert "::warning::cargo-nextest 0.9.153: its release checksums changed" in out.err


def test_write_is_all_or_nothing(tmp_path):
    # The version resolves, then the aarch64 checksum is missing: no fragment
    # changes, not even the resolved version.
    other, fetch = _main_fixture(tmp_path)
    nextest = tmp_path / "common" / "cargo-nextest.dockerfile"
    before = {nextest: nextest.read_text(), other: other.read_text()}
    with pytest.raises(rl.ResolutionError, match="cargo-nextest 0.9.153 ARM64"):
        rl.main(["--write"], docker_root=tmp_path, fetch=fetch,
                fetch_text=_text_fetch(_nextest_sums({"AMD64": HEX_C})))
    assert {f: f.read_text() for f in before} == before


def test_write_restores_every_fragment_when_a_digest_rewrite_fails(tmp_path):
    # Every lookup succeeds and the version is written, then the fragment's
    # aarch64 digest line is missing: the version rewrite is undone.
    other, fetch = _main_fixture(tmp_path)
    nextest = tmp_path / "common" / "cargo-nextest.dockerfile"
    nextest.write_text(f"ARG CARGO_NEXTEST_VERSION=0.9.152\nARG CARGO_NEXTEST_SHA256_AMD64={HEX_A}\n")
    before = {nextest: nextest.read_text(), other: other.read_text()}
    with pytest.raises(rl.ResolutionError, match="CARGO_NEXTEST_SHA256_ARM64"):
        rl.main(["--write"], docker_root=tmp_path, fetch=fetch,
                fetch_text=_text_fetch(_nextest_sums({"AMD64": HEX_C, "ARM64": HEX_A})))
    assert {f: f.read_text() for f in before} == before


def test_main_without_write_prints_digests_and_writes_nothing(tmp_path, capsys):
    other, fetch = _main_fixture(tmp_path)
    nextest = tmp_path / "common" / "cargo-nextest.dockerfile"
    before = nextest.read_text()
    assert rl.main([], docker_root=tmp_path, fetch=fetch,
                   fetch_text=_text_fetch(_nextest_sums({"AMD64": HEX_C, "ARM64": HEX_A}))) == 0
    assert nextest.read_text() == before
    out = capsys.readouterr().out
    assert "cargo-nextest\t0.9.153" in out
    assert f"cargo-nextest\tsha256-amd64\t{HEX_C}" in out
    assert f"cargo-nextest\tsha256-arm64\t{HEX_A}" in out


def test_curl_text_reads_the_body_from_a_file(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        Path(args[args.index("-o") + 1]).write_text(f"{HEX_A}  x.tar.gz\n")

    monkeypatch.setattr(rl.subprocess, "run", run)
    assert rl._curl_text("https://x/y.sha256") == f"{HEX_A}  x.tar.gz\n"
    assert calls[0][:8] == ["curl", "-fsSL", "--retry", "5", "--retry-all-errors", "--retry-delay", "2",
                            "https://x/y.sha256"]


def test_curl_text_raises_on_a_curl_failure(monkeypatch):
    def run(args, **kwargs):
        raise rl.subprocess.CalledProcessError(22, args, stderr="curl: (22) 404\n")

    monkeypatch.setattr(rl.subprocess, "run", run)
    with pytest.raises(rl.ResolutionError, match=r"curl failed fetching https://x/y.sha256: curl: \(22\) 404"):
        rl._curl_text("https://x/y.sha256")


def test_every_digest_tool_is_pinned_in_its_live_fragment():
    # rewrite_digests with each tool's current source digests changes nothing,
    # and raises if a TOOL_DIGESTS tool's fragment lacks a digest line.
    docker = Path(__file__).resolve().parent.parent
    for tool in rl.TOOL_DIGESTS:
        stem = rl.TOOL_ARGS[tool].removesuffix("_VERSION")
        current = {}
        for frag in sorted((docker / "common").glob("*.dockerfile")):
            for arch in rl.ARCHES:
                match = re.search(rf"^ARG {stem}_SHA256_{arch}=(\S+)$", frag.read_text(), re.MULTILINE)
                if match:
                    current[arch] = match.group(1)
        assert set(current) == set(rl.ARCHES), tool
        assert rl.rewrite_digests(docker, tool, current) is False


def test_nextest_fragment_verifies_pinned_digest():
    # The build verifies the tarball against the digest pinned in source and
    # downloads no checksum file.
    text = (Path(__file__).resolve().parent.parent / "common" / "cargo-nextest.dockerfile").read_text()
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert re.search(r"amd64\)[^;]*; NEXTEST_SHA256=\"\$\{CARGO_NEXTEST_SHA256_AMD64\}\"", body)
    assert re.search(r"arm64\)[^;]*; NEXTEST_SHA256=\"\$\{CARGO_NEXTEST_SHA256_ARM64\}\"", body)
    assert 'echo "${NEXTEST_SHA256}  /tmp/${NEXTEST_TARBALL}" | sha256sum -c -' in body
    assert ".sha256" not in body
    assert body.count("curl ") == 1
