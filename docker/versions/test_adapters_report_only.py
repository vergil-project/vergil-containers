"""The report-only adapters (Rust, Java, Node, Clang, GCC) against fixtures that
are copies of the upstream responses on 2026-10-21. No test touches the network."""
from datetime import date
from pathlib import Path

import pytest

import frozen
import manifest as mf
from lifecycle import core
from lifecycle.adapters import ADAPTERS
from lifecycle.adapters.clang import ClangAdapter
from lifecycle.adapters.gcc import GccAdapter, parse_releases, parse_supported
from lifecycle.adapters.java import JavaAdapter
from lifecycle.adapters.node import NodeAdapter
from lifecycle.adapters.rust import RustAdapter
from lifecycle.core import EOL_DATE_UNKNOWN, Change, NotFoundError, SourceError, UpstreamRelease

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
TODAY = date(2026, 10, 21)
SEED = frozen.SEED  # the frozen test manifest, not the live one (#654)

URL_FIXTURES = {
    "https://endoflife.date/api/rust.json": "endoflife-rust.json",
    "https://endoflife.date/api/eclipse-temurin.json": "endoflife-eclipse-temurin.json",
    "https://endoflife.date/api/nodejs.json": "endoflife-nodejs.json",
    "https://api.github.com/repos/llvm/llvm-project/releases?per_page=100": "llvm-releases.json",
    "https://apt.llvm.org/trixie/dists/": "apt-llvm-trixie-index.html",
    "https://gcc.gnu.org/releases.html": "gcc-releases.html",
    "https://gcc.gnu.org/": "gcc-home.html",
    "https://sources.debian.org/api/src/gcc-14/": "debian-src-gcc-14.json",
}


def fixture_fetch(url):
    """Serve the recorded upstream responses. Debian source packages without a
    fixture answer the way sources.debian.org does for gcc-15/16 on 2026-10-21:
    packaged in forky and sid only."""
    if url in URL_FIXTURES:
        return (FIXTURES / URL_FIXTURES[url]).read_bytes()
    if url.startswith("https://sources.debian.org/api/src/gcc-"):
        return b'{"versions": [{"version": "x", "suites": ["forky", "sid"]}]}'
    raise AssertionError(f"unexpected fetch: {url}")


class Tags:
    """A fake Docker Hub: records each (image, tag) asked about."""

    def __init__(self, missing=()):
        self.missing = set(missing)
        self.asked = []

    def __call__(self, image, tag):
        self.asked.append((image, tag))
        return (image, tag) not in self.missing


def _family(key):
    (family,) = [f for f in SEED.families if f.key == key]
    return family


def _changes(adapter, today=TODAY):
    return core.classify(_family(adapter.key), adapter.target(adapter.fetch(), today), today, 90)


def _kinds(changes):
    return [(c.kind, c.version) for c in changes]


# --- Registry ----------------------------------------------------------------------


def test_every_manifest_family_has_an_adapter():
    assert {f.key for f in SEED.families} <= set(ADAPTERS)
    assert all(key == adapter.key for key, adapter in ADAPTERS.items())


def test_run_reports_no_missing_adapter_against_fixtures():
    adapters = {
        "rust": RustAdapter(fetch=fixture_fetch, tag_exists=Tags()),
        "java": JavaAdapter(fetch=fixture_fetch, tag_exists=Tags()),
        "ts-node": NodeAdapter(fetch=fixture_fetch, setup_exists=lambda url: True),
        "cpp-clang": ClangAdapter(fetch=fixture_fetch),
        "cpp-gcc": GccAdapter(fetch=fixture_fetch),
    }
    report_only = mf.Manifest(families=tuple(f for f in SEED.families if f.key in adapters))
    results = core.run(report_only, adapters, TODAY)
    assert [r.error for r in results] == [None] * len(adapters)


# --- Rust --------------------------------------------------------------------------


def test_rust_window_is_newest_two_by_release_order():
    tags = Tags()
    adapter = RustAdapter(fetch=fixture_fetch, tag_exists=tags)
    target = adapter.target(adapter.fetch(), TODAY)
    assert [t.version for t in target] == ["1.99", "1.98"]
    assert tags.asked == [("rust", "1.99-slim"), ("rust", "1.98-slim")]
    # 1.98 is EOL upstream since 1.99 shipped; the window keeps it anyway.
    assert all(t.eol is None for t in target)


def test_rust_classify_against_seed():
    changes = _changes(RustAdapter(fetch=fixture_fetch, tag_exists=Tags()))
    assert _kinds(changes) == [("add", "1.99"), ("add", "1.98"), ("out_of_policy", "1.93"), ("out_of_policy", "1.92")]


def test_rust_newest_minus_one_is_not_dropped_once_built():
    adapter = RustAdapter(fetch=fixture_fetch, tag_exists=Tags())
    family = mf.Family(
        key="rust",
        language="rust",
        token_prefix="",
        build_arg="RUST_VERSION",
        automation="report",
        versions=tuple(
            mf.ManifestVersion(version=v, ga=None, eol=None, in_policy=True, runtime_published=None)
            for v in ("1.99", "1.98")
        ),
    )
    assert core.classify(family, adapter.target(adapter.fetch(), TODAY), TODAY, 90) == []


