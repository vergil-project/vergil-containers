"""Rust adapter (policy: docs/site/docs/languages/rust.md).

Window: the newest stable release and the one before it (newest and
newest-1), by release order. Source: endoflife.date `rust`. A version is
installable when the Rust release channel has a manifest for the series
(`channel-rust-<v>.toml`) naming a release of it: the image installs that
series' pinned release with rustup (epic vergil-project/.github#649, spec
§5.4). The channel is read with the toolchain pins' own fetcher,
`resolve_toolchains.rust_release`, so the upstream is parsed in one place.

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


class RustAdapter:
    key = "rust"
    evidence_url = "https://endoflife.date/rust"
    product = "rust"
    window = 2

    def __init__(self, fetch: Fetch = fetch_url) -> None:
        self._fetch = fetch

    def fetch(self) -> list[UpstreamRelease]:
        return endoflife(self.product, self._fetch)

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        return [
            TargetVersion(r.version, r.ga, None, channel_has_series(r.version, self._fetch))
            for r in newest_n(ga_only(releases, today), self.window)
        ]

    def extra_changes(self, change: Change) -> list[str]:
        return []
