"""Java adapter (policy: docs/site/docs/languages/java.md).

Window: LTS releases that are GA and not EOL; the shared core applies
no-backfill (which keeps out 11 and 8). Source: endoflife.date
`eclipse-temurin`, whose `lts` flag the window depends on. A version is
installable when the official `eclipse-temurin:<v>-jdk` base image tag exists.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from functools import partial

from lifecycle.core import Change, TargetVersion, UpstreamRelease, ga_not_eol, lts_only
from lifecycle.sources import Fetch, docker_hub_tag_exists, endoflife, fetch_url

TagExists = Callable[[str, str], bool]


class JavaAdapter:
    key = "java"
    evidence_url = "https://endoflife.date/eclipse-temurin"
    product = "eclipse-temurin"
    image = "eclipse-temurin"

    def __init__(self, fetch: Fetch = fetch_url, tag_exists: TagExists | None = None) -> None:
        self._fetch = fetch
        self._tag_exists = tag_exists or partial(docker_hub_tag_exists, fetch=fetch)

    def fetch(self) -> list[UpstreamRelease]:
        return endoflife(self.product, self._fetch)

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        return [
            TargetVersion(r.version, r.ga, r.eol, self._tag_exists(self.image, f"{r.version}-jdk"))
            for r in lts_only(ga_not_eol(releases, today), today)
        ]

    def extra_changes(self, change: Change) -> list[str]:
        return []
