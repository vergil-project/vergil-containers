"""Hermetic unit tests for the leading-edge resolver. The redirect fetch is
INJECTED — no network (and no curl) is ever exercised here."""
import re
from pathlib import Path

import pytest

import resolve_latest as rl

TOOLS = {
    "shellcheck", "shfmt", "actionlint", "git-cliff", "hadolint",
    "opentofu", "nfpm", "trivy", "scorecard", "uv", "cargo-nextest", "yq",
    "cargo-deny", "cargo-llvm-cov",
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
                        + _digest_args(rl.TOOL_DIGESTS, {"AMD64": HEX_A, "ARM64": HEX_B}))
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
    """Every digest tool's checksums at the 1.0.1 the refresh tree floats it
    to, as main's fetch_text and fetch_asset keywords."""
    bodies = _all_sums({"AMD64": HEX_A, "ARM64": HEX_B}, version="1.0.1")
    return {"fetch_text": _text_fetch(bodies), "fetch_asset": _asset_fetch(bodies)}


def test_refresh_moves_the_registry_within_its_major(tmp_path, capsys):
    fragment = _refresh_tree(tmp_path, "3.1.2")
    assert rl.main(["--write"], docker_root=tmp_path, **_refresh_sums(), fetch=_refresh_fetch("v3.1.3")) == 0
    assert (tmp_path / "pins" / "workflow-images.txt").read_text() == "REGISTRY_VERSION=3.1.3\n"
    assert "ARG TRIVY_VERSION=1.0.1\n" in fragment.read_text()
    assert "bumped registry: 3.1.2 -> 3.1.3" in capsys.readouterr().out


def test_refresh_fails_on_a_new_major_before_writing_anything(tmp_path):
    fragment = _refresh_tree(tmp_path, "3.1.2")
    before = fragment.read_text()
    with pytest.raises(rl.MajorVersionError):
        rl.main(["--write"], docker_root=tmp_path, **_refresh_sums(), fetch=_refresh_fetch("v4.0.0"))
    assert fragment.read_text() == before
    assert (tmp_path / "pins" / "workflow-images.txt").read_text() == "REGISTRY_VERSION=3.1.2\n"


def test_refresh_dry_run_lists_the_registry(tmp_path, capsys):
    _refresh_tree(tmp_path, "3.1.2")
    assert rl.main([], docker_root=tmp_path, **_refresh_sums(), fetch=_refresh_fetch("v3.1.3")) == 0
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
        if url not in bodies or not isinstance(bodies[url], str):
            raise rl.ResolutionError(f"curl failed fetching {url}: HTTP 404")
        return bodies[url]
    return fetch


def _asset_fetch(bodies):
    """An asset fetch (rl._curl_hashes's shape) serving the digests in
    `bodies` that are an `asset` tool's (a dict, not a checksum file's text)."""
    def fetch(url):
        if url not in bodies or not isinstance(bodies[url], dict):
            raise rl.ResolutionError(f"curl failed fetching {url}: HTTP 404")
        return bodies[url]
    return fetch


# A yq-style algorithm order: SHA-256 is neither first nor last.
YQ_ORDER = ["CRC32", "MD5", "SHA-1", "SHA-256", "SHA-512"]


def _sums(tool, version, digests):
    """Canned checksum bodies for any TOOL_DIGESTS `tool` at `version`, in its
    DigestSource's layout, keyed by the URL it names: `<digest>  <asset>` per
    file for `single` and `list` (a release-wide `list` file also lists a decoy
    asset), and for `columns` an `<asset>  <hash>...` line per asset with the
    YQ_ORDER file beside it."""
    source = rl.TOOL_DIGESTS[tool]
    bodies: dict[str, str] = {}
    for arch, digest in digests.items():
        url = source.checksum_urls[arch].format(version=version)
        asset = source.assets[arch].format(version=version)
        if source.layout == "columns":
            hashes = ["0" * 8 if name != "SHA-256" else digest for name in YQ_ORDER]
            bodies[url] = bodies.get(url, "") + "  ".join([asset, *hashes]) + "\n"
            bodies[source.hashes_order_url.format(version=version)] = "\n".join(YQ_ORDER) + "\n"
        elif source.layout == "list":
            bodies[url] = bodies.get(url, f"{HEX_C}  decoy-{asset}.sbom.json\n") + f"{digest}  {asset}\n"
        elif source.layout == "asset":
            bodies[url] = {"sha256": digest, "sha512": "0" * 128}
        else:
            bodies[url] = f"{digest}  {asset}\n"
    return bodies


