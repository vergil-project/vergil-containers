"""Leading-edge resolver for the 9 binary-download mechanism tools (#435).

For each tool, resolve the newest release version from its GitHub repo via the
`/releases/latest` **redirect** — `curl -fsSLI https://github.com/OWNER/REPO/
releases/latest` returns a 3xx whose `location:` header points at
`.../releases/tag/vX.Y.Z`. We parse the tag from that header.

Why the redirect and not `api.github.com`: the API's unauthenticated limit is
60 requests/hr and is easily exhausted in CI; the release redirect is unmetered.
The redirect also resolves to the latest *full* release (never a pre-release).

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

# tool → GitHub release repo (OWNER/REPO). The 9 binary-download mechanism tools
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
}

# tool → the ARG name carrying its pinned version in a docker/common fragment.
# Every one of these ARGs stores a bare `x.y.z` (no `v` prefix); the fragment's
# download URL re-adds the `v`. So normalization for all 9 is "strip a leading
# v" — see normalize_version.
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
}

_TAG_IN_LOCATION = re.compile(r"/releases/tag/(?P<tag>[^/\s]+)\s*$")
_SEMVER = re.compile(r"^v?(?P<ver>\d+\.\d+\.\d+)$")


class ResolutionError(RuntimeError):
    """A tool's latest version could not be resolved. Raised loudly so a broken
    lookup fails the bumper rather than silently skipping the tool."""


def _curl_location(repo: str) -> str:
    """Default fetcher: HEAD `github.com/OWNER/REPO/releases/latest` and return
    the redirect's `location` header (the `.../releases/tag/vX.Y.Z` URL). Raises
    ResolutionError on any curl failure or missing header."""
    url = f"https://github.com/{repo}/releases/latest"
    try:
        proc = subprocess.run(
            ["curl", "-fsSLI", url],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ResolutionError(f"{repo}: curl failed resolving /releases/latest: {exc}") from exc
    for line in proc.stdout.splitlines():
        name, sep, value = line.partition(":")
        if sep and name.strip().lower() == "location" and "/releases/tag/" in value:
            return value.strip()
    raise ResolutionError(f"{repo}: no '/releases/tag/' location header in redirect chain")


def parse_tag_from_location(location: str) -> str:
    """Pull the release tag (e.g. `v0.12.0`) out of a `.../releases/tag/<tag>`
    URL. Raises ResolutionError if the URL has no parseable tag segment."""
    match = _TAG_IN_LOCATION.search(location)
    if not match:
        raise ResolutionError(f"cannot parse a release tag from location: {location!r}")
    return match.group("tag")


def normalize_version(tag: str) -> str:
    """Normalize a release tag to the ARG convention (bare `x.y.z`). All 9 tools
    store a bare version, so this strips an optional leading `v` and asserts the
    result is a three-component semver. Raises on anything else (fail loud)."""
    match = _SEMVER.match(tag)
    if not match:
        raise ResolutionError(f"release tag {tag!r} is not a v?x.y.z version")
    return match.group("ver")


def resolve(repo: str, fetch=_curl_location) -> str:
    """Resolve one repo's latest release version as bare `x.y.z`."""
    return normalize_version(parse_tag_from_location(fetch(repo)))


def resolve_all(tools: dict[str, str] | None = None, fetch=_curl_location) -> dict[str, str]:
    """Resolve every tool in `tools` (default: TOOL_REPOS) → {tool: x.y.z}.
    Propagates ResolutionError from the first tool that fails."""
    tools = TOOL_REPOS if tools is None else tools
    return {tool: resolve(repo, fetch=fetch) for tool, repo in tools.items()}


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


def main(argv: list[str]) -> int:
    docker_root = Path(__file__).resolve().parent.parent
    resolved = resolve_all()
    if "--write" not in argv:
        for tool, ver in sorted(resolved.items()):
            print(f"{tool}\t{ver}")
        return 0
    changed = rewrite_args(docker_root, resolved)
    if not changed:
        print("no version changes")
    for tool, (old, new) in sorted(changed.items()):
        print(f"bumped {tool}: {old} -> {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
