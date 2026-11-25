"""Leading-edge resolver for the binary-download mechanism tools (#435).

For each tool, resolve the newest release version from its GitHub repo via the
`/releases/latest` **redirect** — `curl -fsSLI https://github.com/OWNER/REPO/
releases/latest` returns a 3xx whose `location:` header points at
`.../releases/tag/vX.Y.Z`. We parse the tag from that header. A tool whose
repo's latest release may be another project's (cargo-nextest) resolves from
the URL its project documents for its latest binary instead (TOOL_LATEST_URLS),
whose redirect names the release asset, `.../releases/download/<tag>/<asset>`.

Why the redirect and not `api.github.com`: the API's unauthenticated limit is
60 requests/hr and is easily exhausted in CI; the release redirect is unmetered.
The redirect also resolves to the latest *full* release (never a pre-release).

It also moves the workflow image pins (WORKFLOW_PIN_REPOS, in
docker/pins/workflow-images.txt), but never across a major version: a newest
release in another major raises `MajorVersionError` before anything is written
(#914).

**Digests in source.** A prebuilt tool in TOOL_DIGESTS (cargo-nextest,
cargo-deny, hadolint, opentofu, nfpm, trivy, scorecard, uv, yq, actionlint,
shellcheck, shfmt) also has its per-architecture sha256 pinned in its fragment,
`ARG <STEM>_SHA256_AMD64=` and `_ARM64=` (epic vergil-project/.github#1165,
spec §6.3; vergil-containers#945, #974, #994), and the image build verifies
against those, not against a checksum it downloads. A tool whose release
publishes no checksum (shellcheck, shfmt) has its digests computed by the
refresh from the release asset itself, trust on first sight: once pinned, any
later change to that asset fails the build. Each such fragment pins exactly one tool, so
the refresh's path fence ties each digest to its own tool's version. `--write`
resolves them from the release's checksum files at the version it writes and
writes versions and digests together, all or nothing, so a refresh PR shows
every digest change beside its version change. A digest change with no version
change (a published release's files changed) raises `ResolutionError` and
writes nothing: refresh PRs merge themselves (epic vergil-project/.github#1168),
so such a change is never left for a human to spot in the PR.

**Fail loud.** Any resolution failure raises `ResolutionError` — there is no
silent fallback that would let a broken lookup masquerade as "no change".

This module owns the ONLY network call in the pins toolchain, and only when run
as the scheduled bumper. Normal builds and `generate.sh` never invoke it, so
they stay hermetic and offline-capable. Unit tests inject `fetch`/`resolved`
and never touch the network.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# tool → GitHub release repo (OWNER/REPO). The binary-download mechanism tools
# kept as pins by #418/#422; this map is the single source of truth for the
# bumper. Keyed by the pins.yml / catalog tool name.
TOOL_REPOS = {
    "shellcheck": "koalaman/shellcheck",
    "shfmt": "mvdan/sh",
    "actionlint": "rhysd/actionlint",
    "git-cliff": "orhun/git-cliff",
    "hadolint": "hadolint/hadolint",
    "opentofu": "opentofu/opentofu",
    "nfpm": "goreleaser/nfpm",
    "trivy": "aquasecurity/trivy",
    "scorecard": "ossf/scorecard",
    "uv": "astral-sh/uv",
    "cargo-nextest": "nextest-rs/nextest",
    "yq": "mikefarah/yq",
    # The Rust validation tools pinned under epic vergil-project/.github#1165
    # (spec §6.3). cargo-deny tags its releases with a bare `x.y.z`,
    # cargo-llvm-cov with `vX.Y.Z`.
    "cargo-deny": "EmbarkStudios/cargo-deny",
    "cargo-llvm-cov": "taiki-e/cargo-llvm-cov",
}

# tool → the URL whose redirect names its latest release, for a tool whose
# repo's /releases/latest cannot be trusted to. nextest-rs/nextest also
# publishes nextest-runner and other crates' releases, and does not mark the
# cargo-nextest release latest, so the repo's latest release may be another
# crate's (vergil-containers#885). nextest documents get.nexte.st/latest/<platform>
# as the latest cargo-nextest binary
# (https://nexte.st/docs/installation/release-urls/); it redirects to the release
# asset, `.../releases/download/cargo-nextest-X.Y.Z/<asset>`.
TOOL_LATEST_URLS = {
    "cargo-nextest": "https://get.nexte.st/latest/linux",
}

# tool → the prefix its release tags carry before the version
# (`cargo-nextest-0.9.152`). A tool with none tags `vX.Y.Z` or `X.Y.Z`.
TOOL_TAG_PREFIXES = {
    "cargo-nextest": "cargo-nextest-",
}

# tool → the ARG name carrying its pinned version in a docker/common fragment.
# Every one of these ARGs stores a bare `x.y.z` (no `v` prefix); the fragment's
# download URL re-adds the `v` (or, for cargo-nextest, its tag prefix). So
# normalization for all of them is "strip the tag prefix and a leading v" — see
# normalize_version.
TOOL_ARGS = {
    "shellcheck": "SHELLCHECK_VERSION",
    "shfmt": "SHFMT_VERSION",
    "actionlint": "ACTIONLINT_VERSION",
    "git-cliff": "GIT_CLIFF_VERSION",
    "hadolint": "HADOLINT_VERSION",
    "opentofu": "OPENTOFU_VERSION",
    "nfpm": "NFPM_VERSION",
    "trivy": "TRIVY_VERSION",
    "scorecard": "SCORECARD_VERSION",
    "uv": "UV_VERSION",
    "cargo-nextest": "CARGO_NEXTEST_VERSION",
    "yq": "YQ_VERSION",
    "cargo-deny": "CARGO_DENY_VERSION",
    "cargo-llvm-cov": "CARGO_LLVM_COV_VERSION",
}

# Workflow image pins (vergil-containers#914): tools a workflow runs as an image
# that no image ships, so no fragment carries an ARG for them. Each is a
# `<NAME>=x.y.z` line in WORKFLOW_PINS, which docker/pins/workflow_images.py
# turns into the image the workflow runs. The refresh moves each to its newest
# release, but only within its major version: a release that changes the major
# fails the refresh (MajorVersionError), so a major move is always a by-hand
# change in a reviewed PR. tool → GitHub release repo (OWNER/REPO).
WORKFLOW_PIN_REPOS = {
    # The job-local registry service of PR CI's image build (ci-images.yml);
    # the official `registry` image is built from these releases.
    "registry": "distribution/distribution",
}

# tool → the name of its `<NAME>=x.y.z` line in WORKFLOW_PINS.
WORKFLOW_PIN_NAMES = {
    "registry": "REGISTRY_VERSION",
}

# The workflow image pins, relative to docker/.
WORKFLOW_PINS = Path("pins") / "workflow-images.txt"

# The architectures a prebuilt tool's digests are pinned for, as they appear in
# the fragment's `ARG <STEM>_SHA256_<ARCH>=` lines (STEM is the tool's TOOL_ARGS
# name less `_VERSION`), the same naming as the toolchain pins'
# `RUSTUP_INIT_SHA256_AMD64`.
ARCHES = ("AMD64", "ARM64")


# How a release's checksum file is laid out (DigestSource.layout).
#   single  - one file per asset, one line: the digest alone or
#             `<digest>  <asset>` (parse_checksum).
#   list    - one file for the whole release, a `<digest>  <file>` line per
#             file (sha256sum's output); the asset's line is selected by its
#             exact file name (parse_checksum_list).
#   columns - one file for the whole release, a `<file>  <hash>...` line per
#             file with one column per algorithm, in the order a second file
#             (`hashes_order_url`) lists them, one name a line; the SHA-256
#             column is found from that order (parse_checksum_columns).
#   asset   - no checksum file: the release publishes none, so `checksum_urls`
#             names the asset itself, which the refresh downloads and hashes
#             (fetch_asset), trust on first sight (vergil-containers#994).
LAYOUTS = ("single", "list", "columns", "asset")


@dataclass(frozen=True)
class DigestSource:
    """Where a prebuilt tool's release publishes each architecture's sha256.

    `checksum_urls` maps each of ARCHES to the URL template of the release's
    checksum file for that architecture's asset (for the `asset` layout, of the
    asset itself), and `assets` to the asset's file name; both take
    `{version}`, the bare `x.y.z` of the ARG. `layout`
    (one of LAYOUTS) says how the file is laid out; a `columns` source also
    names `hashes_order_url`, the template of its algorithm order file."""

    checksum_urls: dict[str, str]
    assets: dict[str, str]
    layout: str = "single"
    hashes_order_url: str | None = None


_NEXTEST_DOWNLOAD = "https://github.com/nextest-rs/nextest/releases/download/cargo-nextest-{version}/"
_NEXTEST_TRIPLES = {"AMD64": "x86_64-unknown-linux-gnu", "ARM64": "aarch64-unknown-linux-gnu"}
_DENY_DOWNLOAD = "https://github.com/EmbarkStudios/cargo-deny/releases/download/{version}/"
_DENY_TRIPLES = {"AMD64": "x86_64-unknown-linux-musl", "ARM64": "aarch64-unknown-linux-musl"}
_UV_DOWNLOAD = "https://github.com/astral-sh/uv/releases/download/{version}/"
_UV_TRIPLES = {"AMD64": "x86_64-unknown-linux-gnu", "ARM64": "aarch64-unknown-linux-gnu"}
_YQ_DOWNLOAD = "https://github.com/mikefarah/yq/releases/download/v{version}/"


def _release_list(checksum_url: str, assets: dict[str, str]) -> DigestSource:
    """A DigestSource whose release publishes one `list` checksum file,
    `checksum_url`, for every architecture's asset."""
    return DigestSource(checksum_urls={arch: checksum_url for arch in ARCHES}, assets=assets, layout="list")


