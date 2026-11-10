"""Hermetic tests for the language toolchain pins (epic
vergil-project/.github#649, Task 6): the toolchains.yml schema, its checks
against the version manifest, the resolvers and the build args generate.py
emits. Every fetch is INJECTED: no test touches the network."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

DOCKER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DOCKER / "versions"))

import check_pins  # noqa: E402
import frozen  # noqa: E402
import generate as g  # noqa: E402
import generate_catalog  # noqa: E402
import manifest as mf  # noqa: E402
import resolve_toolchains as rt  # noqa: E402

SEED = frozen.SEED  # frozen manifest: python 3.14-3.12, go 1.26, rust 1.93/1.92, ts-node 24/22, core node 22


def _h(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _pin(version: str, *, release: str | None = None, hashed: bool = True) -> rt.Pin:
    sha = {arch: _h(f"{version}-{arch}") for arch in rt.ARCHES} if hashed else None
    return rt.Pin(version=version, sha256=sha, release=release)


def _pins() -> rt.Toolchains:
    """Pins of exactly what the frozen manifest lists."""
    return rt.Toolchains(
        series={
            "python": {s: _pin(f"{s}.1", release="20261026") for s in ("3.14", "3.13", "3.12")},
            "go": {"1.26": _pin("1.26.10")},
            "node": {"24": _pin("24.22.2"), "22": _pin("22.23.4")},
            "rust": {"1.93": _pin("1.93.1", hashed=False), "1.92": _pin("1.92.0", hashed=False)},
        },
        tools={"rustup-init": _pin("1.29.3")},
    )


def _doc(t: rt.Toolchains) -> dict:
    return yaml.safe_load(rt.dump_toolchains(t))


# --- The schema -------------------------------------------------------------------


def test_write_round_trips(tmp_path):
    path = tmp_path / "toolchains.yml"
    path.write_text(rt.dump_toolchains(_pins()))
    loaded = rt.load_toolchains(path)
    assert loaded == _pins()
    path.write_text(rt.dump_toolchains(loaded))
    assert rt.load_toolchains(path) == loaded


def test_live_toolchains_is_canonical_and_consistent():
    path = DOCKER / "pins" / "toolchains.yml"
    pins = rt.load_toolchains(path)
    assert path.read_text() == rt.dump_toolchains(pins)
    assert rt.consistency_errors(mf.load_manifest(DOCKER / "versions" / "manifest.yml"), pins) == []


@pytest.mark.parametrize("kind", ["python", "go", "node"])
def test_entry_needs_both_arches(kind):
    doc = _doc(_pins())
    series = next(iter(doc["toolchains"][kind]))
    del doc["toolchains"][kind][series]["sha256"]["arm64"]
    with pytest.raises(rt.ToolchainsError, match=rf"toolchain '{kind}' '{series}': sha256: missing key\(s\) 'arm64'"):
        rt.parse_toolchains(doc)


def test_rustup_init_needs_both_arches():
    doc = _doc(_pins())
    del doc["tools"]["rustup-init"]["sha256"]["amd64"]
    with pytest.raises(rt.ToolchainsError, match=r"tool 'rustup-init': sha256: missing key\(s\) 'amd64'"):
        rt.parse_toolchains(doc)


def test_rust_needs_no_hash():
    doc = _doc(_pins())
    assert doc["toolchains"]["rust"]["1.93"] == {"version": "1.93.1"}
    assert rt.parse_toolchains(doc).series["rust"]["1.93"].sha256 is None
    doc["toolchains"]["rust"]["1.93"]["sha256"] = {arch: _h(arch) for arch in rt.ARCHES}
    with pytest.raises(rt.ToolchainsError, match=r"unknown key\(s\) 'sha256'"):
        rt.parse_toolchains(doc)


@pytest.mark.parametrize(
    "edit, needle",
    [
        (lambda d: d["toolchains"]["python"]["3.14"].update(version="3.13.1"), "not a release of python 3.14"),
        (lambda d: d["toolchains"]["python"]["3.14"].pop("release"), r"missing key\(s\) 'release'"),
        (lambda d: d["toolchains"]["python"]["3.14"].update(release="2026-10-26"), "release"),
        (lambda d: d["toolchains"]["go"]["1.26"]["sha256"].update(amd64="ABC"), "amd64"),
        (lambda d: d["toolchains"]["node"].update({"24.1": d["toolchains"]["node"]["24"]}), "series"),
        (lambda d: d["toolchains"].update(ruby={}), "unknown toolchain"),
        (lambda d: d["tools"].update(cargo={}), "unknown tool"),
        (lambda d: d.update(schema=2), "schema 2"),
    ],
)
def test_schema_violations_fail_loud(edit, needle):
    doc = _doc(_pins())
    edit(doc)
    with pytest.raises(rt.ToolchainsError, match=needle):
        rt.parse_toolchains(doc)


# --- Against the manifest -----------------------------------------------------------


def test_exact_pins_are_consistent():
    assert rt.consistency_errors(SEED, _pins()) == []


def test_missing_series_fails():
    pins = _pins()
    del pins.series["python"]["3.13"]
    assert rt.consistency_errors(SEED, pins) == [
        "toolchain 'python' '3.13': the manifest lists the series but toolchains.yml has no pin"
    ]


def test_orphan_series_fails():
    pins = _pins()
    pins.series["go"]["1.25"] = _pin("1.25.9")
    (error,) = rt.consistency_errors(SEED, pins)
    assert error.startswith("toolchain 'go' '1.25': pinned, but neither a go series nor a core runtime")


def test_core_node_pin_not_orphan():
    # Core Node 22 with no ts-node series 22: its entry is still required.
    families = tuple(
        replace(f, versions=tuple(v for v in f.versions if v.version != "22")) if f.key == "ts-node" else f
        for f in SEED.families
    )
    m = replace(SEED, families=families)
    assert [v.version for v in next(f for f in m.families if f.key == "ts-node").versions] == ["24"]
    assert m.core.node == "22"
    assert rt.required_series(m)["node"] == ["24", "22"]
    assert rt.consistency_errors(m, _pins()) == []


def test_core_node_major_needs_pin():
    m = replace(SEED, core=mf.Core(python="3.15", node="26"))
    # ts-node 22 still needs its pin; the core major 26 has none.
    assert rt.consistency_errors(m, _pins()) == [
        "toolchain 'node' '26': the manifest lists the series but toolchains.yml has no pin",
    ]
    no_22 = replace(m, families=tuple(
        replace(f, versions=tuple(v for v in f.versions if v.version != "22")) if f.key == "ts-node" else f
        for f in m.families
    ))
    assert rt.consistency_errors(no_22, _pins()) == [
        "toolchain 'node' '26': the manifest lists the series but toolchains.yml has no pin",
        "toolchain 'node' '22': pinned, but neither a ts-node series nor a core runtime in the manifest; remove it",
    ]


def test_core_python_needs_no_pin():
    # The core Python is vergil-python from the apt repository: no pin, and a
    # core series outside the family window asks for none.
    m = replace(SEED, core=mf.Core(python="3.16", node="22"))
    assert rt.required_series(m)["python"] == ["3.14", "3.13", "3.12"]
    assert rt.consistency_errors(m, _pins()) == []


def test_rustup_init_follows_rust():
    pins = _pins()
    del pins.tools["rustup-init"]
    assert rt.consistency_errors(SEED, pins) == ["tool 'rustup-init': rust is pinned but toolchains.yml has no rustup-init pin"]
    no_rust = replace(SEED, families=tuple(f for f in SEED.families if f.key != "rust"))
    pins = _pins()
    del pins.series["rust"]
    assert rt.consistency_errors(no_rust, pins) == [
        "tool 'rustup-init': pinned, but the manifest has no rust series; remove it"
    ]


def _check_tree(tmp_path: Path, pins_text: str) -> Path:
    root = tmp_path / "docker"
    (root / "versions").mkdir(parents=True)
    (root / "pins").mkdir()
    shutil.copy2(frozen.MANIFEST, root / "versions" / "manifest.yml")
    (root / "pins" / "toolchains.yml").write_text(pins_text)
    return root


def test_check_pins_reports_toolchain_errors(tmp_path):
    assert check_pins.toolchain_errors(_check_tree(tmp_path / "ok", rt.dump_toolchains(_pins()))) == []
    doc = _doc(_pins())
    del doc["toolchains"]["node"]["24"]["sha256"]["amd64"]
    (error,) = check_pins.toolchain_errors(_check_tree(tmp_path / "bad", yaml.safe_dump(doc)))
    assert "toolchain 'node' '24': sha256: missing key(s) 'amd64'" in error
    pins = _pins()
    del pins.series["go"]
    (error,) = check_pins.toolchain_errors(_check_tree(tmp_path / "missing", rt.dump_toolchains(pins)))
    assert error.startswith("toolchain 'go' '1.26'")


def test_check_pins_main_fails_on_toolchain_drift(monkeypatch, capsys):
    monkeypatch.setattr(check_pins, "toolchain_errors", lambda root: ["toolchain 'go' '1.26': no pin"])
    assert check_pins.main(DOCKER) == 1
    assert "::error::toolchain 'go' '1.26': no pin" in capsys.readouterr().err


# --- Build args ---------------------------------------------------------------------


def test_build_args_per_family():
    pins = _pins()
    assert rt.build_args(pins, "python", "3.14") == {
        "TOOLCHAIN_VERSION": "3.14.1",
        "TOOLCHAIN_SHA256_AMD64": _h("3.14.1-amd64"),
        "TOOLCHAIN_SHA256_ARM64": _h("3.14.1-arm64"),
        "PBS_RELEASE": "20261026",
    }
    assert rt.build_args(pins, "ts-node", "24") == {
        "TOOLCHAIN_VERSION": "24.22.2",
        "TOOLCHAIN_SHA256_AMD64": _h("24.22.2-amd64"),
        "TOOLCHAIN_SHA256_ARM64": _h("24.22.2-arm64"),
    }
    assert rt.build_args(pins, "rust", "1.92") == {
        "TOOLCHAIN_VERSION": "1.92.0",
        "RUSTUP_INIT_VERSION": "1.29.3",
        "RUSTUP_INIT_SHA256_AMD64": _h("1.29.3-amd64"),
        "RUSTUP_INIT_SHA256_ARM64": _h("1.29.3-arm64"),
    }
    assert rt.build_args(pins, "cpp-clang", "20") == {}
    with pytest.raises(rt.ToolchainsError, match="go 1.27 has no pin"):
        rt.build_args(pins, "go", "1.27")


def test_generate_emits_build_args():
    include = json.loads(g.render_matrix_json(SEED, frozen.PINS))["include"]
    families = {f.key: f for f in SEED.families}
    for e in include:
        if e["language"] not in families:
            continue
        f = families[e["language"]]
        expected = {f.build_arg: e["version"], **rt.build_args(frozen.PINS, f.key, e["version"])}
        assert e["build-args"] == expected
        assert list(e["build-args"])[0] == f.build_arg
    by = {(e["language"], e["version"]): e["build-args"] for e in include}
    assert by[("go", "1.26")]["TOOLCHAIN_VERSION"] == frozen.PINS.series["go"]["1.26"].version
    assert by[("python", "3.12")]["PBS_RELEASE"] == frozen.PINS.series["python"]["3.12"].release
    assert by[("rust", "1.93")]["RUSTUP_INIT_VERSION"] == frozen.PINS.tools["rustup-init"].version
    assert by[("cpp-gcc", "14")] == {"GCC_VERSION": "14"}


def test_generate_fails_loud_on_a_missing_pin():
    pins = _pins()
    del pins.series["node"]["22"]
    with pytest.raises(g.GenerateError, match="toolchain 'node' '22'"):
        g.render_matrix_json(SEED, pins)


def test_live_matrix_embeds_the_live_pins():
    root = DOCKER.parent
    pins = rt.load_toolchains(root / g.TOOLCHAINS)
    matrix = json.loads((root / g.MATRIX_JSON).read_text())
    rows = {(e["language"], e["version"]): e["build-args"] for e in matrix["include"]}
    assert rows[("go", "1.27")]["TOOLCHAIN_VERSION"] == pins.series["go"]["1.27"].version


def test_catalog_lists_every_toolchain_pin():
    table = generate_catalog.render_toolchains(_pins())
    assert "| python | 3.14 | 3.14.1 | 20261026 | `" in table
    assert "| rust | 1.93 | 1.93.1 | — | — (rustup verifies) | — (rustup verifies) |" in table
    assert f"| rustup-init | — | 1.29.3 | — | `{_h('1.29.3-amd64')}` | `{_h('1.29.3-arm64')}` |" in table


# --- The resolvers ------------------------------------------------------------------


def _fetch(bodies: dict[str, object]):
    """A fetch(url) serving canned bodies; any other URL fails like a 404."""
    def fetch(url: str) -> bytes:
        if url not in bodies:
            raise rt.ResolutionError(f"{url}: HTTP 404 Not Found")
        body = bodies[url]
        return body if isinstance(body, bytes) else (json.dumps(body) if not isinstance(body, str) else body).encode()
    return fetch


def _pbs_sums(release: str, builds: dict[str, tuple[str, ...]]) -> str:
    lines = []
    for version, arches in builds.items():
        for arch in arches:
            lines.append(f"{_h(version + arch + release)}  {rt.pbs_asset(version, release, arch)}")
        # Variants that are not install-only builds are ignored.
        lines.append(f"{_h('stripped')}  cpython-{version}+{release}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz")
        lines.append(f"{_h('v2')}  cpython-{version}+{release}-x86_64_v2-unknown-linux-gnu-install_only.tar.gz")
    return "\n".join(lines) + "\n"


def _pbs_bodies(releases: dict[str, dict[str, tuple[str, ...]]]) -> dict[str, object]:
    feed = "".join(
        f'<entry><link rel="alternate" href="https://github.com/astral-sh/python-build-standalone/releases/tag/{r}"/></entry>'
        for r in releases
    )
    bodies: dict[str, object] = {rt.PBS_RELEASES_FEED: f"<feed>{feed}</feed>"}
    for release, builds in releases.items():
        bodies[rt.PBS_DOWNLOAD.format(release=release, name="SHA256SUMS")] = _pbs_sums(release, builds)
    return bodies


def test_resolve_python_picks_install_only_both_arches():
    fetch = _fetch(_pbs_bodies({
        # The newest release has 3.15 for amd64 only: the older one is chosen.
        "20261102": {"3.15.3": ("amd64",), "3.14.11": ("amd64", "arm64")},
        "20261026": {"3.15.2": ("amd64", "arm64"), "3.14.10": ("amd64", "arm64")},
    }))
    pins = rt.resolve_python(["3.15", "3.14"], fetch)
    assert pins["3.15"] == rt.Pin(
        version="3.15.2",
        sha256={arch: _h("3.15.2" + arch + "20261026") for arch in rt.ARCHES},
        release="20261026",
    )
    assert pins["3.14"].version == "3.14.11"
    assert pins["3.14"].release == "20261102"


def test_resolve_python_fails_when_no_release_has_the_series():
    fetch = _fetch(_pbs_bodies({"20261026": {"3.15.2": ("amd64",)}}))
    with pytest.raises(rt.ResolutionError, match="3.15 for both amd64 and arm64"):
        rt.resolve_python(["3.15"], fetch)


def _go_release(version: str, *, stable: bool = True, arches=rt.ARCHES, sha: str | None = None) -> dict:
    files = [
        {"filename": f"go{version}.linux-{a}.tar.gz", "os": "linux", "arch": a, "kind": "archive",
         "sha256": _h(version + a) if sha is None else sha}
        for a in arches
    ]
    files.append({"filename": f"go{version}.src.tar.gz", "os": "", "arch": "", "kind": "source", "sha256": _h("src")})
    return {"version": f"go{version}", "stable": stable, "files": files}


def test_resolve_go_newest_stable_patch():
    fetch = _fetch({rt.GO_RELEASES: [
        _go_release("1.28rc1", stable=False),
        _go_release("1.27.3"),
        _go_release("1.27.4", arches=("amd64",)),
        _go_release("1.27.2"),
        _go_release("1.26.10"),
        _go_release("1.4.2", sha=""),  # the oldest releases list no SHA-256
    ]})
    pins = rt.resolve_go(["1.27", "1.26"], fetch)
    assert pins["1.27"] == rt.Pin(version="1.27.3", sha256={a: _h("1.27.3" + a) for a in rt.ARCHES})
    assert pins["1.26"].version == "1.26.10"
    with pytest.raises(rt.ResolutionError, match="SHA-256"):
        rt.resolve_go(["1.4"], fetch)
    with pytest.raises(rt.ResolutionError, match=r"no stable go1\.29\.x"):
        rt.resolve_go(["1.29"], fetch)


def test_resolve_node_newest_patch_with_both_tarballs():
    index = [
        {"version": "v24.23.0", "files": ["linux-x64"]},
        {"version": "v24.22.2", "files": ["linux-arm64", "linux-x64", "win-x64-msi"]},
        {"version": "v24.9.0", "files": ["linux-arm64", "linux-x64"]},
        {"version": "v22.23.4", "files": ["linux-arm64", "linux-x64"]},
    ]
    sums = "".join(
        f"{_h('24.22.2' + a)}  {rt.node_tarball('24.22.2', a)}\n" for a in rt.ARCHES
    ) + f"{_h('xz')}  node-v24.22.2-linux-x64.tar.xz\n"
    fetch = _fetch({rt.NODE_INDEX: index, rt.NODE_SHASUMS.format(version="24.22.2"): sums})
    assert rt.resolve_node(["24"], fetch) == {
        "24": rt.Pin(version="24.22.2", sha256={a: _h("24.22.2" + a) for a in rt.ARCHES})
    }
    # 22.23.4's SHASUMS256.txt is not served: the lookup fails loud.
    with pytest.raises(rt.ResolutionError, match="HTTP 404"):
        rt.resolve_node(["22"], fetch)


def test_resolve_rust_from_the_series_channel_manifest():
    url = rt.RUST_CHANNEL.format(series="1.93")
    fetch = _fetch({url: '[pkg.rust]\nversion = "1.93.1 (01f6ddf75 2026-02-11)"\n'})
    assert rt.resolve_rust(["1.93"], fetch) == {"1.93": rt.Pin(version="1.93.1")}
    bad = _fetch({url: '[pkg.rust]\nversion = "1.94.0 (abc 2026-03-01)"\n'})
    with pytest.raises(rt.ResolutionError, match="not a release of 1.93"):
        rt.resolve_rust(["1.93"], bad)


def test_resolve_rustup_init_hashes_per_arch():
    bodies: dict[str, object] = {rt.RUSTUP_RELEASE: "schema-version = '1'\nversion = '1.29.3'\n"}
    for arch, triple in rt.RUSTUP_TRIPLES.items():
        url = rt.RUSTUP_INIT_SHA256.format(version="1.29.3", triple=triple)
        bodies[url] = f"{_h(arch)}  *rustup-init\n"
    assert rt.rustup_init_release(_fetch(bodies)) == rt.Pin(
        version="1.29.3", sha256={a: _h(a) for a in rt.ARCHES}
    )
    del bodies[rt.RUSTUP_INIT_SHA256.format(version="1.29.3", triple=rt.RUSTUP_TRIPLES["arm64"])]
    with pytest.raises(rt.ResolutionError, match="aarch64-unknown-linux-gnu"):
        rt.rustup_init_release(_fetch(bodies))


def _upstreams() -> dict[str, object]:
    """Canned upstreams serving every series of the frozen manifest."""
    bodies = _pbs_bodies({"20261026": {f"{s}.1": rt.ARCHES for s in ("3.14", "3.13", "3.12")}})
    bodies[rt.GO_RELEASES] = [_go_release("1.26.10")]
    bodies[rt.NODE_INDEX] = [{"version": f"v{v}", "files": ["linux-x64", "linux-arm64"]} for v in ("24.22.2", "22.23.4")]
    for v in ("24.22.2", "22.23.4"):
        bodies[rt.NODE_SHASUMS.format(version=v)] = "".join(f"{_h(v + a)}  {rt.node_tarball(v, a)}\n" for a in rt.ARCHES)
    for s, v in (("1.93", "1.93.1"), ("1.92", "1.92.0")):
        bodies[rt.RUST_CHANNEL.format(series=s)] = f'[pkg.rust]\nversion = "{v} (abc 2026-01-01)"\n'
    bodies[rt.RUSTUP_RELEASE] = "version = '1.29.3'\n"
    for arch, triple in rt.RUSTUP_TRIPLES.items():
        bodies[rt.RUSTUP_INIT_SHA256.format(version="1.29.3", triple=triple)] = f"{_h('1.29.3-' + arch)}  *rustup-init\n"
    return bodies


def test_resolve_covers_every_required_series():
    t = rt.resolve(SEED, _fetch(_upstreams()))
    assert rt.consistency_errors(SEED, t) == []
    assert t.series["python"]["3.13"].version == "3.13.1"
    assert t.series["node"]["22"].version == "22.23.4"


def test_main_reports_then_writes(tmp_path, capsys):
    out = tmp_path / "toolchains.yml"
    fetch = _fetch(_upstreams())
    assert rt.main([], fetch=fetch, manifest=frozen.MANIFEST, out=out) == 0
    assert not out.exists()
    assert "added go 1.26: 1.26.10" in capsys.readouterr().out
    assert rt.main(["--write"], fetch=fetch, manifest=frozen.MANIFEST, out=out) == 0
    written = out.read_text()
    assert rt.load_toolchains(out) == rt.resolve(SEED, fetch)
    # Right after a write, a run without --write reports no change.
    assert rt.main([], fetch=fetch, manifest=frozen.MANIFEST, out=out) == 0
    assert "no toolchain pin changes" in capsys.readouterr().out
    assert out.read_text() == written


def test_main_reports_a_bumped_pin(tmp_path, capsys):
    out = tmp_path / "toolchains.yml"
    fetch = _fetch(_upstreams())
    resolved = rt.resolve(SEED, fetch)
    older = replace(resolved, series={**resolved.series, "go": {"1.26": _pin("1.26.9")}})
    out.write_text(rt.dump_toolchains(older))
    assert rt.main(["--write"], fetch=fetch, manifest=frozen.MANIFEST, out=out) == 0
    assert "bumped go 1.26: 1.26.9 -> 1.26.10" in capsys.readouterr().out
    assert rt.load_toolchains(out) == resolved


def test_a_changed_hash_of_a_pinned_release_fails_loud(tmp_path, capsys):
    out = tmp_path / "toolchains.yml"
    fetch = _fetch(_upstreams())
    resolved = rt.resolve(SEED, fetch)
    tampered = replace(resolved, series={**resolved.series, "go": {"1.26": _pin("1.26.10")}})
    assert tampered.series["go"]["1.26"].sha256 != resolved.series["go"]["1.26"].sha256
    out.write_text(rt.dump_toolchains(tampered))
    before = out.read_text()
    assert rt.main(["--write"], fetch=fetch, manifest=frozen.MANIFEST, out=out) == 1
    assert "go 1.26 1.26.10: upstream now lists a different SHA-256" in capsys.readouterr().err
    assert out.read_text() == before


def test_resolve_failure_exits_nonzero(tmp_path, capsys):
    out = tmp_path / "toolchains.yml"
    bodies = _upstreams()
    out.write_text(rt.dump_toolchains(rt.resolve(SEED, _fetch(bodies))))
    before = out.read_text()
    del bodies[rt.GO_RELEASES]
    assert rt.main(["--write"], fetch=_fetch(bodies), manifest=frozen.MANIFEST, out=out) == 1
    assert "::error::https://go.dev/dl/" in capsys.readouterr().err
    assert out.read_text() == before


def test_fetch_url_wraps_http_errors(monkeypatch):
    import urllib.error
    import urllib.request

    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 503, "Service Unavailable", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(rt.ResolutionError, match="HTTP 503"):
        rt.fetch_url("https://example.invalid/x")


def test_upstream_refresh_regenerates_after_resolving():
    lines = [ln.strip() for ln in (DOCKER / "pins" / "upstream-refresh.sh").read_text().splitlines()]
    steps = [ln for ln in lines if ln and not ln.startswith("#") and ("uv run" in ln or "python3" in ln)]
    assert steps == [
        "python3 docker/pins/resolve_latest.py --write",
        "uv run docker/pins/resolve_toolchains.py --write",
        "uv run docker/versions/generate.py",
        "uv run docker/pins/generate_catalog.py",
    ]
