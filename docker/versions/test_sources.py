import io
import json
import urllib.error
from datetime import date

import pytest

from lifecycle import sources
from lifecycle.core import EOL_DATE_UNKNOWN, NotFoundError, SourceError


def _fetch_json(data):
    calls = []

    def fetch(url):
        calls.append(url)
        return json.dumps(data).encode()

    fetch.calls = calls
    return fetch


def _cycle(**overrides):
    entry = {"cycle": "3.15", "releaseDate": "2026-10-09", "eol": "2031-10-31", "lts": False}
    entry.update(overrides)
    return {k: v for k, v in entry.items() if v is not ...}


# --- endoflife ---------------------------------------------------------------


def test_endoflife_parses_eol_false_and_date():
    fetch = _fetch_json([_cycle(cycle="1.27", eol=False), _cycle(cycle="1.25", eol="2026-08-19")])
    rs = sources.endoflife("someproduct", fetch)
    assert fetch.calls == ["https://endoflife.date/api/someproduct.json"]
    assert [r.version for r in rs] == ["1.27", "1.25"]
    assert rs[0].eol is None
    assert rs[1].eol == date(2026, 8, 19)
    assert rs[0].ga == date(2026, 10, 9)


def test_endoflife_eol_true_means_eol_with_unknown_date():
    (r,) = sources.endoflife("p", _fetch_json([_cycle(eol=True)]))
    assert r.eol == EOL_DATE_UNKNOWN


@pytest.mark.parametrize("field", ["cycle", "releaseDate", "eol"])
def test_endoflife_rejects_missing_cycle_field(field):
    with pytest.raises(SourceError, match=r"endoflife\.date 'someproduct'.*" + field):
        sources.endoflife("someproduct", _fetch_json([_cycle(), _cycle(**{field: ...})]))


@pytest.mark.parametrize(
    "entry, needle",
    [
        (_cycle(releaseDate="soon"), "releaseDate"),
        (_cycle(releaseDate=None), "releaseDate"),
        (_cycle(eol="2031-13-01"), "eol"),
        (_cycle(cycle="3.15-rc"), "cycle"),
        (_cycle(cycle=3.15), "cycle"),
        (_cycle(lts="not-a-date"), "lts"),
        ("3.15", "not an object"),
    ],
)
def test_endoflife_rejects_malformed_fields(entry, needle):
    with pytest.raises(SourceError, match=needle):
        sources.endoflife("p", _fetch_json([entry]))


def test_endoflife_lts_true_false_absent_and_date():
    rs = sources.endoflife(
        "p",
        _fetch_json(
            [
                _cycle(cycle="26", lts="2026-10-28"),
                _cycle(cycle="24", lts=True),
                _cycle(cycle="23", lts=False),
                _cycle(cycle="21", lts=...),
            ]
        ),
    )
    assert [(r.lts, r.lts_since) for r in rs] == [
        (True, date(2026, 10, 28)),
        (True, None),
        (False, None),
        (False, None),
    ]


@pytest.mark.parametrize(
    "body, needle",
    [(b"<html>rate limited</html>", "not valid JSON"), (b"{}", "not a JSON list"), (b"[]", "no release cycles")],
)
def test_endoflife_rejects_bad_body(body, needle):
    with pytest.raises(SourceError, match=needle):
        sources.endoflife("p", lambda url: body)


def test_endoflife_http_error_raises(monkeypatch):
    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 503, "Service Unavailable", None, None)

    monkeypatch.setattr(sources.urllib.request, "urlopen", urlopen)
    with pytest.raises(SourceError, match=r"https://endoflife\.date/api/p\.json: HTTP 503"):
        sources.endoflife("p", sources.fetch_url)


# --- fetch_url -----------------------------------------------------------------


def test_fetch_url_returns_body_and_sends_user_agent(monkeypatch):
    seen = {}

    def urlopen(request, timeout):
        seen["ua"] = request.get_header("User-agent")
        seen["timeout"] = timeout
        return io.BytesIO(b"body")

    monkeypatch.setattr(sources.urllib.request, "urlopen", urlopen)
    assert sources.fetch_url("https://example.invalid/x") == b"body"
    assert seen == {"ua": sources.USER_AGENT, "timeout": sources.TIMEOUT_SECONDS}


def test_fetch_url_404_is_not_found(monkeypatch):
    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr(sources.urllib.request, "urlopen", urlopen)
    with pytest.raises(NotFoundError, match="HTTP 404"):
        sources.fetch_url("https://example.invalid/x")


@pytest.mark.parametrize("exc", [urllib.error.URLError("no route"), TimeoutError("timed out")])
def test_fetch_url_network_failure_raises(monkeypatch, exc):
    def urlopen(request, timeout):
        raise exc

    monkeypatch.setattr(sources.urllib.request, "urlopen", urlopen)
    with pytest.raises(SourceError, match=r"https://example\.invalid/x"):
        sources.fetch_url("https://example.invalid/x")


# --- docker_hub_tag_exists -------------------------------------------------------


def test_tag_exists_true_on_matching_tag():
    fetch = _fetch_json({"name": "3.15-slim", "digest": "sha256:x"})
    assert sources.docker_hub_tag_exists("img", "3.15-slim", fetch) is True
    assert fetch.calls == ["https://hub.docker.com/v2/namespaces/library/repositories/img/tags/3.15-slim"]


def test_tag_exists_false_on_404():
    def fetch(url):
        raise NotFoundError(f"{url}: HTTP 404")

    assert sources.docker_hub_tag_exists("img", "9.99", fetch) is False


def test_tag_exists_other_failure_is_loud():
    def fetch(url):
        raise SourceError(f"{url}: HTTP 429 Too Many Requests")

    with pytest.raises(SourceError, match="429"):
        sources.docker_hub_tag_exists("img", "3.15", fetch)


@pytest.mark.parametrize("body", [b"not json", json.dumps({"name": "other"}).encode(), b"[]"])
def test_tag_exists_unexpected_body_is_loud(body):
    with pytest.raises(SourceError, match=r"img:3\.15"):
        sources.docker_hub_tag_exists("img", "3.15", lambda url: body)
