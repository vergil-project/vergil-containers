"""Rust adapter (policy: docs/site/docs/languages/rust.md).

Window: the newest stable release and the one before it (newest and
newest-1), by release order. Sources: Rust's own release channel for which
series are released, and endoflife.date `rust` for their dates.

New series come from the stable channel (`channel-rust-stable.toml`), not
from endoflife.date, which lags Rust's releases by days (on 2026-11-15 the
stable channel carried 1.100 while endoflife.date's newest cycle was still
1.99). A series the stable channel has released that endoflife.date does not
list yet is added with the publication date of its `.0` release's channel
manifest as its GA date. endoflife.date stays the cross-check: a cycle it
lists as released no later than the current stable release, but newer than
it, is a contradiction and raises SourceError. A newer cycle it dates after
the current stable release has not shipped, and is left out.

A version is installable when the Rust release channel has a manifest for the
series (`channel-rust-<v>.toml`) naming a release of it: the image installs
that series' pinned release with rustup (epic vergil-project/.github#649,
spec §5.4). Every channel manifest is read with the toolchain pins' own
fetchers (`resolve_toolchains.rust_release`, `rust_stable_release` and
`rust_release_date`), so the upstream is parsed in one place.

Quirk: upstream EOL comes with the next release, not on a fixed date, so the
newest-1 release is always already "EOL" upstream. The policy deliberately
keeps it for one cycle, so the window is computed from release order and the
targets carry no EOL date (an upstream date would make the core drop newest-1
the moment it is added).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from lifecycle.core import Change, NotFoundError, SourceError, TargetVersion, UpstreamRelease, ga_only, newest_n
from lifecycle.sources import Fetch, endoflife, fetch_url
from manifest import version_sort_key

sys.path.append(str(Path(__file__).resolve().parents[3] / "pins"))
import resolve_toolchains as rt  # noqa: E402


def channel_has_series(series: str, fetch: Fetch) -> bool:
    """Whether the Rust release channel has a release of `series`.

    A 404 for the series' channel manifest is "no". Any other failure (an
    unreachable host, a manifest that does not parse or names no release of
    the series) raises SourceError: a broken upstream never reads as "not
    installable"."""
    try:
        rt.rust_release(series, fetch)
    except NotFoundError:
        return False
    except rt.ResolutionError as exc:
        raise SourceError(f"Rust channel {series}: {exc}") from exc
    return True


def _release_date(version: str, fetch: Fetch) -> date:
    """The publication date of Rust release `version`. Any failure, a 404
    included, raises SourceError: a release the stable channel implies must
    have a manifest."""
    try:
        return rt.rust_release_date(version, fetch)
    except (NotFoundError, rt.ResolutionError) as exc:
        raise SourceError(f"Rust channel {version}: {exc}") from exc


def with_stable_channel(releases: list[UpstreamRelease], fetch: Fetch) -> list[UpstreamRelease]:
    """`releases` (endoflife.date's cycles) brought up to Rust's stable channel.

    Every series after endoflife.date's newest cycle, up to and including the
    stable channel's, is added newest first, with its `.0` release's
    publication date as GA. Cycles endoflife.date lists beyond the stable
    series are left out if dated after the stable release, and raise
    SourceError if dated on or before it."""
    try:
        stable, published = rt.rust_stable_release(fetch)
    except (NotFoundError, rt.ResolutionError) as exc:  # a 404 here is an error too
        raise SourceError(f"Rust stable channel: {exc}") from exc
    major, minor, patch = (int(p) for p in stable.split("."))

    kept: list[UpstreamRelease] = []
    for r in releases:
        if version_sort_key(r.version) <= (major, minor):
            kept.append(r)
        elif r.ga is not None and r.ga <= published:
            raise SourceError(
                f"endoflife.date rust lists {r.version} as released on {r.ga.isoformat()}, but Rust's "
                f"stable channel is at {stable} (published {published.isoformat()})"
            )
    if not kept:
        raise SourceError(f"endoflife.date rust lists no cycle at or below the stable series {major}.{minor}")

    newest = max(version_sort_key(r.version) for r in kept)
    if len(newest) != 2 or newest[0] != major:
        raise SourceError(
            f"endoflife.date rust's newest cycle {'.'.join(map(str, newest))} is not a {major}.y series "
            f"like the stable channel's {stable}; the series between them cannot be inferred"
        )
    added = [
        UpstreamRelease(
            f"{major}.{m}",
            published if (m, patch) == (minor, 0) else _release_date(f"{major}.{m}.0", fetch),
            None,
            False,
        )
        for m in range(minor, newest[1], -1)
    ]
    return [*added, *kept]


class RustAdapter:
    key = "rust"
    # Rust's own release notes: they list a release the day it ships, while
    # endoflife.date can lag (the window's new series come from the channel).
    evidence_url = "https://doc.rust-lang.org/stable/releases.html"
    product = "rust"
    window = 2

    def __init__(self, fetch: Fetch = fetch_url) -> None:
        self._fetch = fetch

    def fetch(self) -> list[UpstreamRelease]:
        return with_stable_channel(endoflife(self.product, self._fetch), self._fetch)

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        return [
            TargetVersion(r.version, r.ga, None, channel_has_series(r.version, self._fetch))
            for r in newest_n(ga_only(releases, today), self.window)
        ]

    def extra_changes(self, change: Change) -> list[str]:
        return []
