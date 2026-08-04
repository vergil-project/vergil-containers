"""WS4 exposure report: what is pinned, in what state, and which pins are due
for re-evaluation (leading edge has moved past the inducing_release).

Internal-state observability only. The upstream-latest lookup is intentionally
minimal and best-effort — full upstream-distance drift tracking is the
Dependabot follow-on (epic vergil-project/.github#158), deliberately NOT built
here. A tool whose latest version cannot be resolved is simply absent from
`latest`, which means it is not flagged (unknowns never raise a false alarm)."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from packaging.version import InvalidVersion, Version

import check_pins
import harvest_installed


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
    auto = sorted(t for t, m in pins.items() if m.get("state") == "auto-managed")
    lines.append("\n## Auto-managed (leading edge, weekly bumper)\n")
    lines.append(
        "> Floated to the newest upstream release by the `bump-tools` workflow "
        "(#435); the pin stays in source for reproducibility.\n"
    )
    lines += [f"- {t}: {pins[t]['constraint']}" for t in auto] or ["- none\n"]
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
    """Best-effort latest x.y.z from a GitHub repo's latest release tag. On any
    network/parse failure, warn (never swallow silently) and return None so the
    tool is treated as unknown — not flagged."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (https only)
            tag = json.load(resp).get("tag_name", "")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"::warning::could not resolve latest for {repo}: {exc}", file=sys.stderr)
        return None
    match = harvest_installed._VER.search(tag)
    return match.group(1) if match else None


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
    prefix = argv[0] if argv else "prod"
    pins = check_pins.load_pins(root)
    latest = _build_latest(sorted(pins))
    images = _image_matrix(prefix)
    tools = sorted(pins)
    installed = harvest_installed.harvest(images, tools)
    print(render(root, latest=latest, installed=installed))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
