"""Clang adapter for the `cpp-clang` family (policy:
docs/site/docs/languages/cpp-clang.md).

Window: the newest LLVM major and the one before it (newest and newest-1).
Source: the GitHub releases API for `llvm/llvm-project` (there is no
endoflife.date product). Release candidates and other pre-releases are
skipped; a major is GA on its first final release (`llvmorg-X.1.0` since LLVM
18, `llvmorg-X.0.0` before). LLVM publishes no EOL dates.

A major is installable when apt.llvm.org publishes the
`llvm-toolchain-trixie-<major>` suite for the image's Debian base; a GA major
it does not publish surfaces as blocked.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from functools import partial

from lifecycle.core import Change, TargetVersion, UpstreamRelease, ga_only, newest_n
from lifecycle.sources import Fetch, fetch_url, github_releases, index_links

Index = Callable[[str], set[str]]

REPO = "llvm/llvm-project"
APT_INDEX_URL = "https://apt.llvm.org/trixie/dists/"
APT_SUITE = "llvm-toolchain-trixie-{major}"
_TAG_RE = re.compile(r"^llvmorg-(\d+)\.\d+\.\d+$")


class ClangAdapter:
    key = "cpp-clang"
    window = 2

    def __init__(self, fetch: Fetch = fetch_url, index: Index | None = None) -> None:
        self._fetch = fetch
        self._index = index or partial(index_links, fetch=fetch)

    def fetch(self) -> list[UpstreamRelease]:
        """One release per major, dated by its earliest final release."""
        first: dict[str, date] = {}
        for tag, published in github_releases(REPO, self._fetch):
            m = _TAG_RE.match(tag)
            if m is None:
                continue  # not a toolchain release tag
            major = m.group(1)
            if major not in first or published < first[major]:
                first[major] = published
        return [UpstreamRelease(major, ga, None, False) for major, ga in first.items()]

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        window = newest_n(ga_only(releases, today), self.window)
        suites = self._index(APT_INDEX_URL)
        return [
            TargetVersion(r.version, r.ga, r.eol, APT_SUITE.format(major=r.version) in suites) for r in window
        ]

    def extra_changes(self, change: Change) -> list[str]:
        return []
