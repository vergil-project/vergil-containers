"""GCC adapter for the `cpp-gcc` family (policy:
docs/site/docs/languages/cpp-gcc.md).

Window: the release series gcc.gnu.org lists as maintained, limited to those
the image's Ubuntu 24.04 (noble) base ships as a release. There is no
endoflife.date product, so the adapter reads two gcc.gnu.org pages and fails
loud if either cannot be parsed:

- the GCC Releases page (`releases.html`), whose timeline table dates every
  release. A major is GA on its `X.1` release (since GCC 5, `X.0` is a
  development snapshot); series before GCC 5 used another numbering and are
  ignored.
- the home page's "Supported Releases" list, the policy's record of what is
  maintained. A series it does not list is EOL (upstream gives no date). The
  development series is listed too, but has no `X.1` release yet, so it is
  not GA.

A major is installable when noble publishes a released `gcc-<major>` source
package in a pocket the image installs from (Release, Updates or Security):
a version `<major>.<minor>.<patch>-<revision>`, such as noble-updates'
`14.2.0-4ubuntu2~24.04.1`. A pre-release snapshot such as noble's own
`14-20240412-0ubuntu1` does not count. A maintained major noble does not ship
as a release surfaces as blocked, not behind.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from functools import partial

from lifecycle.core import (
    EOL_DATE_UNKNOWN,
    Change,
    SourceError,
    TargetVersion,
    UpstreamRelease,
    ga_not_eol,
)
from lifecycle.sources import Fetch, fetch_url, ubuntu_source_versions

Packaged = Callable[[str, str], bool]

RELEASES_URL = "https://gcc.gnu.org/releases.html"
HOME_URL = "https://gcc.gnu.org/"
UBUNTU_SERIES = "noble"
FIRST_MODERN_MAJOR = 5  # GCC 5 started "one major per release, X.1 is the first"

_TIMELINE_RE = re.compile(r'id="timeline".*?<table[^>]*>(.*?)</table>', re.S)
_ROW_RE = re.compile(r"<tr><td><a[^>]*>GCC (\d+)\.(\d+)(?:\.\d+)?</a></td>\s*<td>([^<]+)</td></tr>")
_SUPPORTED_RE = re.compile(r"<h2>Supported Releases</h2>(.*?)</dl>", re.S)
_SERIES_RE = re.compile(r"<!--GCC (\d+) status below-->")


def ubuntu_has_release(package: str, series: str, fetch: Fetch) -> bool:
    """Whether `series` publishes a released version of `package` (`gcc-<major>`):
    `<major>.<minor>.<patch>-<revision>`, never a `<major>-<date>` snapshot."""
    major = package.removeprefix("gcc-")
    released = re.compile(rf"^{re.escape(major)}\.\d+\.\d+-")
    return any(released.match(v) for v in ubuntu_source_versions(package, series, fetch))


def _decode(url: str, body: bytes) -> str:
    try:
        return body.decode()
    except UnicodeDecodeError as exc:
        raise SourceError(f"{url}: not UTF-8: {exc}") from exc


def parse_releases(html: str) -> dict[str, date]:
    """Map each modern major to the date of its `X.1` release, from the
    timeline table of `releases.html`. Raises SourceError when the table is
    missing or holds no modern release."""
    table = _TIMELINE_RE.search(html)
    if table is None or "Release date" not in table.group(1):
        raise SourceError(f"{RELEASES_URL}: no release timeline table (has the page layout changed?)")
    ga: dict[str, date] = {}
    majors: set[int] = set()
    for major, minor, when in _ROW_RE.findall(table.group(1)):
        if int(major) < FIRST_MODERN_MAJOR:
            continue
        majors.add(int(major))
        if minor != "1":
            continue
        try:
            ga[major] = datetime.strptime(when.strip(), "%B %d, %Y").date()
        except ValueError as exc:
            raise SourceError(f"{RELEASES_URL}: GCC {major}.{minor} date {when.strip()!r} is not a date") from exc
    if not majors:
        raise SourceError(f"{RELEASES_URL}: the timeline table lists no GCC {FIRST_MODERN_MAJOR}+ release")
    missing = sorted(m for m in majors if str(m) not in ga)
    if missing:
        raise SourceError(f"{RELEASES_URL}: no X.1 release row for GCC {', '.join(map(str, missing))}")
    return ga


def parse_supported(html: str) -> set[str]:
    """The majors in the home page's "Supported Releases" list (including the
    development series). Raises SourceError when the list is missing or empty."""
    section = _SUPPORTED_RE.search(html)
    if section is None:
        raise SourceError(f"{HOME_URL}: no 'Supported Releases' list (has the page layout changed?)")
    supported = set(_SERIES_RE.findall(section.group(1)))
    if not supported:
        raise SourceError(f"{HOME_URL}: the 'Supported Releases' list names no release series")
    return supported


class GccAdapter:
    key = "cpp-gcc"
    evidence_url = RELEASES_URL

    def __init__(self, fetch: Fetch = fetch_url, packaged: Packaged | None = None) -> None:
        self._fetch = fetch
        self._packaged = packaged or partial(ubuntu_has_release, fetch=fetch)

    def fetch(self) -> list[UpstreamRelease]:
        ga = parse_releases(_decode(RELEASES_URL, self._fetch(RELEASES_URL)))
        supported = parse_supported(_decode(HOME_URL, self._fetch(HOME_URL)))
        return [
            UpstreamRelease(major, ga.get(major), None if major in supported else EOL_DATE_UNKNOWN, False)
            for major in sorted(set(ga) | supported, key=int, reverse=True)
        ]

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        return [
            TargetVersion(r.version, r.ga, r.eol, self._packaged(f"gcc-{r.version}", UBUNTU_SERIES))
            for r in ga_not_eol(releases, today)
        ]

    def extra_changes(self, change: Change) -> list[str]:
        return []