def _all_sums(digests, version):
    """Every TOOL_DIGESTS tool's checksum bodies at one `version`."""
    return {url: body for tool in rl.TOOL_DIGESTS for url, body in _sums(tool, version, digests).items()}


def _digest_args(tools, digests):
    """The `ARG <STEM>_SHA256_<ARCH>=` lines of each of `tools`."""
    return "".join(f"ARG {rl.TOOL_ARGS[tool].removesuffix('_VERSION')}_SHA256_{arch}={digests[arch]}\n"
                   for tool in sorted(tools) for arch in rl.ARCHES)


def _main_sums(nextest_digests):
    """The checksum fetches for _main_fixture, as main's fetch_text and
    fetch_asset keywords: cargo-nextest's at 0.9.153 as given, and every other
    digest tool's at the 1.0.0 it stays at, unchanged."""
    others = {url: body for tool in set(rl.TOOL_DIGESTS) - {"cargo-nextest"}
              for url, body in _sums(tool, "1.0.0", {"AMD64": HEX_A, "ARM64": HEX_B}).items()}
    bodies = {**_nextest_sums(nextest_digests), **others}
    return {"fetch_text": _text_fetch(bodies), "fetch_asset": _asset_fetch(bodies)}


def _nextest_fragment(tmp_path, version="0.9.152", amd64=HEX_A, arm64=HEX_B, extra=""):
    (tmp_path / "common").mkdir(exist_ok=True)
    frag = tmp_path / "common" / "cargo-nextest.dockerfile"
    frag.write_text(
        f"ARG CARGO_NEXTEST_VERSION={version}\n"
        f"ARG CARGO_NEXTEST_SHA256_AMD64={amd64}\n"
        f"ARG CARGO_NEXTEST_SHA256_ARM64={arm64}\n" + extra
    )
    return frag


# The prebuilt tools whose digests are pinned in source (epic
# vergil-project/.github#1165, vergil-containers#945).
DIGEST_TOOLS = {"cargo-nextest", "cargo-deny", "hadolint", "opentofu", "nfpm", "trivy", "scorecard", "uv", "yq",
                "actionlint", "shellcheck", "shfmt"}


def test_tool_digests_cover_only_registered_tools():
    assert set(rl.TOOL_DIGESTS) == DIGEST_TOOLS
    assert set(rl.TOOL_DIGESTS) <= set(rl.TOOL_REPOS)
    for source in rl.TOOL_DIGESTS.values():
        assert set(source.checksum_urls) == set(rl.ARCHES) == set(source.assets)
        assert source.layout in rl.LAYOUTS
        assert (source.layout == "columns") == (source.hashes_order_url is not None)


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
        rl.resolve_digests("cargo-llvm-cov", "0.9.2", fetch=_text_fetch({}))


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
                             if tool != "cargo-nextest")
                     + _digest_args(set(rl.TOOL_DIGESTS) - {"cargo-nextest"}, {"AMD64": HEX_A, "ARM64": HEX_B}))
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
                   **_main_sums({"AMD64": HEX_C, "ARM64": HEX_A})) == 0
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


