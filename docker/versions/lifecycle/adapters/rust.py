"""Rust adapter (policy: docs/site/docs/languages/rust.md).

Window: the newest stable release and the one before it (newest and
newest-1), by release order. Source: endoflife.date `rust`. A version is
installable when the official `rust:<v>-slim` base image tag exists.

Quirk: upstream EOL comes with the next release, not on a fixed date, so the
newest-1 release is always already "EOL" upstream. The policy deliberately
keeps it for one cycle, so the window is computed from release order and the
targets carry no EOL date (an upstream date would make the core drop newest-1
the moment it is added).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from functools import partial

from lifecycle.core import Change, TargetVersion, UpstreamRelease, ga_only, newest_n
from lifecycle.sources import Fetch, docker_hub_tag_exists, endoflife, fetch_url

TagExists = Callable[[str, str], bool]


class RustAdapter:
    key = "rust"
    evidence_url = "https://endoflife.date/rust"
    product = "rust"
    image = "rust"
    window = 2

    def __init__(self, fetch: Fetch = fetch_url, tag_exists: TagExists | None = None) -> None:
        self._fetch = fetch
        self._tag_exists = tag_exists or partial(docker_hub_tag_exists, fetch=fetch)

    def fetch(self) -> list[UpstreamRelease]:
        return endoflife(self.product, self._fetch)

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        return [
            TargetVersion(r.version, r.ga, None, self._tag_exists(self.image, f"{r.version}-slim"))
            for r in newest_n(ga_only(releases, today), self.window)
        ]

    def extra_changes(self, change: Change) -> list[str]:
        return []
