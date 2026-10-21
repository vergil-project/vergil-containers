"""Upstream sources shared by the adapters.

`fetch_url` is the only real network call. Every other function takes its
fetcher as an argument, so tests inject canned responses and never touch the
network. Every fetch or parse failure raises SourceError naming the source:
nothing here returns an empty or partial result on failure.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date

from lifecycle.core import EOL_DATE_UNKNOWN, NotFoundError, SourceError, UpstreamRelease

Fetch = Callable[[str], bytes]

USER_AGENT = "vergil-containers-lifecycle-check (+https://github.com/vergil-project/vergil-containers)"
TIMEOUT_SECONDS = 30

ENDOFLIFE_URL = "https://endoflife.date/api/{product}.json"
DOCKER_HUB_TAG_URL = "https://hub.docker.com/v2/namespaces/library/repositories/{image}/tags/{tag}"

_CYCLE_RE = re.compile(r"^\d+(\.\d+)?$")


def fetch_url(url: str) -> bytes:
    """GET `url` and return the body. HTTP 404 raises NotFoundError; any other
    HTTP, network or timeout failure raises SourceError naming the URL."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NotFoundError(f"{url}: HTTP 404 {exc.reason}") from exc
        raise SourceError(f"{url}: HTTP {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, OSError) as exc:  # URLError, timeouts, resets
        raise SourceError(f"{url}: {exc}") from exc


def _endoflife_date(product: str, cycle: str, field: str, value: object) -> date:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise SourceError(f"endoflife.date {product!r} cycle {cycle!r}: {field} {value!r} is not an ISO date")


def _parse_cycle(product: str, index: int, entry: object) -> UpstreamRelease:
    if not isinstance(entry, dict):
        raise SourceError(f"endoflife.date {product!r}: entry {index} is not an object")
    for field in ("cycle", "releaseDate", "eol"):
        if field not in entry:
            raise SourceError(f"endoflife.date {product!r}: entry {index} has no {field!r} field")
    cycle = entry["cycle"]
    if not isinstance(cycle, str) or not _CYCLE_RE.match(cycle):
        raise SourceError(f"endoflife.date {product!r}: entry {index} cycle {cycle!r} is not a version")

    ga = _endoflife_date(product, cycle, "releaseDate", entry["releaseDate"])

    eol_raw = entry["eol"]
    if eol_raw is False:
        eol = None
    elif eol_raw is True:
        eol = EOL_DATE_UNKNOWN
    else:
        eol = _endoflife_date(product, cycle, "eol", eol_raw)

    # `lts` is optional on endoflife.date: false/absent, true, or the date the
    # release becomes LTS.
    lts_raw = entry.get("lts", False)
    lts_since = None
    if isinstance(lts_raw, bool):
        lts = lts_raw
    else:
        lts = True
        lts_since = _endoflife_date(product, cycle, "lts", lts_raw)

    return UpstreamRelease(version=cycle, ga=ga, eol=eol, lts=lts, lts_since=lts_since)


def endoflife(product: str, fetch: Fetch) -> list[UpstreamRelease]:
    """Parse `https://endoflife.date/api/<product>.json`.

    Strict: a missing `cycle`, `releaseDate` or `eol`, a malformed date, a
    non-list body or an empty list raises SourceError naming the product."""
    url = ENDOFLIFE_URL.format(product=product)
    body = fetch(url)
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError(f"endoflife.date {product!r}: {url} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise SourceError(f"endoflife.date {product!r}: {url} is not a JSON list")
    if not data:
        raise SourceError(f"endoflife.date {product!r}: {url} lists no release cycles")
    return [_parse_cycle(product, i, entry) for i, entry in enumerate(data)]


def docker_hub_tag_exists(image: str, tag: str, fetch: Fetch) -> bool:
    """Whether the official Docker Hub image `image` has tag `tag`.

    A 404 is "no". Any other failure (rate limit, network) raises SourceError:
    an unreachable registry never reads as "not installable"."""
    url = DOCKER_HUB_TAG_URL.format(image=image, tag=tag)
    try:
        body = fetch(url)
    except NotFoundError:
        return False
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError(f"Docker Hub {image}:{tag}: {url} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("name") != tag:
        raise SourceError(f"Docker Hub {image}:{tag}: {url} did not describe tag {tag!r}")
    return True