def test_write_refuses_a_digest_change_without_a_version_change(tmp_path, capsys):
    # The release's checksums changed under the pinned version: the refresh
    # fails, naming the tool and version, and no fragment changes.
    other, fetch = _main_fixture(tmp_path)
    _nextest_fragment(tmp_path, version="0.9.153")
    nextest = tmp_path / "common" / "cargo-nextest.dockerfile"
    before = {nextest: nextest.read_text(), other: other.read_text()}
    with pytest.raises(rl.ResolutionError,
                       match="cargo-nextest 0.9.153: upstream now lists different release checksums"):
        rl.main(["--write"], docker_root=tmp_path, fetch=fetch,
                **_main_sums({"AMD64": HEX_C, "ARM64": HEX_B}))
    assert {f: f.read_text() for f in before} == before
    assert "pinned" not in capsys.readouterr().out


def test_write_is_all_or_nothing(tmp_path):
    # The version resolves, then the aarch64 checksum is missing: no fragment
    # changes, not even the resolved version.
    other, fetch = _main_fixture(tmp_path)
    nextest = tmp_path / "common" / "cargo-nextest.dockerfile"
    before = {nextest: nextest.read_text(), other: other.read_text()}
    with pytest.raises(rl.ResolutionError, match="cargo-nextest 0.9.153 ARM64"):
        rl.main(["--write"], docker_root=tmp_path, fetch=fetch,
                **_main_sums({"AMD64": HEX_C}))
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
                **_main_sums({"AMD64": HEX_C, "ARM64": HEX_A}))
    assert {f: f.read_text() for f in before} == before


def test_main_without_write_prints_digests_and_writes_nothing(tmp_path, capsys):
    other, fetch = _main_fixture(tmp_path)
    nextest = tmp_path / "common" / "cargo-nextest.dockerfile"
    before = nextest.read_text()
    assert rl.main([], docker_root=tmp_path, fetch=fetch,
                   **_main_sums({"AMD64": HEX_C, "ARM64": HEX_A})) == 0
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


def _version_fragment(tool):
    """The live fragment that pins `tool`'s version."""
    docker = Path(__file__).resolve().parent.parent
    arg = rl.TOOL_ARGS[tool]
    found = [f for f in sorted((docker / "common").glob("*.dockerfile"))
             if re.search(rf"^ARG {arg}=", f.read_text(), re.MULTILINE)]
    assert len(found) == 1, (tool, found)
    return found[0]


def test_each_digest_fragment_pins_one_tool():
    # The refresh's path fence (vergil.toml) treats a fragment as one block:
    # a digest may change only when a version in the same fragment does. A
    # fragment that pins digests therefore pins exactly one tool, so each
    # digest is tied to its own tool's version.
    docker = Path(__file__).resolve().parent.parent
    for frag in sorted((docker / "common").glob("*.dockerfile")):
        text = frag.read_text()
        if not re.search(r"^ARG [A-Z0-9_]+_SHA256_(AMD64|ARM64)=", text, re.MULTILINE):
            continue
        versions = re.findall(r"^ARG ([A-Z0-9_]+)_VERSION=", text, re.MULTILINE)
        assert len(versions) == 1, (frag.name, versions)
        stems = set(re.findall(r"^ARG ([A-Z0-9_]+)_SHA256_(?:AMD64|ARM64)=", text, re.MULTILINE))
        assert stems == set(versions), (frag.name, stems)


@pytest.mark.parametrize("tool", sorted(DIGEST_TOOLS))
def test_each_digest_fragment_verifies_only_its_pinned_digests(tool):
    # The build checks the download against a digest pinned in source, chosen
    # by TARGETARCH, and downloads no checksum file: the only curl is the asset.
    frag = _version_fragment(tool)
    stem = rl.TOOL_ARGS[tool].removesuffix("_VERSION")
    body = "\n".join(line for line in frag.read_text().splitlines() if not line.lstrip().startswith("#"))
    for arch in rl.ARCHES:
        assert re.search(rf"{arch.lower()}\)(?: [A-Z0-9_]+=[^;\s]+;)? [A-Z0-9_]+=\"\$\{{{stem}_SHA256_{arch}\}}\" ;;",
                         body), (tool, arch)
    assert re.search(r'echo "\$\{[A-Z_]+_SHA256\}  /tmp/[^"]+" \| sha256sum -c -', body), tool
    assert body.count("curl ") == 1, tool
    for word in ("checksums", "SHA256SUMS", ".sha256 ", "sha256sum -c \"", "grep "):
        assert word not in body, (tool, word)


