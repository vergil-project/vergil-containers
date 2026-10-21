"""Node.js adapter for the `ts-node` family (policy:
docs/site/docs/languages/ts-node.md).

Window: majors that are LTS on the day of the check and not EOL. The policy
uses the LTS status itself, not the parity of the major, because from Node.js
27 every major becomes LTS. Source: endoflife.date `nodejs`, whose `lts` field
is the LTS start date or `false`.

GA: a major is GA for Vergil on its LTS start date, not its initial release,
so a target's `ga` is that date. An LTS major with no start date is an error.

A major is installable when NodeSource publishes its `setup_<major>.x` script,
which the image's Dockerfile runs.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from functools import partial

from lifecycle.core import Change, SourceError, TargetVersion, UpstreamRelease, ga_not_eol, lts_only
from lifecycle.sources import Fetch, endoflife, fetch_url, url_exists

UrlExists = Callable[[str], bool]

NODESOURCE_SETUP_URL = "https://deb.nodesource.com/setup_{major}.x"
VM_PIN_FOLLOW_UP = (
    "line up the separate Node.js pin in vergil-project/vergil-vm with the new {family} window ({kind} {version})"
)


class NodeAdapter:
    key = "ts-node"
    evidence_url = "https://endoflife.date/nodejs"
    product = "nodejs"

    def __init__(self, fetch: Fetch = fetch_url, setup_exists: UrlExists | None = None) -> None:
        self._fetch = fetch
        self._url_exists = setup_exists or partial(url_exists, fetch=fetch)

    def fetch(self) -> list[UpstreamRelease]:
        return endoflife(self.product, self._fetch)

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        targets: list[TargetVersion] = []
        for r in lts_only(ga_not_eol(releases, today), today):
            if r.lts_since is None:
                raise SourceError(
                    f"endoflife.date {self.product!r} cycle {r.version!r}: LTS with no LTS start date, "
                    "which this family's GA rule needs"
                )
            installable = self._url_exists(NODESOURCE_SETUP_URL.format(major=r.version))
            targets.append(TargetVersion(r.version, r.lts_since, r.eol, installable))
        return targets

    def extra_changes(self, change: Change) -> list[str]:
        if change.kind not in ("add", "drop", "out_of_policy"):
            return []
        return [VM_PIN_FOLLOW_UP.format(family=self.key, kind=change.kind, version=change.version)]
