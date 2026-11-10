"""The report-only adapters (Rust, Node, Clang, GCC) against fixtures that
are copies of the upstream responses on 2026-10-21 (the apt.llvm.org noble
index and Launchpad's noble gcc-14 sources on 2026-11-10). No test touches the
network."""
import json
from datetime import date
from pathlib import Path

import pytest

import frozen
import manifest as mf
import resolve_toolchains
from lifecycle import core
from lifecycle.adapters import ADAPTERS
from lifecycle.adapters import node as adapters_node
from lifecycle.adapters.clang import ClangAdapter
from lifecycle.adapters.gcc import GccAdapter, parse_releases, parse_supported, ubuntu_has_release
from lifecycle.adapters.node import NodeAdapter
from lifecycle.adapters import rust as rust_adapter
from lifecycle.adapters.rust import RustAdapter
from lifecycle.core import EOL_DATE_UNKNOWN, Change, SourceError, UpstreamRelease

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
TODAY = date(2026, 10, 21)
SEED = frozen.SEED  # the frozen test manifest, not the live one (#654)

LAUNCHPAD_NOBLE_GCC = (
    "https://api.launchpad.net/1.0/ubuntu/+archive/primary?ws.op=getPublishedSources"
    "&source_name=gcc-{major}&exact_match=true"
    "&distro_series=https://api.launchpad.net/1.0/ubuntu/noble&status=Published&ws.size=300"
)

URL_FIXTURES = {
    "https://endoflife.date/api/rust.json": "endoflife-rust.json",
    "https://endoflife.date/api/nodejs.json": "endoflife-nodejs.json",
    # nodejs.org's release index, trimmed to the two newest releases of each of
    # 26, 25, 24, 22 and 20 published by 2026-10-21 (epic
    # vergil-project/.github#649).
    "https://nodejs.org/dist/index.json": "nodejs-index.json",
    "https://api.github.com/repos/llvm/llvm-project/releases?per_page=100": "llvm-releases.json",
    "https://apt.llvm.org/noble/dists/": "apt-llvm-noble-index.html",
    "https://gcc.gnu.org/releases.html": "gcc-releases.html",
    "https://gcc.gnu.org/": "gcc-home.html",
    LAUNCHPAD_NOBLE_GCC.format(major=14): "launchpad-noble-gcc-14.json",
}


def fixture_fetch(url):
    """Serve the recorded upstream responses. A noble GCC source package
    without a fixture answers the way Launchpad does for gcc-15 and gcc-16 on
    2026-11-10: no publication in noble."""
    if url in URL_FIXTURES:
        return (FIXTURES / URL_FIXTURES[url]).read_bytes()
    if url.startswith("https://api.launchpad.net/1.0/ubuntu/+archive/primary?ws.op=getPublishedSources&source_name=gcc-"):
        return b'{"start": 0, "total_size": 0, "entries": []}'
    raise AssertionError(f"unexpected fetch: {url}")


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
        "rust": RustAdapter(fetch=RustChannel()),
        "ts-node": NodeAdapter(fetch=fixture_fetch),
        "cpp-clang": ClangAdapter(fetch=fixture_fetch),
        "cpp-gcc": GccAdapter(fetch=fixture_fetch),
    }
    report_only = mf.Manifest(families=tuple(f for f in SEED.families if f.key in adapters))
    results = core.run(report_only, adapters, TODAY)
    assert [r.error for r in results] == [None] * len(adapters)


# --- Rust --------------------------------------------------------------------------


class RustChannel:
    """A fake Rust release channel in front of the fixtures: each
    `channel-rust-<series>.toml` (the URL the toolchain pins' fetcher reads)
    names release `<series>.1`, or the body given in `bodies`; a series in
    `missing` answers 404. Records each series asked about, in order."""

    def __init__(self, missing=(), bodies=None):
        self.missing = set(missing)
        self.bodies = dict(bodies or {})
        self.asked = []

    def __call__(self, url):
        prefix, suffix = rust_adapter.rt.RUST_CHANNEL.split("{series}")
        if not (url.startswith(prefix) and url.endswith(suffix)):
            return fixture_fetch(url)
        series = url[len(prefix):-len(suffix)]
        self.asked.append(series)
        if series in self.missing:
            raise NotFoundError(f"{url}: HTTP 404")
        body = self.bodies.get(series, f'[pkg.rust]\nversion = "{series}.1 (0123456789 2026-10-15)"\n')
        return body.encode()