def test_resolve_digests_real_layouts():
    # Each layout parsed from bodies shaped like the upstream releases'.
    bodies = {
        "https://github.com/hadolint/hadolint/releases/download/v2.15.1/checksums.sha256":
            f"{HEX_A} *hadolint-linux-arm64\n{HEX_B} *hadolint-linux-x86_64\n{HEX_C} *hadolint-macos-arm64\n",
        "https://github.com/goreleaser/nfpm/releases/download/v2.49.0/checksums.txt":
            f"{HEX_C}  nfpm_2.49.0_Linux_arm64.tar.gz.sbom.json\n{HEX_A}  nfpm_2.49.0_Linux_arm64.tar.gz\n"
            f"{HEX_B}  nfpm_2.49.0_Linux_x86_64.tar.gz\n{HEX_C}  nfpm_2.49.0_Linux_x86_64.tar.gz.sbom.json\n",
        "https://github.com/mikefarah/yq/releases/download/v4.54.3/checksums":
            "yq_linux_arm64  df1b  " + HEX_A + "  9f\nyq_linux_amd64  20e4  " + HEX_B + "  4a\n"
            "yq_linux_amd64.tar.gz  0000  " + HEX_C + "  00\n",
        "https://github.com/mikefarah/yq/releases/download/v4.54.3/checksums_hashes_order": "CRC32\nSHA-256\nMD5\n",
        "https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_checksums.txt":
            f"{HEX_C}  actionlint_1.7.12_linux_386.tar.gz\n{HEX_B}  actionlint_1.7.12_linux_amd64.tar.gz\n"
            f"{HEX_A}  actionlint_1.7.12_linux_arm64.tar.gz\n{HEX_C}  actionlint_1.7.12_linux_armv6.tar.gz\n",
    }
    fetch = _text_fetch(bodies)
    assert rl.resolve_digests("actionlint", "1.7.12", fetch=fetch) == {"AMD64": HEX_B, "ARM64": HEX_A}
    assert rl.resolve_digests("hadolint", "2.15.1", fetch=fetch) == {"AMD64": HEX_B, "ARM64": HEX_A}
    assert rl.resolve_digests("nfpm", "2.49.0", fetch=fetch) == {"AMD64": HEX_B, "ARM64": HEX_A}
    assert rl.resolve_digests("yq", "4.54.3", fetch=fetch) == {"AMD64": HEX_B, "ARM64": HEX_A}


@pytest.mark.parametrize("tool", sorted(DIGEST_TOOLS))
def test_resolve_digests_every_tool(tool):
    bodies = _sums(tool, "1.2.3", {"AMD64": HEX_A, "ARM64": HEX_B})
    assert rl.resolve_digests(tool, "1.2.3", fetch=_text_fetch(bodies), fetch_asset=_asset_fetch(bodies)) == {
        "AMD64": HEX_A, "ARM64": HEX_B}


def test_resolve_digests_fetches_a_release_wide_file_once():
    calls = []
    bodies = _sums("trivy", "0.76.2", {"AMD64": HEX_A, "ARM64": HEX_B})

    def fetch(url):
        calls.append(url)
        return bodies[url]

    assert rl.resolve_digests("trivy", "0.76.2", fetch=fetch) == {"AMD64": HEX_A, "ARM64": HEX_B}
    assert calls == ["https://github.com/aquasecurity/trivy/releases/download/v0.76.2/trivy_0.76.2_checksums.txt"]


