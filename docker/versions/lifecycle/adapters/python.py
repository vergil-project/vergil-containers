"""Python adapter (policy: docs/site/docs/languages/python.md).

Window: every minor version that is GA and not EOL (spec §5.1); the shared
core applies no-backfill. Source: endoflife.date `python`. A version is
installable when the official `python:<v>-slim` base image tag exists.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from functools import partial

from lifecycle.core import Change, TargetVersion, UpstreamRelease, ga_not_eol
from lifecycle.sources import Fetch, docker_hub_tag_exists, endoflife, fetch_url

TagExists = Callable[[str, str], bool]


class PythonAdapter:
    key = "python"
    evidence_url = "https://endoflife.date/python"
    product = "python"
    image = "python"

    def __init__(self, fetch: Fetch = fetch_url, tag_exists: TagExists | None = None) -> None:
        self._fetch = fetch
        self._tag_exists = tag_exists or partial(docker_hub_tag_exists, fetch=fetch)

    def fetch(self) -> list[UpstreamRelease]:
        return endoflife(self.product, self._fetch)

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        return [
            TargetVersion(r.version, r.ga, r.eol, self._tag_exists(self.image, f"{r.version}-slim"))
            for r in ga_not_eol(releases, today)
        ]

    def extra_changes(self, change: Change) -> list[str]:
        return []
