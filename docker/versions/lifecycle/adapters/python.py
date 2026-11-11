"""Python adapter (policy: docs/site/docs/languages/python.md).

Window: every minor version that is GA and not EOL (spec §5.1); the shared
core applies no-backfill. Source: endoflife.date `python`. A version is
installable when a recent python-build-standalone release has an install-only
build of the series for both architectures (spec §5.4): the image unpacks that
build (spec §5.3.1). The probe is Task 6's python-build-standalone fetcher,
`resolve_toolchains.pbs_series_builds`, the same search the daily upstream
refresh pins from, so a series called installable here is one the refresh can
pin.

Runtime (spec §7, plan Task 13b): `vergil-python` publishes one runtime package
per series, `vergil-python<x.y>`, to the vergil apt repository. Each target
version carries whether that package is published, read from the apt index.
That serves packaging, not the image, and is unchanged.
"""
from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from datetime import date
from functools import partial
from pathlib import Path

from lifecycle.core import Change, SourceError, TargetVersion, UpstreamRelease, ga_not_eol
from lifecycle.runtime import AptIndex, read_index
from lifecycle.sources import Fetch, endoflife, fetch_url

sys.path.append(str(Path(__file__).resolve().parents[3] / "pins"))
import resolve_toolchains as rt  # noqa: E402

# series -> the series python-build-standalone builds for both architectures.
BuiltSeries = Callable[[list[str]], set[str]]
ReadIndex = Callable[[], AptIndex]


def runtime_package(version: str) -> str:
    """The `vergil-python` runtime package for series `version` (exact name:
    `vergil-python3.14`, never a patch-pinned `vergil-python3.14.8`)."""
    return f"vergil-python{version}"


def pbs_built_series(series: Iterable[str], fetch: Fetch) -> set[str]:
    """The series among `series` that a recent python-build-standalone release
    builds install-only for both architectures. A failed fetch raises the
    fetcher's SourceError, and a malformed upstream body raises SourceError
    too: an unreadable upstream never reads as "not installable"."""
    try:
        return set(rt.pbs_series_builds(series, fetch))
    except rt.ResolutionError as exc:
        raise SourceError(f"python-build-standalone: {exc}") from exc


class PythonAdapter:
    key = "python"
    evidence_url = "https://endoflife.date/python"
    product = "python"

    def __init__(
        self, fetch: Fetch = fetch_url, built_series: BuiltSeries | None = None, runtime_index: ReadIndex | None = None
    ) -> None:
        self._fetch = fetch
        self._built_series = built_series or partial(pbs_built_series, fetch=fetch)
        self._runtime_index = runtime_index or partial(read_index, fetch)

    def fetch(self) -> list[UpstreamRelease]:
        return endoflife(self.product, self._fetch)

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        window = ga_not_eol(releases, today)
        if not window:
            return []  # the core reports an empty window as an error
        built = self._built_series([r.version for r in window])  # probed once for every version
        index = self._runtime_index()  # read once for every version
        return [
            TargetVersion(r.version, r.ga, r.eol, r.version in built, index.published(runtime_package(r.version)))
            for r in window
        ]

    def extra_changes(self, change: Change) -> list[str]:
        return []