@pytest.mark.parametrize("body,match", [
    ("", "expected one checksum line for 'trivy_0.76.2_Linux-ARM64.tar.gz', got 0"),
    (f"{HEX_A}  trivy_0.76.2_Linux-ARM64.tar.gz.sbom.json\n", "got 0"),
    (f"{HEX_A}  trivy_0.76.2_Linux-ARM64.tar.gz\n{HEX_B}  trivy_0.76.2_Linux-ARM64.tar.gz\n", "got 2"),
    (f"{HEX_A}  trivy_0.76.2_Linux-ARM64.tar.gz extra\n", "expected '<sha256>  <file>' lines"),
    ("zz  trivy_0.76.2_Linux-ARM64.tar.gz\n", "is not a SHA-256"),
])
def test_resolve_digests_malformed_list_raises(body, match):
    url = "https://github.com/aquasecurity/trivy/releases/download/v0.76.2/trivy_0.76.2_checksums.txt"
    with pytest.raises(rl.ResolutionError, match=re.escape(match)) as exc:
        rl.resolve_digests("trivy", "0.76.2",
                           fetch=_text_fetch({url: f"{HEX_B}  trivy_0.76.2_Linux-64bit.tar.gz\n" + body}))
    # A malformed line fails the file for every architecture, so the first
    # one read (AMD64) may be the one named.
    assert re.match(r"trivy 0\.76\.2 (AMD64|ARM64) ", str(exc.value))


YQ_URL = "https://github.com/mikefarah/yq/releases/download/v4.54.3/"


@pytest.mark.parametrize("sums,order,match", [
    (f"yq_linux_amd64  1  {HEX_A}\nyq_linux_arm64  1  {HEX_B}\n", "CRC32\nSHA-512\n", "expected one SHA-256 in the hash order, got 0"),
    (f"yq_linux_amd64  1  {HEX_A}\nyq_linux_arm64  1  {HEX_B}\n", "SHA-256\nSHA-256\n", "got 2"),
    (f"yq_linux_arm64  1  {HEX_B}\n", "CRC32\nSHA-256\n", "expected one checksum line for 'yq_linux_amd64', got 0"),
    (f"yq_linux_amd64  1  {HEX_A}\nyq_linux_amd64  1  {HEX_A}\n", "CRC32\nSHA-256\n", "got 2"),
    (f"yq_linux_amd64  {HEX_A}\n", "CRC32\nSHA-256\n", "has 1 hashes, the order lists 2"),
    ("yq_linux_amd64  1  2\n", "CRC32\nSHA-256\n", "is not a SHA-256"),
])
def test_resolve_digests_malformed_columns_raises(sums, order, match):
    fetch = _text_fetch({f"{YQ_URL}checksums": sums, f"{YQ_URL}checksums_hashes_order": order})
    with pytest.raises(rl.ResolutionError, match=re.escape(match)) as exc:
        rl.resolve_digests("yq", "4.54.3", fetch=fetch)
    assert "yq 4.54.3 AMD64" in str(exc.value)


def test_resolve_digests_columns_follows_a_reordered_release():
    # The same file with the SHA-256 column moved yields the SHA-256 still.
    sums = f"yq_linux_amd64  {HEX_C}  {HEX_A}\nyq_linux_arm64  {HEX_C}  {HEX_B}\n"
    fetch = _text_fetch({f"{YQ_URL}checksums": sums, f"{YQ_URL}checksums_hashes_order": "SHA-512\nSHA-256\n"})
    assert rl.resolve_digests("yq", "4.54.3", fetch=fetch) == {"AMD64": HEX_A, "ARM64": HEX_B}
    fetch = _text_fetch({f"{YQ_URL}checksums": sums, f"{YQ_URL}checksums_hashes_order": "SHA-256\nSHA-512\n"})
    assert rl.resolve_digests("yq", "4.54.3", fetch=fetch) == {"AMD64": HEX_C, "ARM64": HEX_C}


