"""Python adapter (policy: docs/site/docs/languages/python.md).

Window: every minor version that is GA and not EOL (spec §5.1); the shared
core applies no-backfill. Source: endoflife.date `python`. A version is
installable when the official `python:<v>-slim` base image tag exists.

Runtime (spec §7, plan Task 13b): `vergil-python` publishes one runtime package
per series, `vergil-python<x.y>`, to the vergil apt repository. Each target
version carries whether that package is published, read from the apt index.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from functools import partial

from lifecycle.core import Change, TargetVersion, UpstreamRelease, ga_not_eol
from lifecycle.runtime import AptIndex, read_index
from lifecycle.sources import Fetch, docker_hub_tag_exists, endoflife, fetch_url

TagExists = Callable[[str, str], bool]
ReadIndex = Callable[[], AptIndex]


def runtime_package(version: str) -> str:
    """The `vergil-python` runtime package for series `version` (exact name:
    `vergil-python3.14`, never a patch-pinned `vergil-python3.14.8`)."""
    return f"vergil-python{version}"


class PythonAdapter:
    key = "python"
    evidence_url = "https://endoflife.date/python"
    product = "python"
    image = "python"

    def __init__(
        self, fetch: Fetch = fetch_url, tag_exists: TagExists | None = None, runtime_index: ReadIndex | None = None
    ) -> None:
        self._fetch = fetch
        self._tag_exists = tag_exists or partial(docker_hub_tag_exists, fetch=fetch)
        self._runtime_index = runtime_index or partial(read_index, fetch)

    def fetch(self) -> list[UpstreamRelease]:
        return endoflife(self.product, self._fetch)

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        window = ga_not_eol(releases, today)
        if not window:
            return []  # the core reports an empty window as an error
        index = self._runtime_index()  # read once for every version
        return [
            TargetVersion(
                r.version,
                r.ga,
                r.eol,
                self._tag_exists(self.image, f"{r.version}-slim"),
                index.published(runtime_package(r.version)),
            )
            for r in window
        ]

    def extra_changes(self, change: Change) -> list[str]:
        return []