def _release_assets(download: str, assets: dict[str, str]) -> DigestSource:
    """A DigestSource whose release publishes no checksum: the refresh hashes
    each architecture's asset, `download` + its name, itself."""
    return DigestSource(checksum_urls={arch: download + asset for arch, asset in assets.items()},
                        assets=assets, layout="asset")

# tool → its DigestSource, for every prebuilt tool whose per-architecture
# sha256 is pinned in source beside its version (epic vergil-project/.github
# #1165, spec §6.3). The image build verifies the tarball against the pinned
# digest, never against a checksum downloaded beside it; the refresh writes the
# digests in the same run that floats the version, so a refresh PR shows both
# changes together.
TOOL_DIGESTS = {
    # nextest publishes a `.sha256` per asset, `<digest>  <asset>`.
    "cargo-nextest": DigestSource(
        checksum_urls={arch: f"{_NEXTEST_DOWNLOAD}cargo-nextest-{{version}}-{triple}.sha256"
                       for arch, triple in _NEXTEST_TRIPLES.items()},
        assets={arch: f"cargo-nextest-{{version}}-{triple}.tar.gz"
                for arch, triple in _NEXTEST_TRIPLES.items()},
    ),
    # cargo-deny publishes a `<asset>.sha256` per asset holding the digest
    # alone. cargo-llvm-cov has no entry: it is built from crates.io, whose
    # index carries the crate checksum cargo verifies.
    "cargo-deny": DigestSource(
        checksum_urls={arch: f"{_DENY_DOWNLOAD}cargo-deny-{{version}}-{triple}.tar.gz.sha256"
                       for arch, triple in _DENY_TRIPLES.items()},
        assets={arch: f"cargo-deny-{{version}}-{triple}.tar.gz"
                for arch, triple in _DENY_TRIPLES.items()},
    ),
    # The other auto-managed prebuilt tools (vergil-containers#945), each
    # verified at build against the digests pinned in its own fragment.
    # hadolint publishes one checksums.sha256 for the release,
    # `<digest> *<asset>` per binary.
    "hadolint": _release_list(
        "https://github.com/hadolint/hadolint/releases/download/v{version}/checksums.sha256",
        {"AMD64": "hadolint-linux-x86_64", "ARM64": "hadolint-linux-arm64"}),
    # OpenTofu's tofu_<version>_SHA256SUMS lists every asset of the release.
    "opentofu": _release_list(
        "https://github.com/opentofu/opentofu/releases/download/v{version}/tofu_{version}_SHA256SUMS",
        {"AMD64": "tofu_{version}_linux_amd64.tar.gz", "ARM64": "tofu_{version}_linux_arm64.tar.gz"}),
    # nfpm's checksums.txt also lists a `.sbom.json` beside each tarball; the
    # exact file name selects the tarball's line.
    "nfpm": _release_list(
        "https://github.com/goreleaser/nfpm/releases/download/v{version}/checksums.txt",
        {"AMD64": "nfpm_{version}_Linux_x86_64.tar.gz", "ARM64": "nfpm_{version}_Linux_arm64.tar.gz"}),
    "trivy": _release_list(
        "https://github.com/aquasecurity/trivy/releases/download/v{version}/trivy_{version}_checksums.txt",
        {"AMD64": "trivy_{version}_Linux-64bit.tar.gz", "ARM64": "trivy_{version}_Linux-ARM64.tar.gz"}),
    "scorecard": _release_list(
        "https://github.com/ossf/scorecard/releases/download/v{version}/scorecard_checksums.txt",
        {"AMD64": "scorecard_{version}_linux_amd64.tar.gz", "ARM64": "scorecard_{version}_linux_arm64.tar.gz"}),
    # uv tags its releases with a bare `x.y.z` and publishes a
    # `<asset>.sha256` per tarball, `<digest>  <asset>`.
    "uv": DigestSource(
        checksum_urls={arch: f"{_UV_DOWNLOAD}uv-{triple}.tar.gz.sha256" for arch, triple in _UV_TRIPLES.items()},
        assets={arch: f"uv-{triple}.tar.gz" for arch, triple in _UV_TRIPLES.items()},
    ),
    # yq's `checksums` holds one line per asset with a column per algorithm,
    # in the order `checksums_hashes_order` lists them.
    "yq": DigestSource(
        checksum_urls={arch: f"{_YQ_DOWNLOAD}checksums" for arch in ARCHES},
        assets={"AMD64": "yq_linux_amd64", "ARM64": "yq_linux_arm64"},
        layout="columns",
        hashes_order_url=f"{_YQ_DOWNLOAD}checksums_hashes_order",
    ),
    # actionlint's actionlint_<version>_checksums.txt lists every asset of the
    # release, `<digest>  <asset>` (vergil-containers#974).
    "actionlint": _release_list(
        "https://github.com/rhysd/actionlint/releases/download/v{version}/actionlint_{version}_checksums.txt",
        {"AMD64": "actionlint_{version}_linux_amd64.tar.gz", "ARM64": "actionlint_{version}_linux_arm64.tar.gz"}),
    # shellcheck and shfmt publish no checksums, so the refresh hashes each
    # asset itself (vergil-containers#994).
    "shellcheck": _release_assets(
        "https://github.com/koalaman/shellcheck/releases/download/v{version}/",
        {"AMD64": "shellcheck-v{version}.linux.x86_64.tar.xz", "ARM64": "shellcheck-v{version}.linux.aarch64.tar.xz"}),
    "shfmt": _release_assets(
        "https://github.com/mvdan/sh/releases/download/v{version}/",
        {"AMD64": "shfmt_v{version}_linux_amd64", "ARM64": "shfmt_v{version}_linux_arm64"}),
}