def test_resolve_digests_columns_without_its_order_file_raises():
    fetch = _text_fetch({f"{YQ_URL}checksums": f"yq_linux_amd64  {HEX_A}\n"})
    with pytest.raises(rl.ResolutionError, match="yq 4.54.3 AMD64: no checksum"):
        rl.resolve_digests("yq", "4.54.3", fetch=fetch)


def test_resolve_digests_refuses_an_inconsistent_source(monkeypatch):
    base = rl.TOOL_DIGESTS["uv"]
    for bad, match in [
        (rl.DigestSource(base.checksum_urls, base.assets, layout="tsv"), "unknown checksum layout"),
        (rl.DigestSource(base.checksum_urls, base.assets, layout="columns"), "hash order file"),
        (rl.DigestSource(base.checksum_urls, base.assets, hashes_order_url="x"), "hash order file"),
    ]:
        monkeypatch.setitem(rl.TOOL_DIGESTS, "uv", bad)
        with pytest.raises(rl.ResolutionError, match=match):
            rl.resolve_digests("uv", "0.13.9", fetch=_text_fetch({}))


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


# --- cargo-deny and cargo-llvm-cov (epic vergil-project/.github#1165, spec §6.3)

DENY_DOWNLOAD = "https://github.com/EmbarkStudios/cargo-deny/releases/download/0.21.1/"


def test_cargo_deny_registered_with_digests():
    assert rl.TOOL_REPOS["cargo-deny"] == "EmbarkStudios/cargo-deny"
    assert rl.TOOL_ARGS["cargo-deny"] == "CARGO_DENY_VERSION"
    assert "cargo-deny" not in rl.TOOL_TAG_PREFIXES
    # cargo-deny publishes `<asset>.sha256` for each musl tarball, holding the
    # digest alone with no trailing newline.
    bodies = {
        f"{DENY_DOWNLOAD}cargo-deny-0.21.1-x86_64-unknown-linux-musl.tar.gz.sha256": HEX_A,
        f"{DENY_DOWNLOAD}cargo-deny-0.21.1-aarch64-unknown-linux-musl.tar.gz.sha256": HEX_B,
    }
    assert rl.resolve_digests("cargo-deny", "0.21.1", fetch=_text_fetch(bodies)) == {
        "AMD64": HEX_A, "ARM64": HEX_B}
    del bodies[f"{DENY_DOWNLOAD}cargo-deny-0.21.1-aarch64-unknown-linux-musl.tar.gz.sha256"]
    with pytest.raises(rl.ResolutionError, match=r"cargo-deny 0\.21\.1 ARM64: no checksum"):
        rl.resolve_digests("cargo-deny", "0.21.1", fetch=_text_fetch(bodies))


def test_cargo_deny_resolves_from_its_bare_release_tag():
    fetch = _fetch({"EmbarkStudios/cargo-deny":
                    "https://github.com/EmbarkStudios/cargo-deny/releases/tag/0.21.1"})
    assert rl.resolve_tool("cargo-deny", rl.TOOL_REPOS["cargo-deny"], fetch=fetch) == "0.21.1"


def test_cargo_llvm_cov_registered():
    # Built from crates.io (no checksummed, versioned release asset), so it
    # has a version ARG for the refresh and no digests.
    assert rl.TOOL_REPOS["cargo-llvm-cov"] == "taiki-e/cargo-llvm-cov"
    assert rl.TOOL_ARGS["cargo-llvm-cov"] == "CARGO_LLVM_COV_VERSION"
    assert "cargo-llvm-cov" not in rl.TOOL_DIGESTS
    assert "cargo-llvm-cov" not in rl.TOOL_LATEST_URLS
    fetch = _fetch({"taiki-e/cargo-llvm-cov":
                    "https://github.com/taiki-e/cargo-llvm-cov/releases/tag/v0.9.2"})
    assert rl.resolve_tool("cargo-llvm-cov", rl.TOOL_REPOS["cargo-llvm-cov"], fetch=fetch) == "0.9.2"