def test_rust_window_is_newest_two_by_release_order():
    channel = RustChannel()
    adapter = RustAdapter(fetch=channel)
    target = adapter.target(adapter.fetch(), TODAY)
    assert [t.version for t in target] == ["1.99", "1.98"]
    assert channel.asked == ["1.99", "1.98"]
    assert all(t.installable for t in target)
    # 1.98 is EOL upstream since 1.99 shipped; the window keeps it anyway.
    assert all(t.eol is None for t in target)


def test_rust_classify_against_seed():
    changes = _changes(RustAdapter(fetch=RustChannel()))
    assert _kinds(changes) == [("add", "1.99"), ("add", "1.98"), ("out_of_policy", "1.93"), ("out_of_policy", "1.92")]


def test_rust_newest_minus_one_is_not_dropped_once_built():
    adapter = RustAdapter(fetch=RustChannel())
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
    adapter = RustAdapter(fetch=RustChannel())
    releases = [UpstreamRelease("1.100", date(2026, 11, 12), None, False), *adapter.fetch()]
    assert [t.version for t in adapter.target(releases, TODAY)] == ["1.99", "1.98"]


def test_rust_missing_channel_manifest_is_blocked():
    adapter = RustAdapter(fetch=RustChannel(missing={"1.99"}))
    assert _kinds(_changes(adapter))[:2] == [("blocked", "1.99"), ("add", "1.98")]


@pytest.mark.parametrize(
    ("body", "needle"),
    [
        ('[pkg.rust]\nversion = "1.98.1 (0123456789 2026-09-03)"\n', "not a release of 1.99"),
        ("[pkg.rust]\n", "pkg.rust.version None"),
        ("not = toml = at all", "not valid TOML"),
    ],
)
def test_rust_unusable_channel_manifest_is_loud(body, needle):
    adapter = RustAdapter(fetch=RustChannel(bodies={"1.99": body}))
    with pytest.raises(SourceError, match=rf"Rust channel 1\.99: .*{needle}"):
        adapter.target(adapter.fetch(), TODAY)


def test_rust_unreachable_channel_is_loud_not_blocked():
    def fetch(url):
        if "channel-rust-" in url:
            raise SourceError(f"{url}: HTTP 503 Service Unavailable")
        return fixture_fetch(url)

    adapter = RustAdapter(fetch=fetch)
    with pytest.raises(SourceError, match="HTTP 503"):
        adapter.target(adapter.fetch(), TODAY)


# --- Node --------------------------------------------------------------------------


NODE_INDEX = "https://nodejs.org/dist/index.json"


class IndexFetch:
    """The fixture fetcher, counting the reads of nodejs.org's release index.
    `drop` maps a release ("v26.12.1") to the files to remove from its entry."""

    def __init__(self, drop=None):
        self.drop = drop or {}
        self.index_reads = 0

    def __call__(self, url):
        if url != NODE_INDEX:
            return fixture_fetch(url)
        self.index_reads += 1
        index = json.loads(fixture_fetch(url))
        for entry in index:
            entry["files"] = [f for f in entry["files"] if f not in self.drop.get(entry["version"], ())]
        return json.dumps(index).encode()


def test_node_before_lts_start_is_in_sync():
    fetch = IndexFetch()
    adapter = NodeAdapter(fetch=fetch)
    target = adapter.target(adapter.fetch(), TODAY)
    # 26 is not LTS until 2026-10-28; odd majors are never LTS.
    assert [(t.version, t.installable) for t in target] == [("24", True), ("22", True)]
    assert fetch.index_reads == 1  # one read for the whole window
    assert _changes(adapter) == []


def test_node_26_is_added_once_lts():
    adapter = NodeAdapter(fetch=fixture_fetch)
    after = date(2026, 10, 29)
    target = adapter.target(adapter.fetch(), after)
    assert target[0].version == "26"
    assert target[0].ga == date(2026, 10, 28)  # GA is the LTS start, not the 2026-05-05 release
    assert target[0].installable
    assert _kinds(_changes(adapter, after)) == [("add", "26")]


def test_node_major_without_both_tarballs_is_blocked():
    # The image downloads linux-x64 and linux-arm64: a major whose releases
    # lack either one is not installable.
    fetch = IndexFetch(drop={"v26.12.1": ["linux-arm64"], "v26.12.0": ["linux-x64"]})
    adapter = NodeAdapter(fetch=fetch)
    assert _kinds(_changes(adapter, date(2026, 10, 29))) == [("blocked", "26")]


