"""Go adapter (policy: docs/site/docs/languages/go.md).

Window: the two newest GA releases (spec §5.1). Source: endoflife.date `go`.
A version is installable when go.dev's release list has a stable `go<v>.x`
release with a Linux archive for both architectures: the image installs that
download (epic vergil-project/.github#649, spec §5.4). The list is read with
the go.dev fetcher of `docker/pins/resolve_toolchains.py`, the one the
toolchain pin refresh uses, so go.dev is fetched and parsed in one place.

Quirk: with GOTOOLCHAIN=local some tool pins depend on the Go version, so
dropping a version also means retiring its `case go<v>*)` branch in the Go
Dockerfile template and any `pins.yml` constraint that names it. Those are
returned by `extra_changes` as manual follow-ups for the PR body.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import yaml

from lifecycle.core import Change, SourceError, TargetVersion, UpstreamRelease, ga_only, newest_n
from lifecycle.sources import Fetch, endoflife, fetch_url

_PINS_DIR = str(Path(__file__).resolve().parents[3] / "pins")
if _PINS_DIR not in sys.path:
    sys.path.append(_PINS_DIR)
import resolve_toolchains as rt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE = Path("docker/go/Dockerfile.template")
PINS = Path("docker/pins/pins.yml")


class GoAdapter:
    key = "go"
    evidence_url = "https://endoflife.date/go"
    product = "go"
    window = 2

    def __init__(self, fetch: Fetch = fetch_url, root: Path = REPO_ROOT) -> None:
        self._fetch = fetch
        self._root = root

    def fetch(self) -> list[UpstreamRelease]:
        return endoflife(self.product, self._fetch)

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        published = self.published_series()
        return [
            TargetVersion(r.version, r.ga, r.eol, r.version in published)
            for r in newest_n(ga_only(releases, today), self.window)
        ]

    def published_series(self) -> set[str]:
        """The series ("1.27") with a stable go.dev release that has a Linux
        archive for every architecture. An unreadable or malformed listing
        raises SourceError: it never reads as "not installable"."""
        try:
            releases = rt.go_releases(self._fetch)
        except rt.ResolutionError as exc:
            raise SourceError(f"go.dev: {exc}") from exc
        return {version.rsplit(".", 1)[0] for version in releases}

    def extra_changes(self, change: Change) -> list[str]:
        """Follow-ups for a dropped version: its `case` branch and `pins.yml` holds."""
        if change.kind not in ("drop", "out_of_policy"):
            return []
        v = change.version
        follow_ups: list[str] = []

        try:
            lines = (self._root / TEMPLATE).read_text().splitlines()
        except OSError as exc:
            raise SourceError(f"go adapter: cannot read {TEMPLATE}: {exc}") from exc
        case_re = re.compile(rf"\bgo{re.escape(v)}\*\)")
        for n, line in enumerate(lines, start=1):
            if case_re.search(line):
                follow_ups.append(f"remove the `case go{v}*)` branch from `{TEMPLATE}` (line {n})")

        try:
            data = yaml.safe_load((self._root / PINS).read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise SourceError(f"go adapter: cannot read {PINS}: {exc}") from exc
        pins = data.get("pins") if isinstance(data, dict) else None
        if not isinstance(pins, dict):
            raise SourceError(f"go adapter: {PINS} has no `pins` mapping")
        # "Go 1.26" but not "Go 1.260" or "Go 1.26.1".
        names_re = re.compile(rf"\bGo {re.escape(v)}(?![\d.]*\d)")
        for name, entry in pins.items():
            constraint = entry.get("constraint") if isinstance(entry, dict) else None
            if isinstance(constraint, str) and names_re.search(constraint):
                follow_ups.append(f"retire or update the `{name}` pin in `{PINS}` (constraint: {constraint})")
        return follow_ups
