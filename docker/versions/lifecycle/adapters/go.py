"""Go adapter (policy: docs/site/docs/languages/go.md).

Window: the two newest GA releases (spec §5.1). Source: endoflife.date `go`.
A version is installable when the official `golang:<v>` base image tag exists.

Quirk: with GOTOOLCHAIN=local some tool pins depend on the Go version, so
dropping a version also means retiring its `case go<v>*)` branch in the Go
Dockerfile template and any `pins.yml` constraint that names it. Those are
returned by `extra_changes` as manual follow-ups for the PR body.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from functools import partial
from pathlib import Path

import yaml

from lifecycle.core import Change, SourceError, TargetVersion, UpstreamRelease, ga_only, newest_n
from lifecycle.sources import Fetch, docker_hub_tag_exists, endoflife, fetch_url

TagExists = Callable[[str, str], bool]

REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE = Path("docker/go/Dockerfile.template")
PINS = Path("docker/pins/pins.yml")


class GoAdapter:
    key = "go"
    product = "go"
    image = "golang"
    window = 2

    def __init__(
        self,
        fetch: Fetch = fetch_url,
        tag_exists: TagExists | None = None,
        root: Path = REPO_ROOT,
    ) -> None:
        self._fetch = fetch
        self._tag_exists = tag_exists or partial(docker_hub_tag_exists, fetch=fetch)
        self._root = root

    def fetch(self) -> list[UpstreamRelease]:
        return endoflife(self.product, self._fetch)

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        return [
            TargetVersion(r.version, r.ga, r.eol, self._tag_exists(self.image, r.version))
            for r in newest_n(ga_only(releases, today), self.window)
        ]

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
