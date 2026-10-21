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


def _capture_headers(monkeypatch):
    seen = {}

    def urlopen(request, timeout):
        seen.update({k.lower(): v for k, v in request.header_items()})
        return io.BytesIO(b"[]")

    monkeypatch.setattr(sources.urllib.request, "urlopen", urlopen)
    return seen


def test_fetch_url_authenticates_github_api_when_token_set(monkeypatch):
    monkeypatch.setenv(sources.GITHUB_TOKEN_ENV, "tok123\n")
    seen = _capture_headers(monkeypatch)
    sources.fetch_url("https://api.github.com/repos/o/r/releases")
    assert seen["authorization"] == "Bearer tok123"


def test_fetch_url_never_sends_token_to_other_hosts(monkeypatch):
    monkeypatch.setenv(sources.GITHUB_TOKEN_ENV, "tok123")
    seen = _capture_headers(monkeypatch)
    sources.fetch_url("https://hub.docker.com/v2/x")
    assert "authorization" not in seen


def test_fetch_url_github_api_unauthenticated_without_token(monkeypatch):
    monkeypatch.delenv(sources.GITHUB_TOKEN_ENV, raising=False)
    seen = _capture_headers(monkeypatch)
    sources.fetch_url("https://api.github.com/repos/o/r/releases")
    assert "authorization" not in seen


def test_fetch_url_empty_token_is_an_error(monkeypatch):
    monkeypatch.setenv(sources.GITHUB_TOKEN_ENV, "  ")
    _capture_headers(monkeypatch)
    with pytest.raises(SourceError, match="set but empty"):
        sources.fetch_url("https://api.github.com/repos/o/r/releases")


@pytest.mark.parametrize("code", [403, 429])
def test_fetch_url_rate_limit_is_an_error(monkeypatch, code):
    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, code, "rate limited", None, None)

    monkeypatch.setattr(sources.urllib.request, "urlopen", urlopen)
    with pytest.raises(SourceError, match=f"HTTP {code}") as info:
        sources.fetch_url("https://hub.docker.com/v2/x")
    assert not isinstance(info.value, NotFoundError)


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


def _not_found(url):
    raise NotFoundError(f"{url}: HTTP 404")


def _unavailable(url):
    raise SourceError(f"{url}: HTTP 503")


# --- url_exists ------------------------------------------------------------------


def test_url_exists_true_false_and_loud():
    assert sources.url_exists("https://example.invalid/a", lambda url: b"") is True
    assert sources.url_exists("https://example.invalid/a", _not_found) is False
    with pytest.raises(SourceError, match="503"):
        sources.url_exists("https://example.invalid/a", _unavailable)


# --- index_links -----------------------------------------------------------------


def test_index_links_reads_relative_entries_only():
    page = (
        b'<a href="../">../</a><a href="suite-a/">suite-a/</a><a href="suite-b">b</a>'
        b'<a href="/abs/">x</a><a href="https://elsewhere/">y</a><a href="?C=M">sort</a>'
    )
    assert sources.index_links("https://example.invalid/dists/", lambda url: page) == {"suite-a", "suite-b"}


@pytest.mark.parametrize("body, needle", [(b"<pre></pre>", "lists no entries"), (b"\xff\xfe", "not UTF-8")])
def test_index_links_rejects_empty_or_undecodable(body, needle):
    with pytest.raises(SourceError, match=needle):
        sources.index_links("https://example.invalid/dists/", lambda url: body)


# --- github_releases -------------------------------------------------------------


def _release(tag, published="2026-08-25T10:00:00Z", draft=False, prerelease=False):
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease, "published_at": published}


def test_github_releases_keeps_final_releases_only():
    fetch = _fetch_json(
        [
            _release("v2.1.0", "2026-10-20T13:03:13Z"),
            _release("v3.0.0-rc1", prerelease=True),
            _release("v2.2.0", draft=True),
            _release("v2.0.0", "2026-02-24T08:06:08Z"),
        ]
    )
    assert sources.github_releases("owner/repo", fetch) == [
        ("v2.1.0", date(2026, 10, 20)),
        ("v2.0.0", date(2026, 2, 24)),
    ]
    assert fetch.calls == ["https://api.github.com/repos/owner/repo/releases?per_page=100"]


@pytest.mark.parametrize(
    "data, needle",
    [
        ({"message": "API rate limit exceeded"}, "not a JSON list"),
        (["x"], "entry 0 is not an object"),
        ([{"tag_name": "v1", "draft": False, "prerelease": False}], "no 'published_at' field"),
        ([_release(None)], "malformed tag or date"),
        ([_release("v1", "yesterday")], "is not a date"),
        ([_release("v1-rc1", prerelease=True)], "no final release"),
        ([], "no final release"),
    ],
)
def test_github_releases_fails_loud(data, needle):
    with pytest.raises(SourceError, match=needle):
        sources.github_releases("owner/repo", _fetch_json(data))


def test_github_releases_rejects_non_json():
    with pytest.raises(SourceError, match="not valid JSON"):
        sources.github_releases("owner/repo", lambda url: b"<html>")


# --- debian_source_in_suite -------------------------------------------------------


def _debian(*suites_per_version):
    return {"package": "pkg", "versions": [{"version": "1", "suites": list(s)} for s in suites_per_version]}


def test_debian_source_in_suite_matches_the_exact_suite():
    fetch = _fetch_json(_debian(["sid"], ["forky", "sid"], ["trixie", "trixie-backports"]))
    assert sources.debian_source_in_suite("pkg", "trixie", fetch) is True
    assert fetch.calls == ["https://sources.debian.org/api/src/pkg/"]
    assert sources.debian_source_in_suite("pkg", "trixie", _fetch_json(_debian(["trixie-backports"], ["sid"]))) is False


def test_debian_source_unknown_package_is_no():
    assert sources.debian_source_in_suite("pkg", "trixie", _fetch_json({"error": 404})) is False
    assert sources.debian_source_in_suite("pkg", "trixie", _not_found) is False


@pytest.mark.parametrize(
    "body, needle",
    [
        (b"oops", "not valid JSON"),
        (json.dumps({"error": 500}).encode(), "lists no versions"),
        (json.dumps({"versions": []}).encode(), "lists no versions"),
        (json.dumps([]).encode(), "lists no versions"),
        (json.dumps({"versions": [{"version": "1"}]}).encode(), "without a `suites` list"),
    ],
)
def test_debian_source_fails_loud(body, needle):
    with pytest.raises(SourceError, match=needle):
        sources.debian_source_in_suite("pkg", "trixie", lambda url: body)


def test_debian_source_unreachable_is_loud():
    with pytest.raises(SourceError, match="503"):
        sources.debian_source_in_suite("pkg", "trixie", _unavailable)