def test_rust_ignores_a_future_release():
    adapter = RustAdapter(fetch=fixture_fetch, tag_exists=Tags())
    releases = [UpstreamRelease("1.100", date(2026, 11, 12), None, False), *adapter.fetch()]
    assert [t.version for t in adapter.target(releases, TODAY)] == ["1.99", "1.98"]


def test_rust_missing_tag_is_blocked():
    adapter = RustAdapter(fetch=fixture_fetch, tag_exists=Tags(missing={("rust", "1.99-slim")}))
    assert _kinds(_changes(adapter))[:2] == [("blocked", "1.99"), ("add", "1.98")]


# --- Java --------------------------------------------------------------------------


def test_java_window_is_lts_not_eol():
    tags = Tags()
    adapter = JavaAdapter(fetch=fixture_fetch, tag_exists=tags)
    target = adapter.target(adapter.fetch(), TODAY)
    # 11 and 8 are still supported upstream; the core's no-backfill drops them.
    assert [t.version for t in target] == ["25", "21", "17", "11", "8"]
    assert ("eclipse-temurin", "25-jdk") in tags.asked
    assert {t.version: t.eol for t in target}["25"] == date(2031, 9, 30)


def test_java_classify_against_seed_is_add_25():
    changes = _changes(JavaAdapter(fetch=fixture_fetch, tag_exists=Tags()))
    assert _kinds(changes) == [("add", "25")]


def test_java_lts_past_eol_leaves_the_window():
    adapter = JavaAdapter(fetch=fixture_fetch, tag_exists=Tags())
    later = date(2027, 11, 1)  # 17 is EOL on 2027-10-31; 27 (non-LTS) never counts
    changes = core.classify(_family("java"), adapter.target(adapter.fetch(), later), later, 90)
    assert _kinds(changes) == [("add", "25"), ("out_of_policy", "17")]


# --- Node --------------------------------------------------------------------------


class Setups:
    def __init__(self, missing=()):
        self.missing = set(missing)
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        return url not in self.missing


def test_node_before_lts_start_is_in_sync():
    setups = Setups()
    adapter = NodeAdapter(fetch=fixture_fetch, setup_exists=setups)
    target = adapter.target(adapter.fetch(), TODAY)
    # 26 is not LTS until 2026-10-28; odd majors are never LTS.
    assert [t.version for t in target] == ["24", "22"]
    assert setups.asked == ["https://deb.nodesource.com/setup_24.x", "https://deb.nodesource.com/setup_22.x"]
    assert _changes(adapter) == []


def test_node_26_is_added_once_lts():
    adapter = NodeAdapter(fetch=fixture_fetch, setup_exists=Setups())
    after = date(2026, 10, 29)
    target = adapter.target(adapter.fetch(), after)
    assert target[0].version == "26"
    assert target[0].ga == date(2026, 10, 28)  # GA is the LTS start, not the 2026-05-05 release
    assert _kinds(_changes(adapter, after)) == [("add", "26")]


def test_node_unpublished_nodesource_setup_is_blocked():
    adapter = NodeAdapter(fetch=fixture_fetch, setup_exists=Setups(missing={"https://deb.nodesource.com/setup_26.x"}))
    assert _kinds(_changes(adapter, date(2026, 10, 29))) == [("blocked", "26")]


def test_node_default_setup_check_goes_through_the_fetcher():
    def fetch(url):
        if url == "https://deb.nodesource.com/setup_22.x":
            raise NotFoundError(f"{url}: HTTP 404")
        if url.startswith("https://deb.nodesource.com/"):
            return b"#!/bin/bash"
        return fixture_fetch(url)

    adapter = NodeAdapter(fetch=fetch)
    assert {t.version: t.installable for t in adapter.target(adapter.fetch(), TODAY)} == {"24": True, "22": False}


def test_node_lts_without_a_start_date_is_an_error():
    adapter = NodeAdapter(fetch=fixture_fetch, setup_exists=Setups())
    with pytest.raises(SourceError, match="no LTS start date"):
        adapter.target([UpstreamRelease("24", date(2025, 5, 6), None, True)], TODAY)


def test_node_extra_changes_name_the_vm_pin():
    adapter = NodeAdapter()
    (line,) = adapter.extra_changes(Change("ts-node", "add", "26", ""))
    assert "vergil-vm" in line and "add 26" in line
    assert adapter.extra_changes(Change("ts-node", "eol_soon", "22", "")) == []


# --- Clang -------------------------------------------------------------------------


def test_clang_majors_dated_by_first_final_release():
    releases = {r.version: r for r in ClangAdapter(fetch=fixture_fetch).fetch()}
    assert releases["23"].ga == date(2026, 8, 25)  # llvmorg-23.1.0, not an -rc
    assert releases["22"].ga == date(2026, 2, 24)
    assert releases["17"].ga is not None  # pre-18 majors start at X.0.0
    assert "24" not in releases  # main has no final release
    assert all(r.eol is None for r in releases.values())


