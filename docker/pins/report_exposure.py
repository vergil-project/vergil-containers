"""WS4 exposure report: what is pinned, in what state, and which pins are due
for re-evaluation (leading edge has moved past the inducing_release).

Internal-state observability only. The upstream-latest lookup is intentionally
minimal and best-effort — full upstream-distance drift tracking is the
Dependabot follow-on (epic vergil-project/.github#158), deliberately NOT built
here. A tool whose latest version cannot be resolved is simply absent from
`latest`, which means it is not flagged (unknowns never raise a false alarm)."""
from __future__ import annotations

import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version

import check_pins
import extract_pins
import harvest_installed
import resolve_latest


def source_pins(root: Path) -> dict[str, str]:
    """Version-of-record per tool, read from the templates. For auto-managed
    tools the source pin IS the current version (pins.yml carries only a
    descriptive constraint), so this is what must be compared against upstream.
    Where a tool is pinned per-image (a `case` on the runtime version, e.g.
    go-test-coverage), the NEWEST pin wins — the older one is a deliberate
    per-image hold, not drift."""
    newest: dict[str, str] = {}
    for pin in extract_pins.extract(root):
        try:
            candidate = Version(pin.version)
        except InvalidVersion:
            continue
        current = newest.get(pin.tool)
        if current is None or candidate > Version(current):
            newest[pin.tool] = pin.version
    return newest


def auto_managed_behind(
    pins: dict, pinned: dict[str, str], latest: dict[str, str]
) -> list[tuple[str, str, str]]:
    """Auto-managed tools whose source pin trails the newest upstream release.

    This is a SEPARATE signal from `due_for_reevaluation`, deliberately. That
    list means "a break-hold whose inducing_release is no longer leading edge,
    so the reason for the hold must be reconsidered" — a question that does not
    apply to auto-managed tools, which carry no inducing_release and are
    *supposed* to move. Folding the two together would conflate "this pin's
    justification may have expired" with "this pin is merely behind".

    Behind means the weekly bumper's PR has not been merged (it is never
    auto-merged — #435 keeps a human merge gate), so nothing has carried the new
    version into the images. Unresolvable or unparseable versions are skipped:
    unknowns never raise a false alarm. Returns (tool, pinned, latest)."""
    out = []
    for tool, meta in pins.items():
        if meta.get("state") != "auto-managed":
            continue
        have, newest = pinned.get(tool), latest.get(tool)
        if not have or not newest:
            continue
        try:
            if Version(newest) > Version(have):
                out.append((tool, have, newest))
        except InvalidVersion:
            continue
    return sorted(out)


def due_for_reevaluation(pins: dict, latest: dict[str, str]) -> list[str]:
    """Active pins whose inducing_release is strictly older than the latest
    known upstream release. Pins that are not active, that carry no
    inducing_release, or whose latest is unknown are never flagged."""
    out = []
    for tool, meta in pins.items():
        if meta.get("state") != "active":
            continue
        induced = meta.get("inducing_release")
        newest = latest.get(tool)
        if induced and newest and Version(newest) > Version(induced):
            out.append(tool)
    return sorted(out)


def render(root: Path, latest: dict[str, str], installed: dict[str, dict[str, str]]) -> str:
    """Markdown report: (1) due-for-re-evaluation headline, (2) installed tool
    versions per image (pinned AND floating), (3) the full pin table, with a
    pointer to the pin-lifecycle procedure (spec §4.3)."""
    pins = check_pins.load_pins(root)
    due = due_for_reevaluation(pins, latest)
    pinned = source_pins(root)
    behind = auto_managed_behind(pins, pinned, latest)
    lines = [
        "# Pin exposure report\n",
        "> Re-evaluation procedure: see the pin lifecycle (spec §4.3), published "
        "in the site docs under epic #155's docs-review gate (#414).\n",
        "## Due for re-evaluation\n",
    ]
    lines += [
        f"- **{t}** — inducing release {pins[t]['inducing_release']} is no "
        f"longer leading edge ({latest.get(t)}); re-evaluate per lifecycle."
        for t in due
    ] or ["- none\n"]
    lines.append("\n## Auto-managed tools behind the leading edge\n")
    lines.append(
        "> These float via the weekly `bump-tools` workflow, which opens a PR "
        "but never auto-merges (#435). Anything listed here means a bump PR is "
        "waiting on a human — check for an open `bot/bump-tools-*` PR (#573).\n"
    )
    lines += [
        f"- **{t}** — pinned {have}, upstream {newest}; the bump has not landed."
        for t, have, newest in behind
    ] or ["- none — every auto-managed tool is at its leading edge.\n"]
    auto = sorted(t for t, m in pins.items() if m.get("state") == "auto-managed")
    lines.append("\n## Auto-managed (leading edge, weekly bumper)\n")
    lines.append(
        "> Floated to the newest upstream release by the `bump-tools` workflow "
        "(#435); the pin stays in source for reproducibility.\n"
    )
    lines += [
        f"- {t}: {pins[t]['constraint']}"
        f" [pinned {pinned.get(t, '?')}, upstream {latest.get(t, 'unknown')}]"
        for t in auto
    ] or ["- none\n"]
    lines.append("\n## Installed tool versions per image\n")
    for image in sorted(installed):
        lines.append(f"### {image}")
        for tool, ver in sorted(installed[image].items()):
            state = pins.get(tool, {}).get("state", "floating")
            lines.append(f"- {tool}: {ver} [{state}]")
    lines.append("\n## All pins\n")
    for t, m in sorted(pins.items()):
        lines.append(f"- {t} [{m['state']}] {m['constraint']} — {m['reason']}")
    return "\n".join(lines) + "\n"


