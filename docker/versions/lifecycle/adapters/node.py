"""Node.js adapter for the `ts-node` family (policy:
docs/site/docs/languages/ts-node.md).

Window: majors that are LTS on the day of the check and not EOL. The policy
uses the LTS status itself, not the parity of the major, because from Node.js
27 every major becomes LTS. Source: endoflife.date `nodejs`, whose `lts` field
is the LTS start date or `false`.

GA: a major is GA for Vergil on its LTS start date, not its initial release,
so a target's `ga` is that date. An LTS major with no start date is an error.

A major is installable when nodejs.org's release index has a release of it
with `linux-x64` and `linux-arm64` tarballs, the files the image downloads
(epic vergil-project/.github#649, spec §5.4). The index is read with
`node_releases` from docker/pins/resolve_toolchains.py, the fetcher the
upstream refresh pins the same tarballs with, so nodejs.org is fetched and
parsed in one place. It is read once per check, and only when a major is in
the window.
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

from lifecycle.core import Change, SourceError, TargetVersion, UpstreamRelease, ga_not_eol, lts_only
from lifecycle.sources import Fetch, endoflife, fetch_url

sys.path.append(str(Path(__file__).resolve().parents[3] / "pins"))
import resolve_toolchains as rt  # noqa: E402

# Every Node release with both Linux tarballs, newest first ("24.11.1").
Releases = Callable[[], list[str]]

VM_PIN_FOLLOW_UP = (
    "line up the separate Node.js pin in vergil-project/vergil-vm with the new {family} window ({kind} {version})"
)


class NodeAdapter:
    key = "ts-node"
    evidence_url = "https://endoflife.date/nodejs"
    product = "nodejs"

    def __init__(self, fetch: Fetch = fetch_url, releases: Releases | None = None) -> None:
        self._fetch = fetch
        self._releases = releases or self._index_releases

    def _index_releases(self) -> list[str]:
        # A fetch failure is already a SourceError (lifecycle.sources.fetch_url);
        # a malformed index is the resolver's ResolutionError, which the
        # lifecycle run would not record as this family's error.
        try:
            return rt.node_releases(self._fetch)
        except rt.ResolutionError as exc:
            raise SourceError(f"nodejs.org release index: {exc}") from exc

    def fetch(self) -> list[UpstreamRelease]:
        return endoflife(self.product, self._fetch)

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        window = lts_only(ga_not_eol(releases, today), today)
        for r in window:
            if r.lts_since is None:
                raise SourceError(
                    f"endoflife.date {self.product!r} cycle {r.version!r}: LTS with no LTS start date, "
                    "which this family's GA rule needs"
                )
        published = {v.split(".")[0] for v in self._releases()} if window else set()
        return [TargetVersion(r.version, r.lts_since, r.eol, r.version in published) for r in window]

    def extra_changes(self, change: Change) -> list[str]:
        if change.kind not in ("add", "drop", "out_of_policy"):
            return []
        return [VM_PIN_FOLLOW_UP.format(family=self.key, kind=change.kind, version=change.version)]