def test_clang_classify_against_seed():
    changes = _changes(ClangAdapter(fetch=fixture_fetch))
    assert _kinds(changes) == [("add", "23"), ("add", "22"), ("out_of_policy", "20"), ("out_of_policy", "19")]


def test_clang_major_missing_from_apt_is_blocked():
    def index(url):
        assert url == "https://apt.llvm.org/trixie/dists/"
        return {"llvm-toolchain-trixie", "llvm-toolchain-trixie-22"}

    changes = _changes(ClangAdapter(fetch=fixture_fetch, index=index))
    assert _kinds(changes)[:2] == [("blocked", "23"), ("add", "22")]


def test_clang_skips_non_toolchain_tags():
    def fetch(url):
        return (
            b'[{"tag_name": "llvmorg-23.1.0", "draft": false, "prerelease": false, "published_at": "2026-08-25T00:00:00Z"},'
            b' {"tag_name": "some-other-tag", "draft": false, "prerelease": false, "published_at": "2026-09-01T00:00:00Z"}]'
        )

    assert [r.version for r in ClangAdapter(fetch=fetch).fetch()] == ["23"]


# --- GCC ---------------------------------------------------------------------------


def _gcc_text(name):
    return (FIXTURES / name).read_text()


def test_gcc_releases_parser_dates_each_major_by_x1():
    ga = parse_releases(_gcc_text("gcc-releases.html"))
    assert ga["16"] == date(2026, 4, 30)
    assert ga["15"] == date(2025, 4, 25)
    assert ga["14"] == date(2024, 5, 7)
    assert ga["5"] == date(2015, 4, 22)
    assert "4" not in ga  # pre-GCC-5 numbering is ignored


def test_gcc_supported_list_includes_development_series():
    assert parse_supported(_gcc_text("gcc-home.html")) == {"17", "16", "15", "14"}


def test_gcc_fetch_marks_unlisted_series_eol():
    releases = {r.version: r for r in GccAdapter(fetch=fixture_fetch).fetch()}
    assert releases["13"].eol == EOL_DATE_UNKNOWN
    assert releases["14"].eol is None
    assert releases["17"].ga is None  # development: no 17.1 yet


def test_gcc_classify_against_seed_blocks_15_and_16():
    asked = []

    def packaged(package, suite):
        asked.append((package, suite))
        return package == "gcc-14"

    changes = _changes(GccAdapter(fetch=fixture_fetch, packaged=packaged))
    assert _kinds(changes) == [("blocked", "16"), ("blocked", "15")]
    assert asked == [("gcc-16", "trixie"), ("gcc-15", "trixie"), ("gcc-14", "trixie")]


def test_gcc_default_packaged_check_reads_debian_sources():
    changes = _changes(GccAdapter(fetch=fixture_fetch))
    assert _kinds(changes) == [("blocked", "16"), ("blocked", "15")]


def test_gcc_parser_rejects_page_without_series_table():
    with pytest.raises(SourceError, match="no release timeline table"):
        parse_releases("<html><h2>GCC Releases</h2><p>moved</p></html>")


@pytest.mark.parametrize(
    "html, needle",
    [
        (
            '<h2 id="timeline">x</h2><table><tr><th>Release date</th></tr>'
            '<tr><td><a href="gcc-4.9/">GCC 4.9.4</a></td> <td>August 3, 2016</td></tr></table>',
            "lists no GCC 5\\+ release",
        ),
        (
            '<h2 id="timeline">x</h2><table><tr><th>Release date</th></tr>'
            '<tr><td><a href="gcc-16/">GCC 16.2</a></td> <td>August 7, 2026</td></tr></table>',
            "no X.1 release row for GCC 16",
        ),
        (
            '<h2 id="timeline">x</h2><table><tr><th>Release date</th></tr>'
            '<tr><td><a href="gcc-16/">GCC 16.1</a></td> <td>Spring 2026</td></tr></table>',
            "is not a date",
        ),
    ],
)
def test_gcc_releases_parser_fails_loud(html, needle):
    with pytest.raises(SourceError, match=needle):
        parse_releases(html)


@pytest.mark.parametrize(
    "html, needle",
    [
        ("<h2>News</h2><dl></dl>", "no 'Supported Releases' list"),
        ("<h2>Supported Releases</h2><dl><dt>nothing</dt></dl>", "names no release series"),
    ],
)
def test_gcc_supported_parser_fails_loud(html, needle):
    with pytest.raises(SourceError, match=needle):
        parse_supported(html)


def test_gcc_undecodable_page_is_loud():
    with pytest.raises(SourceError, match="not UTF-8"):
        GccAdapter(fetch=lambda url: b"\xff\xfe").fetch()


# --- Shared ------------------------------------------------------------------------


@pytest.mark.parametrize("adapter", [RustAdapter(), JavaAdapter(), ClangAdapter(), GccAdapter()])
def test_adapters_without_follow_ups(adapter):
    assert adapter.extra_changes(Change(adapter.key, "out_of_policy", "1", "")) == []