# --- CLI-only best-effort upstream-latest + image harvest -------------------
# Everything below runs only under __main__; the unit tests inject `latest` and
# `probe`, so no network or Docker call is ever made during testing.

# Tools whose latest release is a GitHub release we can resolve x.y.z from.
# Absent tools (npm/PyPI/Go-module distribution) are intentionally not resolved
# here — that is the drift-tracker's job, not this internal-state report.
_GITHUB_REPOS = {
    "shellcheck": "koalaman/shellcheck",
    "shfmt": "mvdan/sh",
    "actionlint": "rhysd/actionlint",
    "git-cliff": "orhun/git-cliff",
    "hadolint": "hadolint/hadolint",
    "scorecard": "ossf/scorecard",
    "trivy": "aquasecurity/trivy",
    "uv": "astral-sh/uv",
    "opentofu": "opentofu/opentofu",
    "nfpm": "goreleaser/nfpm",
    "golangci-lint": "golangci/golangci-lint",
    "cargo-deny": "EmbarkStudios/cargo-deny",
    "cargo-llvm-cov": "taiki-e/cargo-llvm-cov",
    "go-test-coverage": "vladopajic/go-test-coverage",
}

# Image matrix (mirrors CLAUDE.md's version matrix); base carries no runtime.
_MATRIX = {
    "base": ["latest"],
    "python": ["3.12", "3.13", "3.14"],
    "java": ["17", "21"],
    "go": ["1.25", "1.26"],
    "ruby": ["3.2", "3.3", "3.4"],
    "rust": ["1.92", "1.93"],
    "cpp-clang": ["20", "19"],
    "cpp-gcc": ["14", "13"],
}


def _latest_from_github(repo: str) -> str | None:
    """Best-effort latest x.y.z from a GitHub repo's latest release.

    Uses the same `/releases/latest` **redirect** as `resolve_latest.py` rather
    than `api.github.com`: #435 rejected the API here because its unauthenticated
    limit is 60/hr and is easily exhausted, while the redirect is unmetered. That
    mattered less while this report was only ever run by hand; it matters now
    that it runs on a schedule (#574).

    Best-effort by design, unlike the bumper: the resolver raises
    ResolutionError, and this report downgrades that to a warning (never a silent
    swallow) and returns None, so an unresolvable tool is reported as unknown
    rather than flagged. The bumper must fail loud because it rewrites pins; a
    read-only observability view must not fail a build over one bad lookup."""
    try:
        return resolve_latest.resolve(repo)
    except resolve_latest.ResolutionError as exc:
        print(f"::warning::could not resolve latest for {repo}: {exc}", file=sys.stderr)
        return None


def _build_latest(tools) -> dict[str, str]:
    latest: dict[str, str] = {}
    for tool in tools:
        repo = _GITHUB_REPOS.get(tool)
        if not repo:
            continue
        newest = _latest_from_github(repo)
        if newest:
            latest[tool] = newest
    return latest


def _image_matrix(prefix: str) -> list[str]:
    images = []
    for lang, versions in _MATRIX.items():
        for version in versions:
            images.append(f"{prefix}-{lang}:{version}")
    return images


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    # --no-probe skips the per-image Docker harvest. The drift signals need only
    # pins.yml + the templates + one upstream lookup per tool, so the report
    # stays useful anywhere without a Docker socket — including inside the
    # prod-base container the CI/ops jobs run in, where probing every tool in
    # every image would otherwise emit hundreds of ::warning:: lines and harvest
    # nothing. Opting out explicitly beats a silent partial result.
    args = [a for a in argv if a != "--no-probe"]
    probe_images = "--no-probe" not in argv
    prefix = args[0] if args else "prod"
    pins = check_pins.load_pins(root)
    latest = _build_latest(sorted(pins))
    installed = (
        harvest_installed.harvest(_image_matrix(prefix), sorted(pins))
        if probe_images
        else {}
    )
    print(render(root, latest=latest, installed=installed))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
