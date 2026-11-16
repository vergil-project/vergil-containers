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

**Fail loud.** Any resolution failure raises `ResolutionError` — there is no
silent fallback that would let a broken lookup masquerade as "no change".

This module owns the ONLY network call in the pins toolchain, and only when run
as the scheduled bumper. Normal builds and `generate.sh` never invoke it, so
they stay hermetic and offline-capable. Unit tests inject `fetch`/`resolved`
and never touch the network.
"""
from __future__ import annotations

import re
import subprocess
import sys
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


def main(argv: list[str], docker_root: Path | None = None, fetch=_curl_location) -> int:
    if docker_root is None:
        docker_root = Path(__file__).resolve().parent.parent
    resolved = resolve_all(fetch=fetch)
    workflow_resolved = resolve_all(WORKFLOW_PIN_REPOS, fetch=fetch)
    if "--write" not in argv:
        for tool, ver in sorted({**resolved, **workflow_resolved}.items()):
            print(f"{tool}\t{ver}")
        return 0
    # The major-version guard runs before any file is written.
    workflow_changed = plan_workflow_pins(docker_root, workflow_resolved)
    changed = rewrite_args(docker_root, resolved)
    write_workflow_pins(docker_root, workflow_changed)
    changed.update(workflow_changed)
    if not changed:
        print("no version changes")
    for tool, (old, new) in sorted(changed.items()):
        print(f"bumped {tool}: {old} -> {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