def _live_common_copy(tmp_path):
    docker = Path(__file__).resolve().parent.parent
    (tmp_path / "common").mkdir()
    for frag in (docker / "common").glob("*.dockerfile"):
        (tmp_path / "common" / frag.name).write_text(frag.read_text())
    return tmp_path / "common"


def test_rewrite_args_finds_new_fragments(tmp_path):
    common = _live_common_copy(tmp_path)
    deny_before = (common / "cargo-deny.dockerfile").read_text()
    cov_before = (common / "cargo-llvm-cov.dockerfile").read_text()
    old_deny = re.search(r"^ARG CARGO_DENY_VERSION=(\S+)$", deny_before, re.MULTILINE).group(1)
    old_cov = re.search(r"^ARG CARGO_LLVM_COV_VERSION=(\S+)$", cov_before, re.MULTILINE).group(1)
    changed = rl.rewrite_args(tmp_path, {"cargo-deny": "9.9.9", "cargo-llvm-cov": "9.9.8"})
    assert changed == {"cargo-deny": (old_deny, "9.9.9"), "cargo-llvm-cov": (old_cov, "9.9.8")}
    assert (common / "cargo-deny.dockerfile").read_text() == deny_before.replace(
        f"ARG CARGO_DENY_VERSION={old_deny}\n", "ARG CARGO_DENY_VERSION=9.9.9\n")
    assert (common / "cargo-llvm-cov.dockerfile").read_text() == cov_before.replace(
        f"ARG CARGO_LLVM_COV_VERSION={old_cov}\n", "ARG CARGO_LLVM_COV_VERSION=9.9.8\n")
    # The refresh writes cargo-deny's digests into the same fragment.
    assert rl.rewrite_digests(tmp_path, "cargo-deny", {"AMD64": HEX_C, "ARM64": HEX_A}) is True
    text = (common / "cargo-deny.dockerfile").read_text()
    assert f"ARG CARGO_DENY_SHA256_AMD64={HEX_C}\n" in text
    assert f"ARG CARGO_DENY_SHA256_ARM64={HEX_A}\n" in text


def _code(fragment):
    text = (Path(__file__).resolve().parent.parent / "common" / fragment).read_text()
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_deny_fragment_verifies_pinned_digest():
    # The build verifies the musl tarball against the digest pinned in source
    # and downloads no checksum file.
    body = _code("cargo-deny.dockerfile")
    assert re.search(r"amd64\) DENY_TRIPLE=x86_64-unknown-linux-musl; "
                     r"DENY_SHA256=\"\$\{CARGO_DENY_SHA256_AMD64\}\"", body)
    assert re.search(r"arm64\) DENY_TRIPLE=aarch64-unknown-linux-musl; "
                     r"DENY_SHA256=\"\$\{CARGO_DENY_SHA256_ARM64\}\"", body)
    assert 'echo "${DENY_SHA256}  /tmp/${DENY_TARBALL}" | sha256sum -c -' in body
    assert "releases/download/${CARGO_DENY_VERSION}/${DENY_TARBALL}" in body
    assert ".sha256" not in body
    assert body.count("curl ") == 1
    assert "cargo install" not in body
    assert "cargo deny --version" in body


def test_llvm_cov_fragment_installs_locked_at_the_pinned_version():
    body = _code("cargo-llvm-cov.dockerfile")
    assert 'cargo install --locked "cargo-llvm-cov@${CARGO_LLVM_COV_VERSION}"' in body
    assert body.count("cargo install") == 1
    assert 'rm -rf "${CARGO_HOME:?}/registry"' in body
    assert "cargo llvm-cov --version" in body


# --- Tools whose release publishes no checksum (vergil-containers#994) --------

SC_DOWNLOAD = "https://github.com/koalaman/shellcheck/releases/download/v0.11.0/"
SHFMT_DOWNLOAD = "https://github.com/mvdan/sh/releases/download/v3.14.1/"