def test_node_major_missing_from_the_index_is_blocked():
    adapter = NodeAdapter(fetch=fixture_fetch, releases=lambda: ["24.22.1", "22.23.4"])
    assert _kinds(_changes(adapter, date(2026, 10, 29))) == [("blocked", "26")]


def test_node_index_is_read_with_the_pins_fetcher():
    # The probe and the upstream refresh share one nodejs.org fetcher (spec §5.4).
    assert adapters_node.rt.node_releases is resolve_toolchains.node_releases


def test_node_malformed_index_is_a_source_error():
    def fetch(url):
        return b"{}" if url == NODE_INDEX else fixture_fetch(url)

    adapter = NodeAdapter(fetch=fetch)
    with pytest.raises(SourceError, match="nodejs.org release index"):
        adapter.target(adapter.fetch(), TODAY)


def test_node_index_fetch_failure_is_the_familys_error():
    def fetch(url):
        if url == NODE_INDEX:
            raise SourceError(f"{url}: HTTP 503 Service Unavailable")
        return fixture_fetch(url)

    family = mf.Manifest(families=(_family("ts-node"),))
    (result,) = core.run(family, {"ts-node": NodeAdapter(fetch=fetch)}, TODAY)
    assert result.error is not None and "HTTP 503" in result.error


def test_node_lts_without_a_start_date_is_an_error():
    adapter = NodeAdapter(fetch=fixture_fetch, releases=lambda: ["24.22.1"])
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
        assert url == "https://apt.llvm.org/noble/dists/"
        return {"llvm-toolchain-noble", "llvm-toolchain-noble-22"}

    changes = _changes(ClangAdapter(fetch=fixture_fetch, index=index))
    assert _kinds(changes)[:2] == [("blocked", "23"), ("add", "22")]


def test_clang_probes_the_noble_suites():
    # The image is built on Ubuntu 24.04 (epic vergil-project/.github#649), so a
    # major published only for Debian trixie is not installable.
    def index(url):
        return {"llvm-toolchain-trixie-22", "llvm-toolchain-trixie-23", "llvm-toolchain-noble-22"}

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
    assert asked == [("gcc-16", "noble"), ("gcc-15", "noble"), ("gcc-14", "noble")]


def test_gcc_default_packaged_check_reads_noble_sources():
    changes = _changes(GccAdapter(fetch=fixture_fetch))
    assert _kinds(changes) == [("blocked", "16"), ("blocked", "15")]


def test_gcc_noble_has_a_released_14():
    # noble-updates and noble-security publish 14.2.0, the release pocket a
    # 14-20240412 snapshot (the fixture holds all three).
    assert ubuntu_has_release("gcc-14", "noble", fixture_fetch) is True
    assert ubuntu_has_release("gcc-15", "noble", fixture_fetch) is False


def _launchpad(*publications):
    entries = [
        {"source_package_name": "gcc-14", "source_package_version": version, "pocket": pocket}
        for version, pocket in publications
    ]
    body = json.dumps({"start": 0, "total_size": len(entries), "entries": entries}).encode()
    return lambda url: body


@pytest.mark.parametrize(
    "publications",
    [
        [("14-20240412-0ubuntu1", "Release")],  # a pre-release snapshot only
        [("14.2.0-4ubuntu2~24.04.1", "Proposed"), ("14-20240412-0ubuntu1", "Release")],
        [("14.2.0-4ubuntu2~24.04.1", "Backports")],
        [("140.1.0-1", "Updates")],  # another major that starts with 14
    ],
)
def test_gcc_noble_snapshot_or_other_pocket_is_not_a_release(publications):
    assert ubuntu_has_release("gcc-14", "noble", _launchpad(*publications)) is False


@pytest.mark.parametrize("pocket", ["Release", "Updates", "Security"])
def test_gcc_noble_release_in_a_default_pocket(pocket):
    assert ubuntu_has_release("gcc-14", "noble", _launchpad(("14.3.0-1ubuntu1", pocket))) is True


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


@pytest.mark.parametrize("adapter", [RustAdapter(), ClangAdapter(), GccAdapter()])
def test_adapters_without_follow_ups(adapter):
    assert adapter.extra_changes(Change(adapter.key, "out_of_policy", "1", "")) == []