# A release tag page (`.../releases/tag/<tag>`) or a release asset
# (`.../releases/download/<tag>/<asset>`).
_TAG_IN_LOCATION = re.compile(
    r"/releases/(?:tag/(?P<tag>[^/\s]+)|download/(?P<asset_tag>[^/\s]+)/[^/\s]+)\s*$"
)
_SEMVER = re.compile(r"^v?(?P<ver>\d+\.\d+\.\d+)$")


class ResolutionError(RuntimeError):
    """A tool's latest version could not be resolved. Raised loudly so a broken
    lookup fails the bumper rather than silently skipping the tool."""


class MajorVersionError(ResolutionError):
    """A workflow image pin's newest release is another major version. Raised
    so the refresh fails rather than move a major on its own: a major move
    needs a human, in a reviewed PR."""


def _latest_url(source: str) -> str:
    """The URL to resolve for `source`: a full `https://` URL as it is, else
    `OWNER/REPO`'s `/releases/latest`."""
    if source.startswith("https://"):
        return source
    return f"https://github.com/{source}/releases/latest"


def _curl_location(source: str) -> str:
    """Default fetcher: HEAD `source`'s latest URL (see _latest_url) and return
    the first redirect `location` header naming a release, a
    `.../releases/tag/<tag>` or `.../releases/download/<tag>/<asset>` URL.
    Raises ResolutionError on any curl failure or missing header."""
    url = _latest_url(source)
    try:
        proc = subprocess.run(
            ["curl", "-fsSLI", url],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ResolutionError(f"{source}: curl failed resolving {url}: {exc}") from exc
    for line in proc.stdout.splitlines():
        name, sep, value = line.partition(":")
        if sep and name.strip().lower() == "location" and _TAG_IN_LOCATION.search(value):
            return value.strip()
    raise ResolutionError(f"{source}: no release location header in the redirect chain of {url}")


def parse_tag_from_location(location: str) -> str:
    """Pull the release tag (e.g. `v0.12.0`) out of a `.../releases/tag/<tag>`
    or `.../releases/download/<tag>/<asset>` URL. Raises ResolutionError if the
    URL has no parseable tag segment."""
    match = _TAG_IN_LOCATION.search(location)
    if not match:
        raise ResolutionError(f"cannot parse a release tag from location: {location!r}")
    return match.group("tag") or match.group("asset_tag")


def normalize_version(tag: str, prefix: str = "") -> str:
    """Normalize a release tag to the ARG convention (bare `x.y.z`). Every tool
    stores a bare version, so this strips the tool's tag `prefix` (which the tag
    must carry) and an optional leading `v`, and asserts the result is a
    three-component semver. Raises on anything else (fail loud)."""
    if not tag.startswith(prefix):
        raise ResolutionError(f"release tag {tag!r} does not start with {prefix!r}")
    match = _SEMVER.match(tag[len(prefix):])
    if not match:
        raise ResolutionError(f"release tag {tag!r} is not a {prefix}v?x.y.z version")
    return match.group("ver")


def resolve(source: str, fetch=_curl_location, prefix: str = "") -> str:
    """Resolve one source's latest release version as bare `x.y.z`. `source` is
    `OWNER/REPO` or a full URL (see _latest_url); `prefix` is its tag prefix."""
    return normalize_version(parse_tag_from_location(fetch(source)), prefix)


def resolve_tool(tool: str, repo: str, fetch=_curl_location) -> str:
    """Resolve one tool's latest release version as bare `x.y.z`: from its
    TOOL_LATEST_URLS entry if it has one, else `repo`, and with its
    TOOL_TAG_PREFIXES prefix. The bumper and the pin-exposure report
    (report_exposure.py) both resolve through this, so they agree on where each
    tool's latest release comes from."""
    return resolve(TOOL_LATEST_URLS.get(tool, repo), fetch=fetch,
                   prefix=TOOL_TAG_PREFIXES.get(tool, ""))


def resolve_all(tools: dict[str, str] | None = None, fetch=_curl_location) -> dict[str, str]:
    """Resolve every tool in `tools` (default: TOOL_REPOS) → {tool: x.y.z}
    through resolve_tool. Propagates ResolutionError from the first tool that
    fails."""
    tools = TOOL_REPOS if tools is None else tools
    return {tool: resolve_tool(tool, repo, fetch=fetch) for tool, repo in tools.items()}


def _fragment_files(docker_root: Path) -> list[Path]:
    return sorted((docker_root / "common").glob("*.dockerfile"))


def rewrite_args(docker_root: Path, resolved: dict[str, str]) -> dict[str, tuple[str, str]]:
    """Rewrite `ARG <TOOL>_VERSION=` lines in the fragments to the resolved
    versions. Returns {tool: (old, new)} for tools that actually changed.
    Raises ResolutionError if a tool's ARG cannot be located — that guards
    against TOOL_ARGS drifting away from the fragments."""
    changed: dict[str, tuple[str, str]] = {}
    files = _fragment_files(docker_root)
    for tool, new in resolved.items():
        arg = TOOL_ARGS[tool]
        pattern = re.compile(rf"^(ARG\s+{re.escape(arg)}=)(\d+\.\d+\.\d+)\b", re.MULTILINE)
        for frag in files:
            text = frag.read_text()
            match = pattern.search(text)
            if not match:
                continue
            old = match.group(2)
            if old != new:
                frag.write_text(pattern.sub(rf"\g<1>{new}", text))
                changed[tool] = (old, new)
            break
        else:
            raise ResolutionError(f"no 'ARG {arg}=' found in any fragment for {tool}")
    return changed


def _workflow_pin_line(tool: str) -> re.Pattern[str]:
    name = WORKFLOW_PIN_NAMES[tool]
    return re.compile(rf"^({re.escape(name)}=)(\d+\.\d+\.\d+)[ \t]*$", re.MULTILINE)


def read_workflow_pin(docker_root: Path, tool: str) -> str:
    """The bare `x.y.z` that WORKFLOW_PINS pins `tool` at. Raises
    ResolutionError when the file cannot be read or does not hold exactly one
    well-formed line for the tool."""
    path = docker_root / WORKFLOW_PINS
    try:
        text = path.read_text()
    except OSError as exc:
        raise ResolutionError(f"cannot read the workflow image pins {path}: {exc}") from exc
    found = _workflow_pin_line(tool).findall(text)
    if len(found) != 1:
        raise ResolutionError(
            f"{path}: expected exactly one '{WORKFLOW_PIN_NAMES[tool]}=x.y.z' line "
            f"for {tool}, found {len(found)}"
        )
    return found[0][1]


def check_same_major(tool: str, old: str, new: str) -> None:
    """Refuse, with MajorVersionError, a move of `tool` from `old` to `new`
    that changes the major version."""
    if old.split(".")[0] != new.split(".")[0]:
        raise MajorVersionError(
            f"{tool}: its newest release, {new}, is not in the major version of the "
            f"pinned {old}. The upstream refresh never moves a major version: move it "
            f"by hand in a reviewed PR, after checking the new major's changes against "
            f"how the workflows use it (docker/{WORKFLOW_PINS}; vergil-containers#914)."
        )


def plan_workflow_pins(docker_root: Path, resolved: dict[str, str]) -> dict[str, tuple[str, str]]:
    """{tool: (old, new)} for each workflow image pin in `resolved` whose
    version differs from WORKFLOW_PINS. Raises MajorVersionError for any that
    would change the major version; it writes nothing."""
    changed: dict[str, tuple[str, str]] = {}
    for tool, new in resolved.items():
        old = read_workflow_pin(docker_root, tool)
        check_same_major(tool, old, new)
        if old != new:
            changed[tool] = (old, new)
    return changed


def write_workflow_pins(docker_root: Path, changed: dict[str, tuple[str, str]]) -> None:
    """Rewrite WORKFLOW_PINS to the new versions of `changed`, a
    plan_workflow_pins result."""
    if not changed:
        return
    path = docker_root / WORKFLOW_PINS
    text = path.read_text()
    for tool, (_old, new) in changed.items():
        text = _workflow_pin_line(tool).sub(rf"\g<1>{new}", text)
    path.write_text(text)


_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _curl_text(url: str) -> str:
    """Default checksum fetcher: GET `url` with curl (retrying transient
    errors, failing on an HTTP error) into a file, and return it as text.
    Raises ResolutionError on any curl failure or a body that is not UTF-8."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "body"
        try:
            subprocess.run(
                ["curl", "-fsSL", "--retry", "5", "--retry-all-errors", "--retry-delay", "2",
                 url, "-o", str(out)],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise ResolutionError(f"curl failed fetching {url}: {exc.stderr.strip() or exc}") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise ResolutionError(f"curl failed fetching {url}: {exc}") from exc
        try:
            return out.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ResolutionError(f"{url}: unreadable checksum body: {exc}") from exc


def _curl_hashes(url: str) -> dict[str, str]:
    """Default asset fetcher: GET `url` with curl (retrying transient errors,
    failing on an HTTP error) into a file, and return its digests,
    {"sha256": <hex>, "sha512": <hex>}. Raises ResolutionError on any curl
    failure, an unreadable file or an empty body."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "asset"
        try:
            subprocess.run(
                ["curl", "-fsSL", "--retry", "5", "--retry-all-errors", "--retry-delay", "2",
                 url, "-o", str(out)],
                capture_output=True,
                text=True,
                timeout=600,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise ResolutionError(f"curl failed fetching {url}: {exc.stderr.strip() or exc}") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise ResolutionError(f"curl failed fetching {url}: {exc}") from exc
        sha256, sha512 = hashlib.sha256(), hashlib.sha512()
        try:
            with out.open("rb") as body:
                for chunk in iter(lambda: body.read(1 << 20), b""):
                    sha256.update(chunk)
                    sha512.update(chunk)
            size = out.stat().st_size
        except OSError as exc:
            raise ResolutionError(f"{url}: unreadable asset: {exc}") from exc
        if size == 0:
            raise ResolutionError(f"{url}: the asset is empty")
        return {"sha256": sha256.hexdigest(), "sha512": sha512.hexdigest()}


def parse_checksum(where: str, text: str, asset: str) -> str:
    """The sha256 in a release checksum file: one line, holding the digest
    alone or `<digest>  <file>` (a leading `*` on the file, binary mode, is
    allowed). A file it names must be `asset`. Raises ResolutionError, naming
    `where`, on anything else."""
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ResolutionError(f"{where}: expected one checksum line, got {len(lines)}")
    parts = lines[0].split()
    if len(parts) > 2:
        raise ResolutionError(f"{where}: expected '<sha256>' or '<sha256>  <file>', got {lines[0]!r}")
    digest = parts[0].lower()
    if not _SHA256_HEX.match(digest):
        raise ResolutionError(f"{where}: {parts[0]!r} is not a SHA-256 hex digest")
    if len(parts) == 2 and parts[1].lstrip("*") != asset:
        raise ResolutionError(f"{where}: the checksum is for {parts[1]!r}, not {asset!r}")
    return digest


def _hex_digest(where: str, value: str) -> str:
    digest = value.lower()
    if not _SHA256_HEX.match(digest):
        raise ResolutionError(f"{where}: {value!r} is not a SHA-256 hex digest")
    return digest


def parse_checksum_list(where: str, text: str, asset: str) -> str:
    """The sha256 of `asset` in a release-wide checksum file: one
    `<digest>  <file>` line per file (a leading `*` on the file, binary mode,
    is allowed). Exactly one line must name `asset` exactly, so the line of
    another file whose name contains it (nfpm's `.sbom.json`) is never taken.
    Raises ResolutionError, naming `where`, on anything else."""
    found = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 2:
            raise ResolutionError(f"{where}: expected '<sha256>  <file>' lines, got {line!r}")
        if parts[1].lstrip("*") == asset:
            found.append(parts[0])
    if len(found) != 1:
        raise ResolutionError(f"{where}: expected one checksum line for {asset!r}, got {len(found)}")
    return _hex_digest(where, found[0])


def parse_checksum_columns(where: str, text: str, order: str, asset: str) -> str:
    """The sha256 of `asset` in a release-wide multi-hash checksum file, one
    `<file>  <hash>...` line per file, its columns in the order `order` lists
    the algorithms, one a line. Exactly one algorithm must be `SHA-256`,
    exactly one line must name `asset`, and that line must hold one hash per
    algorithm. Raises ResolutionError, naming `where`, on anything else, so a
    reordered file never yields another algorithm's hash."""
    names = [line.strip() for line in order.splitlines() if line.strip()]
    if names.count("SHA-256") != 1:
        raise ResolutionError(f"{where}: expected one SHA-256 in the hash order, got {names.count('SHA-256')}")
    column = names.index("SHA-256") + 1
    rows = [parts for parts in (line.split() for line in text.splitlines()) if parts and parts[0] == asset]
    if len(rows) != 1:
        raise ResolutionError(f"{where}: expected one checksum line for {asset!r}, got {len(rows)}")
    if len(rows[0]) != len(names) + 1:
        raise ResolutionError(
            f"{where}: the line for {asset!r} has {len(rows[0]) - 1} hashes, the order lists {len(names)}")
    return _hex_digest(where, rows[0][column])


def resolve_digests(tool: str, version: str, fetch=_curl_text, fetch_asset=_curl_hashes) -> dict[str, str]:
    """Resolve `tool`'s per-architecture sha256 at `version` from its release's
    checksum files (TOOL_DIGESTS) → {"AMD64": <hex>, "ARM64": <hex>}. `fetch`
    takes a URL and returns its body as text; `fetch_asset`, used for the
    `asset` layout only, takes an asset's URL and returns its digests
    (_curl_hashes). A missing or malformed checksum, or an asset that cannot
    be fetched, raises ResolutionError naming the tool and the architecture."""
    source = TOOL_DIGESTS.get(tool)
    if source is None:
        raise ResolutionError(f"{tool}: no digest source in TOOL_DIGESTS")
    if source.layout not in LAYOUTS:
        raise ResolutionError(f"{tool}: unknown checksum layout {source.layout!r}, want one of {list(LAYOUTS)}")
    order_template = source.hashes_order_url
    if (source.layout == "columns") != (order_template is not None):
        raise ResolutionError(f"{tool}: a hash order file goes with the columns layout, and only with it")
    bodies: dict[str, str] = {}

    def body(where: str, url: str) -> str:
        # A release-wide file serves both architectures: fetch it once.
        if url not in bodies:
            try:
                bodies[url] = fetch(url)
            except ResolutionError as exc:
                raise ResolutionError(f"{where}: no checksum: {exc}") from exc
        return bodies[url]

    digests: dict[str, str] = {}
    for arch in ARCHES:
        where = f"{tool} {version} {arch}"
        if arch not in source.checksum_urls or arch not in source.assets:
            raise ResolutionError(f"{where}: TOOL_DIGESTS names no checksum for this architecture")
        url = source.checksum_urls[arch].format(version=version)
        asset = source.assets[arch].format(version=version)
        if source.layout == "asset":
            try:
                hashes = fetch_asset(url)
            except ResolutionError as exc:
                raise ResolutionError(f"{where}: no asset: {exc}") from exc
            digests[arch] = _hex_digest(f"{where} ({url})", hashes.get("sha256", ""))
            continue
        text = body(where, url)
        if source.layout == "single":
            digests[arch] = parse_checksum(f"{where} ({url})", text, asset)
        elif source.layout == "list" or order_template is None:
            digests[arch] = parse_checksum_list(f"{where} ({url})", text, asset)
        else:
            order_url = order_template.format(version=version)
            digests[arch] = parse_checksum_columns(f"{where} ({url})", text, body(where, order_url), asset)
    return digests


def rewrite_digests(docker_root: Path, tool: str, digests: dict[str, str]) -> bool:
    """Rewrite the `ARG <STEM>_SHA256_<ARCH>=` lines (STEM is the tool's
    TOOL_ARGS name less `_VERSION`) in the fragment that pins its version.
    Returns whether the fragment changed. Raises ResolutionError if no fragment
    pins the version, a line is missing, or `digests` does not hold a sha256
    for exactly ARCHES."""
    if set(digests) != set(ARCHES):
        raise ResolutionError(f"{tool}: digests for {sorted(digests)}, want {list(ARCHES)}")
    for arch, digest in digests.items():
        if not _SHA256_HEX.match(digest):
            raise ResolutionError(f"{tool} {arch}: {digest!r} is not a SHA-256 hex digest")
    arg = TOOL_ARGS[tool]
    stem = arg.removesuffix("_VERSION")
    version_line = re.compile(rf"^ARG\s+{re.escape(arg)}=", re.MULTILINE)
    frag = next((f for f in _fragment_files(docker_root) if version_line.search(f.read_text())), None)
    if frag is None:
        raise ResolutionError(f"no 'ARG {arg}=' found in any fragment for {tool}")
    text = frag.read_text()
    new = text
    for arch in ARCHES:
        line = re.compile(rf"^(ARG\s+{re.escape(stem)}_SHA256_{arch}=)[0-9a-f]{{64}}$", re.MULTILINE)
        if not line.search(new):
            raise ResolutionError(f"no 'ARG {stem}_SHA256_{arch}=<sha256>' in {frag.name} for {tool}")
        new = line.sub(rf"\g<1>{digests[arch]}", new)
    if new == text:
        return False
    frag.write_text(new)
    return True


def write(docker_root: Path, resolved: dict[str, str],
          digests: dict[str, dict[str, str]]) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Write the resolved versions (rewrite_args) and digests (rewrite_digests)
    together, all or nothing: if any rewrite fails, every fragment is restored
    to what it held before and the error propagates. A tool whose digests
    change while its version does not raises ResolutionError the same way: a
    published release's files never change, and a refresh PR merges itself,
    so a human looks into the release before the pins move. Returns the
    version changes and the tools whose digests changed."""
    before = {frag: frag.read_text() for frag in _fragment_files(docker_root)}
    try:
        changed = rewrite_args(docker_root, resolved)
        redigested = sorted(tool for tool, d in digests.items() if rewrite_digests(docker_root, tool, d))
        unversioned = [tool for tool in redigested if tool not in changed]
        if unversioned:
            raise ResolutionError(
                "; ".join(f"{tool} {resolved[tool]}" for tool in unversioned)
                + ": upstream now lists different release checksums for a version that is already pinned."
                " A published release's files should never change: check the upstream release before"
                " moving these digests by hand")
    except BaseException:
        for frag, text in before.items():
            frag.write_text(text)
        raise
    return changed, redigested


def main(argv: list[str], docker_root: Path | None = None,
         fetch=_curl_location, fetch_text=_curl_text, fetch_asset=_curl_hashes) -> int:
    """Resolve every tool's latest version, and every TOOL_DIGESTS tool's
    digests at that version, before writing anything; print them, or with
    `--write` write them (see write). Any failed lookup raises ResolutionError
    and nothing is written."""
    docker_root = Path(__file__).resolve().parent.parent if docker_root is None else docker_root
    resolved = resolve_all(fetch=fetch)
    workflow_resolved = resolve_all(WORKFLOW_PIN_REPOS, fetch=fetch)
    digests = {tool: resolve_digests(tool, resolved[tool], fetch=fetch_text, fetch_asset=fetch_asset)
               for tool in TOOL_DIGESTS}
    if "--write" not in argv:
        for tool, ver in sorted({**resolved, **workflow_resolved}.items()):
            print(f"{tool}\t{ver}")
        for tool, by_arch in sorted(digests.items()):
            for arch, digest in by_arch.items():
                print(f"{tool}\tsha256-{arch.lower()}\t{digest}")
        return 0
    # The major-version guard runs before any file is written.
    workflow_changed = plan_workflow_pins(docker_root, workflow_resolved)
    changed, redigested = write(docker_root, resolved, digests)
    write_workflow_pins(docker_root, workflow_changed)
    changed.update(workflow_changed)
    if not changed and not redigested:
        print("no version changes")
    for tool, (old, new) in sorted(changed.items()):
        print(f"bumped {tool}: {old} -> {new}")
    for tool in redigested:
        print(f"pinned {tool} {resolved[tool]} digests")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