def test_asset_tools_hash_the_release_asset_itself():
    # No checksum file is fetched: each architecture's asset is fetched and
    # its own SHA-256 pinned.
    seen = []
    bodies = {
        f"{SC_DOWNLOAD}shellcheck-v0.11.0.linux.x86_64.tar.xz": {"sha256": HEX_A, "sha512": "0" * 128},
        f"{SC_DOWNLOAD}shellcheck-v0.11.0.linux.aarch64.tar.xz": {"sha256": HEX_B, "sha512": "0" * 128},
        f"{SHFMT_DOWNLOAD}shfmt_v3.14.1_linux_amd64": {"sha256": HEX_C, "sha512": "0" * 128},
        f"{SHFMT_DOWNLOAD}shfmt_v3.14.1_linux_arm64": {"sha256": HEX_A, "sha512": "0" * 128},
    }

    def fetch_asset(url):
        seen.append(url)
        return _asset_fetch(bodies)(url)

    no_text = _text_fetch({})
    assert rl.resolve_digests("shellcheck", "0.11.0", fetch=no_text, fetch_asset=fetch_asset) == {
        "AMD64": HEX_A, "ARM64": HEX_B}
    assert rl.resolve_digests("shfmt", "3.14.1", fetch=no_text, fetch_asset=fetch_asset) == {
        "AMD64": HEX_C, "ARM64": HEX_A}
    assert seen == list(bodies)


def test_asset_tool_without_its_asset_raises():
    bodies = {f"{SC_DOWNLOAD}shellcheck-v0.11.0.linux.x86_64.tar.xz": {"sha256": HEX_A}}
    with pytest.raises(rl.ResolutionError, match=r"shellcheck 0\.11\.0 ARM64: no asset"):
        rl.resolve_digests("shellcheck", "0.11.0", fetch=_text_fetch({}), fetch_asset=_asset_fetch(bodies))


@pytest.mark.parametrize("hashes", [{}, {"sha256": "zz"}, {"sha512": HEX_A + HEX_A}])
def test_asset_tool_with_a_bad_digest_raises(hashes):
    bodies = {f"{SHFMT_DOWNLOAD}shfmt_v3.14.1_linux_{arch}": hashes for arch in ("amd64", "arm64")}
    with pytest.raises(rl.ResolutionError, match=r"shfmt 3\.14\.1 AMD64 .*is not a SHA-256"):
        rl.resolve_digests("shfmt", "3.14.1", fetch=_text_fetch({}), fetch_asset=_asset_fetch(bodies))


def test_curl_hashes_hashes_the_downloaded_file(monkeypatch):
    import hashlib
    payload = b"\x7fELF" + bytes(range(256)) * 9000
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        Path(args[args.index("-o") + 1]).write_bytes(payload)

    monkeypatch.setattr(rl.subprocess, "run", run)
    assert rl._curl_hashes("https://x/shfmt") == {
        "sha256": hashlib.sha256(payload).hexdigest(), "sha512": hashlib.sha512(payload).hexdigest()}
    assert calls[0][:8] == ["curl", "-fsSL", "--retry", "5", "--retry-all-errors", "--retry-delay", "2",
                            "https://x/shfmt"]


def test_curl_hashes_raises_on_a_curl_failure(monkeypatch):
    def run(args, **kwargs):
        raise rl.subprocess.CalledProcessError(22, args, stderr="curl: (22) 404\n")

    monkeypatch.setattr(rl.subprocess, "run", run)
    with pytest.raises(rl.ResolutionError, match=r"curl failed fetching https://x/shfmt: curl: \(22\) 404"):
        rl._curl_hashes("https://x/shfmt")


def test_curl_hashes_refuses_an_empty_asset(monkeypatch):
    def run(args, **kwargs):
        Path(args[args.index("-o") + 1]).write_bytes(b"")

    monkeypatch.setattr(rl.subprocess, "run", run)
    with pytest.raises(rl.ResolutionError, match="the asset is empty"):
        rl._curl_hashes("https://x/shfmt")
