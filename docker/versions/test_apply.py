import hashlib
import json
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
import yaml

import frozen
import generate as g
import manifest as mf
from lifecycle import core, publish
from lifecycle.adapters.go import GoAdapter
from lifecycle.adapters.python import PythonAdapter
from lifecycle.apply import ApplyError, apply_change, branch_name, edit_pins, parse_branch, pr_title, render_change
from lifecycle.core import Change, FamilyResult, TargetVersion
from lifecycle.publish import GhCli, GitCli, OpenPr, PublishError, sync_prs
from lifecycle.report import results_to_json
from lifecycle.runtime import AptIndex
from test_generate import repo  # noqa: F401  (fixture: a copy of every generated file)

HERE = Path(__file__).resolve().parent
ROOT = frozen.root()  # a repo tree whose generated files match SEED
FIXTURES = HERE / "fixtures"
TODAY = date(2026, 10, 21)
SEED = frozen.SEED  # the frozen test manifest, not the live one (#654)
rt = frozen.rt
TOOLCHAINS = g.TOOLCHAINS
CATALOG = frozen.CATALOG


def RUNTIME_314():
    """A vergil apt index publishing only the 3.14 runtime, as live today."""
    return AptIndex({("noble", "amd64"): frozenset({"vergil-python3.14"})})
RUN1 = "https://github.com/o/r/actions/runs/1"
RUN2 = "https://github.com/o/r/actions/runs/2"


def _family(m, key):
    (family,) = [f for f in m.families if f.key == key]
    return family


def _fixture_fetch(product, extra=()):
    def fetch(url):
        assert url == f"https://endoflife.date/api/{product}.json", url
        return json.dumps(list(extra) + json.loads((FIXTURES / f"endoflife-{product}.json").read_text())).encode()

    return fetch


GO_DEV = "https://go.dev/dl/?mode=json&include=all"


def _go_fetch(extra=()):
    """endoflife.date's `go` fixture plus the `extra` cycles, and go.dev's
    release list: its fixture plus each extra cycle's `latest` release, so every
    cycle is installable."""
    endoflife = _fixture_fetch("go", extra)

    def fetch(url):
        if url != GO_DEV:
            return endoflife(url)
        listing = json.loads((FIXTURES / "godev-releases.json").read_text())
        for cycle in extra:
            version = f"go{cycle['latest']}"
            listing.insert(0, {"version": version, "stable": True, "files": [
                {"filename": f"{version}.linux-{a}.tar.gz", "os": "linux", "arch": a, "kind": "archive",
                 "sha256": "a" * 64}
                for a in ("amd64", "arm64")
            ]})
        return json.dumps(listing).encode()

    return fetch


def _adapters(go_extra=()):
    return {
        "python": PythonAdapter(
            fetch=_fixture_fetch("python"), built_series=set, runtime_index=RUNTIME_314
        ),
        "go": GoAdapter(fetch=_go_fetch(go_extra)),
    }


def _pr_results(m=SEED, today=TODAY, go_extra=()):
    """Python and go checked from the fixtures, every other family in sync."""
    adapters = _adapters(go_extra)
    pr_only = mf.Manifest(families=tuple(f for f in m.families if f.key in adapters))
    checked = {r.family: r for r in core.run(pr_only, adapters, today)}
    return [checked.get(f.key, FamilyResult(f.key, (), None)) for f in m.families]


def _versions(m, key):
    return [v.version for v in _family(m, key).versions]


# --- the toolchain upstreams (epic vergil-project/.github#1095, Task 2b) ----------------------


def _no_fetch(url):
    """The fetch of a change that resolves no toolchain pin: any call fails the test."""
    raise AssertionError(f"unexpected toolchain upstream fetch: {url}")


def _h(label):
    return hashlib.sha256(label.encode()).hexdigest()


class Upstreams:
    """A fake toolchain-upstream fetch: canned bodies keyed by URL. Any other
    URL fails as `rt.fetch_url` does on a 404 (ResolutionError). Records each
    URL asked, in order."""

    def __init__(self, *bodies):
        self.bodies = {}
        for b in bodies:
            self.bodies |= b
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        if url not in self.bodies:
            raise rt.ResolutionError(f"{url}: HTTP 404 Not Found")
        return self.bodies[url].encode()


def _rust_channel(version):
    series = version.rsplit(".", 1)[0]
    return {rt.RUST_CHANNEL.format(series=series): f'[pkg.rust]\nversion = "{version} (0123456789 2026-10-15)"\n'}


def _rustup(version):
    bodies = {rt.RUSTUP_RELEASE: f"version = '{version}'\n"}
    for arch, triple in rt.RUSTUP_TRIPLES.items():
        bodies[rt.RUSTUP_INIT_SHA256.format(version=version, triple=triple)] = f"{_h(version + arch)}  *rustup-init\n"
    return bodies


def _pbs(release, *versions):
    feed = f'<feed><entry><link href="https://github.com/astral-sh/python-build-standalone/releases/tag/{release}"/></entry></feed>'
    sums = "".join(f"{_h(v + a)}  {rt.pbs_asset(v, release, a)}\n" for v in versions for a in rt.ARCHES)
    return {rt.PBS_RELEASES_FEED: feed, rt.PBS_DOWNLOAD.format(release=release, name="SHA256SUMS"): sums}


def _go(*versions):
    return {rt.GO_RELEASES: json.dumps([
        {"version": f"go{v}", "stable": True, "files": [
            {"filename": f"go{v}.linux-{a}.tar.gz", "os": "linux", "arch": a, "kind": "archive", "sha256": _h(v + a)}
            for a in rt.ARCHES
        ]}
        for v in versions
    ])}


def _pin(version, release=None, hashed=True):
    return rt.Pin(version, {a: _h(version + a) for a in rt.ARCHES} if hashed else None, release)


def rust_pr_fixture(tmp_path):
    """Rust under `automation: "pr"` at 1.99/1.98, pinned to 1.99.0/1.98.0, on
    a frozen repo tree rendered from it: (manifest, pins, root). The pins are
    exactly what the manifest requires (every other series as frozen.PINS has
    it), as check_pins.py holds the real base."""
    rust = replace(
        _family(SEED, "rust"),
        automation="pr",
        versions=tuple(mf.ManifestVersion(v, None, None, True, None) for v in ("1.99", "1.98")),
    )
    m = replace(SEED, families=tuple(rust if f.key == "rust" else f for f in SEED.families))
    required = rt.required_series(m)
    pins = replace(
        frozen.PINS,
        series={
            **{key: {s: frozen.PINS.series[key][s] for s in required[key]} for key in required if key != "rust"},
            "rust": {"1.99": rt.Pin("1.99.0"), "1.98": rt.Pin("1.98.0")},
        },
    )
    assert rt.consistency_errors(m, pins) == []
    root = frozen.make_repo(tmp_path / "repo")
    (root / g.MANIFEST).write_text(mf.dump_manifest(m))
    (root / TOOLCHAINS).write_text(rt.dump_toolchains(pins))
    frozen.render_tree(root, m, pins)
    return m, pins, root


def _with_rust(pins, series, pin):
    """`pins` with `pin` added for rust `series`."""
    return replace(pins, series={**pins.series, "rust": {**pins.series["rust"], series: pin}})


def _tree(root):
    return {p: p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _parsed_pins(files):
    return rt.parse_toolchains(yaml.safe_load(files[TOOLCHAINS]))


ADD_RUST_1_100 = (Change("rust", "add", "1.100", ""), TargetVersion("1.100", date(2026, 11, 26), None, True))


def test_add_writes_the_new_series_pin(tmp_path):
    m, pins, root = rust_pr_fixture(tmp_path)
    fetch = Upstreams(_rust_channel("1.100.0"))
    files = render_change(m, *ADD_RUST_1_100, root, fetch=fetch)
    assert _parsed_pins(files).series["rust"] == {"1.100": rt.Pin("1.100.0"), **pins.series["rust"]}
    text = files[TOOLCHAINS]
    assert text.index('"1.100":') < text.index('"1.99":') < text.index('"1.98":')
    assert fetch.asked == [rt.RUST_CHANNEL.format(series="1.100")]
    include = json.loads(files[g.MATRIX_JSON])["include"]
    (entry,) = [e for e in include if e["language"] == "rust" and e["version"] == "1.100"]
    assert entry["build-args"]["RUST_VERSION"] == "1.100"
    assert entry["build-args"]["TOOLCHAIN_VERSION"] == "1.100.0"


def test_add_does_not_rebump_other_series(tmp_path):
    m, pins, root = rust_pr_fixture(tmp_path)
    # Upstream has newer patches of 1.99 and 1.98: the add PR leaves them to
    # the daily refresh.
    fetch = Upstreams(_rust_channel("1.100.0"), _rust_channel("1.99.3"), _rust_channel("1.98.2"))
    files = render_change(m, *ADD_RUST_1_100, root, fetch=fetch)
    assert files[TOOLCHAINS] == rt.dump_toolchains(_with_rust(pins, "1.100", rt.Pin("1.100.0")))
    assert rt.changes(pins, _parsed_pins(files)) == ["added rust 1.100: 1.100.0"]


def test_add_writes_a_missing_tool_pin_only(tmp_path):
    m, pins, root = rust_pr_fixture(tmp_path)
    # The base pins rustup-init: it is kept, never re-resolved.
    fetch = Upstreams(_rust_channel("1.100.0"), _rustup("1.30.0"))
    files = render_change(m, *ADD_RUST_1_100, root, fetch=fetch)
    assert _parsed_pins(files).tools == pins.tools
    assert rt.RUSTUP_RELEASE not in fetch.asked
    # A base without it: the add resolves it.
    after = apply_change(m, *ADD_RUST_1_100)
    fetch = Upstreams(_rust_channel("1.100.0"), _rustup("1.30.0"))
    edited = edit_pins(after, replace(pins, tools={}), fetch)
    assert edited.tools == {"rustup-init": rt.Pin("1.30.0", {a: _h("1.30.0" + a) for a in rt.ARCHES})}
    assert rt.RUSTUP_RELEASE in fetch.asked


def test_drop_removes_an_orphaned_pin(tmp_path):
    two = replace(_family(SEED, "go"), versions=tuple(mf.ManifestVersion(v, None, None, True, None) for v in ("1.27", "1.26")))
    m = replace(SEED, families=tuple(two if f.key == "go" else f for f in SEED.families))
    base = replace(frozen.PINS, series={**frozen.PINS.series, "go": {"1.27": _pin("1.27.3"), "1.26": _pin("1.26.10")}})
    edited = edit_pins(apply_change(m, Change("go", "drop", "1.26", "")), base, _no_fetch)
    assert edited.series["go"] == {"1.27": _pin("1.27.3")}
    # A rust drop on a rendered tree removes the pin from both toolchains.yml
    # and the catalog.
    m, pins, root = rust_pr_fixture(tmp_path)
    files = render_change(m, Change("rust", "drop", "1.98", ""), None, root, fetch=_no_fetch)
    assert rt.changes(pins, _parsed_pins(files)) == ["removed rust 1.98: 1.98.0"]
    assert "| rust | 1.98 |" in (root / CATALOG).read_text()
    assert "| rust | 1.98 |" not in files[CATALOG]


def test_drop_keeps_a_pin_core_needs(tmp_path):
    # The frozen manifest's core.node is 22, which the ts-node 22 series shares.
    m, pins, root = rust_pr_fixture(tmp_path)
    assert m.core.node == "22" and "22" in pins.series["node"]
    files = render_change(m, Change("ts-node", "drop", "22", ""), None, root, fetch=_no_fetch)
    assert _versions(mf.parse_manifest(yaml.safe_load(files[g.MANIFEST])), "ts-node") == ["24"]
    assert TOOLCHAINS not in files and CATALOG not in files
    assert edit_pins(apply_change(m, Change("ts-node", "drop", "22", "")), pins, _no_fetch) == pins


def test_unresolvable_pin_is_apply_error(tmp_path):
    m, pins, root = rust_pr_fixture(tmp_path)
    with pytest.raises(ApplyError, match=r"^rust 1\.100: cannot resolve its toolchain pin: .*channel-rust-1\.100\.toml"):
        render_change(m, *ADD_RUST_1_100, root, fetch=Upstreams())
    # The error names the manifest family (ts-node), never the toolchain key (node).
    add_26 = (Change("ts-node", "add", "26", ""), TargetVersion("26", date(2026, 10, 28), None, True))
    with pytest.raises(ApplyError, match=r"^ts-node 26: cannot resolve its toolchain pin: ") as raised:
        render_change(m, *add_26, root, fetch=Upstreams())
    assert "'node'" not in str(raised.value)
    # A missing tool pin that cannot be resolved names the family it serves.
    with pytest.raises(ApplyError, match=r"^rust: cannot resolve the rustup-init pin: "):
        edit_pins(apply_change(m, *ADD_RUST_1_100), replace(pins, tools={}), Upstreams(_rust_channel("1.100.0")))


def test_render_change_leaves_root_untouched(tmp_path):
    m, _, root = rust_pr_fixture(tmp_path)
    before = _tree(root)
    fetch = Upstreams(_rust_channel("1.100.0"))
    render_change(m, *ADD_RUST_1_100, root, fetch=fetch)
    render_change(m, Change("rust", "drop", "1.98", ""), None, root, fetch=fetch)
    assert _tree(root) == before


def test_catalog_in_pr_files(tmp_path):
    m, _, root = rust_pr_fixture(tmp_path)
    files = render_change(m, *ADD_RUST_1_100, root, fetch=Upstreams(_rust_channel("1.100.0")))
    assert "| rust | 1.100 | 1.100.0 | — |" in files[CATALOG]
    # The rest of the catalog is the base's, byte for byte.
    added = set(files[CATALOG].splitlines()) - set((root / CATALOG).read_text().splitlines())
    assert added == {"| rust | 1.100 | 1.100.0 | — | — (rustup verifies) | — (rustup verifies) |"}
    # Writing the PR's files gives a tree every generator and the pin gate accept.
    for rel, content in files.items():
        (root / rel).write_text(content)
    assert g.main(["--check", "--root", str(root)]) == 0
    assert frozen.generate_catalog.render(root / "docker", rt.load_toolchains(root / TOOLCHAINS)) == files[CATALOG]
    assert rt.consistency_errors(mf.load_manifest(root / g.MANIFEST), rt.load_toolchains(root / TOOLCHAINS)) == []


def test_parse_branch_accepts_three_digit_minor():
    add = Change("rust", "add", "1.100", "")
    assert branch_name(add) == "lifecycle/rust-add-1.100"
    assert parse_branch("lifecycle/rust-add-1.100") == ("rust", "add", "1.100")
    assert parse_branch("lifecycle/rust-drop-1.99") == ("rust", "drop", "1.99")


# --- apply_change ---------------------------------------------------------------------


def test_apply_add_python_315_inserts_newest_first():
    target = TargetVersion("3.15", date(2026, 10, 9), date(2031, 10, 31), True)
    after = apply_change(SEED, Change("python", "add", "3.15", "GA 2026-10-09"), target)
    assert _versions(after, "python") == ["3.15", "3.14", "3.13", "3.12"]
    added = _family(after, "python").versions[0]
    assert added == mf.ManifestVersion("3.15", date(2026, 10, 9), date(2031, 10, 31), True, False)
    # Every other family is untouched.
    assert [f for f in after.families if f.key != "python"] == [f for f in SEED.families if f.key != "python"]


def test_apply_add_without_runtime_records_null():
    target = TargetVersion("1.27", date(2026, 8, 19), None, True)
    after = apply_change(SEED, Change("go", "add", "1.27", ""), target)
    assert _versions(after, "go") == ["1.27", "1.26"]
    assert _family(after, "go").versions[0].runtime_published is None


def test_apply_add_in_the_middle_keeps_order():
    m = apply_change(SEED, Change("python", "drop", "3.13", ""))
    after = apply_change(m, Change("python", "add", "3.13", ""), TargetVersion("3.13", None, None, True))
    assert _versions(after, "python") == ["3.14", "3.13", "3.12"]


def test_apply_drop_removes_version():
    after = apply_change(SEED, Change("python", "drop", "3.12", "EOL reached"))
    assert _versions(after, "python") == ["3.14", "3.13"]


@pytest.mark.parametrize(
    "change, target, needle",
    [
        (Change("python", "add", "3.15", ""), None, "needs its target"),
        (Change("python", "add", "3.15", ""), TargetVersion("3.16", None, None, True), "needs its target"),
        (Change("python", "add", "3.15", ""), TargetVersion("3.15", None, None, False), "not installable"),
        (Change("python", "add", "3.15", ""), TargetVersion("3.15", None, core.EOL_DATE_UNKNOWN, True), "EOL"),
        (Change("python", "add", "3.14", ""), TargetVersion("3.14", None, None, True), "already lists"),
        (Change("python", "drop", "3.11", ""), None, "does not list"),
        (Change("go", "drop", "1.26", ""), None, "no versions"),
        (Change("python", "blocked", "3.15", ""), None, "reported, not applied"),
        (Change("ruby", "drop", "3.2", ""), None, "no such family"),
    ],
)
def test_apply_rejects_what_it_cannot_apply_exactly(change, target, needle):
    with pytest.raises(ApplyError, match=needle):
        apply_change(SEED, change, target)


# --- names -------------------------------------------------------------------------------


def test_branch_names_and_titles():
    add = Change("python", "add", "3.15", "")
    drop = Change("cpp-clang", "drop", "19", "")
    assert branch_name(add) == "lifecycle/python-add-3.15"
    assert branch_name(drop) == "lifecycle/cpp-clang-drop-19"
    assert parse_branch("lifecycle/python-add-3.15") == ("python", "add", "3.15")
    assert parse_branch("lifecycle/cpp-clang-drop-19") == ("cpp-clang", "drop", "19")
    for other in ("lifecycle/python-blocked-3.15", "upstream-refresh", "lifecycle/python-add-x"):
        assert parse_branch(other) is None
    assert pr_title(add, None) == "feat(versions): add python 3.15"
    assert pr_title(drop, date(2026, 9, 1)) == "feat(versions): drop cpp-clang 19 (EOL 2026-09-01)"
    assert pr_title(drop, None) == "feat(versions): drop cpp-clang 19 (EOL date unknown)"
    with pytest.raises(ApplyError, match="no pull request"):
        pr_title(Change("python", "eol_soon", "3.12", ""), None)


# --- regenerated files ---------------------------------------------------------------------


def test_apply_then_render_regenerates_all_files(repo):  # noqa: F811
    m = mf.load_manifest(repo / g.MANIFEST)
    target = TargetVersion("3.15", date(2026, 10, 9), date(2031, 10, 31), True)
    # testdata/toolchains.yml already pins python 3.15, so nothing is fetched.
    # It also pins go 1.27 and 1.28, which the frozen manifest does not list:
    # the edited pins are exactly what the edited manifest requires, so they go,
    # and toolchains.yml and the catalog change with them.
    files = render_change(m, Change("python", "add", "3.15", ""), target, repo, fetch=_no_fetch)
    assert set(files) == {
        g.MANIFEST,
        g.MATRIX_JSON,
        g.WINDOW_JSON,
        Path("docker/python/Dockerfile.template"),
        *g.DOC_TABLES,
        TOOLCHAINS,
        CATALOG,
    }
    for rel, content in files.items():
        assert (repo / rel).read_text() != content
        (repo / rel).write_text(content)
    assert g.main(["--check", "--root", str(repo)]) == 0
    assert _versions(mf.load_manifest(repo / g.MANIFEST), "python") == ["3.15", "3.14", "3.13", "3.12"]
    assert "ARG PYTHON_VERSION=3.15" in (repo / "docker/python/Dockerfile.template").read_text()
    include = json.loads((repo / g.MATRIX_JSON).read_text())["include"]
    args = {"PYTHON_VERSION": "3.15", **frozen.rt.build_args(frozen.PINS, "python", "3.15")}
    assert {"language": "python", "version": "3.15", "build-args": args, "parent": None, "depth": 0} in include


def test_render_drop_of_an_older_version_leaves_the_arg_default(repo):  # noqa: F811
    m = mf.load_manifest(repo / g.MANIFEST)
    files = render_change(m, Change("python", "drop", "3.12", ""), None, repo, fetch=_no_fetch)
    assert Path("docker/python/Dockerfile.template") not in files
    assert g.MANIFEST in files and g.MATRIX_JSON in files


# --- sync_prs: fakes ------------------------------------------------------------------------


class FakeGh:
    """An in-memory PR tracker implementing the PrClient protocol."""

    def __init__(self):
        self.prs = {}  # number -> dict(head, title, body, open, comments)
        self.calls = []
        self._next = 500

    def seed(self, head, title="old"):
        n = self._next
        self._next += 1
        self.prs[n] = {"head": head, "title": title, "body": "old", "open": True, "comments": []}
        return n

    def list_open_prs(self, head_prefix):
        self.calls.append(("list", head_prefix))
        return [OpenPr(n, p["head"]) for n, p in self.prs.items() if p["open"] and p["head"].startswith(head_prefix)]

    def create_pr(self, head, title, body):
        self.calls.append(("create", head))
        n = self.seed(head, title)
        self.prs[n]["body"] = body
        return n

    def update_pr(self, number, title, body):
        self.calls.append(("update", number))
        self.prs[number].update(title=title, body=body)

    def close_pr(self, number, comment):
        self.calls.append(("close", number))
        self.prs[number]["open"] = False
        self.prs[number]["comments"].append(comment)

    def open_prs(self):
        return {p["head"]: p for p in self.prs.values() if p["open"]}


class FakeGit:
    """A remote holding branch -> files; a push happens only on a change."""

    def __init__(self):
        self.branches = {}
        self.pushes = []

    def publish_branch(self, branch, files, message):
        snapshot = (message, dict(files))
        if self.branches.get(branch) == snapshot:
            return False
        self.branches[branch] = snapshot
        self.pushes.append(branch)
        return True


def _sync(gh, git, results, run_url=RUN1, m=SEED, adapters=None):
    sync_prs(
        results, gh, git, manifest=m, adapters=adapters or _adapters(), root=ROOT, run_url=run_url, fetch=_no_fetch
    )


# --- sync_prs: the pinned tests (plan Task 6) ---------------------------------------------------


def test_first_run_opens_one_pr_per_add():
    gh, git = FakeGh(), FakeGit()
    _sync(gh, git, _pr_results())
    prs = gh.open_prs()
    assert sorted(prs) == ["lifecycle/go-add-1.27", "lifecycle/python-add-3.15"]
    assert prs["lifecycle/python-add-3.15"]["title"] == "feat(versions): add python 3.15"
    assert prs["lifecycle/go-add-1.27"]["title"] == "feat(versions): add go 1.27"
    message, files = git.branches["lifecycle/python-add-3.15"]
    assert message == "feat(versions): add python 3.15"
    assert g.MANIFEST in files and g.WINDOW_JSON in files


def test_rerun_refreshes_existing_pr():
    gh, git = FakeGh(), FakeGit()
    results = _pr_results()
    _sync(gh, git, results, RUN1)
    (n,) = [k for k, p in gh.prs.items() if p["head"] == "lifecycle/python-add-3.15"]
    assert len(git.pushes) == 2

    _sync(gh, git, results, RUN2)
    assert [k for k, p in gh.prs.items() if p["head"] == "lifecycle/python-add-3.15"] == [n]
    assert len(gh.prs) == 2 and all(p["open"] for p in gh.prs.values())
    assert RUN2 in gh.prs[n]["body"] and RUN1 not in gh.prs[n]["body"]
    assert [c for c in gh.calls if c[0] == "create"] == [("create", "lifecycle/python-add-3.15"), ("create", "lifecycle/go-add-1.27")]
    assert ("update", n) in gh.calls
    # Same base, same change: the branch is not pushed again (no CI re-run).
    assert len(git.pushes) == 2


def test_rerun_after_the_base_moved_force_pushes_the_same_branch():
    gh, git = FakeGh(), FakeGit()
    _sync(gh, git, _pr_results())
    moved = apply_change(SEED, Change("python", "drop", "3.12", ""))
    _sync(gh, git, _pr_results(moved), m=moved)
    assert git.pushes.count("lifecycle/python-add-3.15") == 2
    assert [c[0] for c in gh.calls].count("create") == 2


def test_drop_pr_body_lists_go_case_followup():
    # Go 1.28 ships on 2027-02-09 and 1.26 reaches EOL the same day.
    go128 = {"cycle": "1.28", "releaseDate": "2027-02-09", "eol": False, "latest": "1.28.0", "lts": False}
    today = date(2027, 2, 20)
    m = apply_change(SEED, Change("go", "add", "1.27", ""), TargetVersion("1.27", date(2026, 8, 19), None, True))
    results = _pr_results(m, today=today, go_extra=[go128])
    by_family = {r.family: r for r in results}
    # endoflife.date gives 1.26 no EOL date in the fixture, so the drop is by the window rule.
    assert [(c.kind, c.version) for c in by_family["go"].changes] == [("add", "1.28"), ("drop", "1.26")]

    gh, git = FakeGh(), FakeGit()
    _sync(gh, git, results, m=m)
    prs = gh.open_prs()
    drop = prs["lifecycle/go-drop-1.26"]
    assert drop["title"] == "feat(versions): drop go 1.26 (EOL date unknown)"
    assert "- [ ] remove the `case go1.26*)` branch from `docker/go/Dockerfile.template`" in drop["body"]
    assert "- [ ] retire or update the `go-test-coverage` pin in `docker/pins/pins.yml`" in drop["body"]
    assert "https://endoflife.date/go" in drop["body"]
    _, files = git.branches["lifecycle/go-drop-1.26"]
    assert "1.26" not in [v.version for v in _family(mf.parse_manifest(__import__("yaml").safe_load(files[g.MANIFEST])), "go").versions]


def test_drop_title_uses_the_upstream_eol_date():
    results = _pr_results(today=date(2028, 11, 5))
    py = next(r for r in results if r.family == "python")
    assert ("drop", "3.12") in [(c.kind, c.version) for c in py.changes]
    gh, git = FakeGh(), FakeGit()
    _sync(gh, git, results)
    assert gh.open_prs()["lifecycle/python-drop-3.12"]["title"] == "feat(versions): drop python 3.12 (EOL 2028-10-31)"


def test_report_family_never_gets_pr():
    rust = FamilyResult("rust", (Change("rust", "add", "1.99", ""), Change("rust", "out_of_policy", "1.92", "")), None)
    results = [rust if r.family == "rust" else FamilyResult(r.family, (), None) for r in _pr_results()]
    gh, git = FakeGh(), FakeGit()
    _sync(gh, git, results)
    assert gh.prs == {} and git.pushes == []


# --- sync_prs: body, auto-merge ------------------------------------------------------------------


def test_add_pr_body():
    gh, git = FakeGh(), FakeGit()
    _sync(gh, git, _pr_results())
    body = gh.open_prs()["lifecycle/python-add-3.15"]["body"]
    assert "`add` for `python` 3.15" in body
    assert "GA 2026-10-09, EOL 2031-10-31" in body
    assert "https://endoflife.date/python" in body
    assert "`docs/site/docs/languages/python.md`" in body
    assert "**not** set to auto-merge" in body
    assert "Hold" not in body
    assert "`runtime_published: false`" in body
    assert "- `docker/versions/manifest.yml`" in body and "- `docker/versions/window.json`" in body
    assert "## Manual follow-ups\n\nNone." in body
    go_body = gh.open_prs()["lifecycle/go-add-1.27"]["body"]
    assert "runtime_published" not in go_body


def test_sync_never_touches_auto_merge():
    # Driven through the real gh client: a first run opens, a rerun refreshes,
    # and a stale PR is closed, yet no gh call ever merges or sets auto-merge.
    def gh_run(args, stdin):
        calls.append(args)
        if args[:2] == ["pr", "list"]:
            return json.dumps(listed)
        if args[:2] == ["pr", "create"]:
            n = 900 + len(listed)
            listed.append({"number": n, "headRefName": args[args.index("--head") + 1]})
            return f"https://github.com/o/r/pull/{n}\n"
        return ""

    calls, listed = [], [{"number": 1, "headRefName": "lifecycle/python-add-3.99"}]
    gh, git = GhCli("o/r", gh_run, base="develop"), FakeGit()
    _sync(gh, git, _pr_results())
    _sync(gh, git, _pr_results(), RUN2)
    kinds = [c[:2] for c in calls]
    assert ["pr", "create"] in kinds and ["pr", "edit"] in kinds and ["pr", "close"] in kinds
    assert ["pr", "merge"] not in kinds
    assert not [c for c in calls if any("auto" in a for a in c if a.startswith("--"))]


# --- sync_prs: stale PRs and failures --------------------------------------------------------------


def test_pr_no_longer_reported_is_closed():
    gh, git = FakeGh(), FakeGit()
    stale = gh.seed("lifecycle/python-add-3.14")
    other = gh.seed("feature/123-something")
    gone = gh.seed("lifecycle/ruby-drop-3.2")
    _sync(gh, git, _pr_results())
    assert gh.prs[stale]["comments"] == [f"no longer reported in run {RUN1}"]
    assert gh.prs[gone]["comments"] == [f"no longer reported in run {RUN1}"]
    assert gh.prs[other]["open"]


def test_failing_family_keeps_its_prs_and_opens_none():
    gh, git = FakeGh(), FakeGit()
    kept = gh.seed("lifecycle/python-add-3.15")
    results = [
        FamilyResult("python", (), "SourceError: HTTP 503") if r.family == "python" else r for r in _pr_results()
    ]
    _sync(gh, git, results)
    assert gh.prs[kept]["open"] and gh.prs[kept]["body"] == "old"
    assert "lifecycle/python-add-3.15" not in git.branches
    assert "lifecycle/go-add-1.27" in gh.open_prs()


def test_sync_prs_rejects_bad_input():
    gh, git = FakeGh(), FakeGit()
    with pytest.raises(PublishError, match="run URL"):
        _sync(gh, git, [], run_url="")
    with pytest.raises(PublishError, match="'ruby'"):
        _sync(gh, git, [FamilyResult("ruby", (), None)])
    with pytest.raises(PublishError, match="two results"):
        _sync(gh, git, [FamilyResult("go", (), None), FamilyResult("go", (), None)])
    with pytest.raises(PublishError, match="no lifecycle adapter"):
        _sync(gh, git, _pr_results(), adapters={"python": _adapters()["python"]})


def test_sync_prs_fails_loud_on_an_inapplicable_change():
    # The manifest already lists 3.15: the add cannot be applied exactly.
    m = apply_change(SEED, Change("python", "add", "3.15", ""), TargetVersion("3.15", None, None, True))
    with pytest.raises(PublishError, match="python add 3.15: .*already lists"):
        _sync(FakeGh(), FakeGit(), _pr_results(), m=m)


def test_one_failing_change_does_not_block_the_others_or_close_its_pr():
    # Go has one version; dropping it alone cannot be applied.
    results = [
        FamilyResult("go", (Change("go", "drop", "1.26", "EOL reached"),), None) if r.family == "go" else r
        for r in _pr_results()
    ]
    gh, git = FakeGh(), FakeGit()
    existing = gh.seed("lifecycle/go-drop-1.26")
    with pytest.raises(PublishError, match="go drop 1.26: .*no versions"):
        _sync(gh, git, results)
    assert "lifecycle/python-add-3.15" in gh.open_prs()
    assert gh.prs[existing]["open"] and gh.prs[existing]["comments"] == []


def test_sync_prs_add_without_target_fails_loud():
    results = [
        replace(r, target=()) if r.family == "python" else r for r in _pr_results()
    ]
    with pytest.raises(PublishError, match="needs its target"):
        _sync(FakeGh(), FakeGit(), results)


# --- main --prs -------------------------------------------------------------------------------------


def _prs_argv(results):
    """`--prs` on the frozen manifest and the repo tree that matches it (#654)."""
    return ["--results", str(results), "--run-url", RUN1, "--prs",
            "--manifest", str(frozen.MANIFEST), "--root", str(ROOT)]


def test_main_prs_mode(tmp_path):
    path = tmp_path / "results.json"
    path.write_text(results_to_json(_pr_results(), TODAY))
    gh, git = FakeGh(), FakeGit()
    rc = publish.main(_prs_argv(path), gh=gh, git=git, adapters=_adapters(), fetch=_no_fetch)
    assert rc == 0
    assert sorted(gh.open_prs()) == ["lifecycle/go-add-1.27", "lifecycle/python-add-3.15"]


def test_main_prs_needs_base(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    path = tmp_path / "results.json"
    path.write_text(results_to_json([], TODAY))
    assert publish.main(["--results", str(path), "--run-url", RUN1, "--prs"]) == 1
    assert "--prs needs --base" in capsys.readouterr().err


def test_main_prs_failure_exits_1(tmp_path, capsys):
    path = tmp_path / "results.json"
    path.write_text(results_to_json(_pr_results(), TODAY))

    class BrokenGit:
        def publish_branch(self, branch, files, message):
            raise PublishError("git push failed (exit 1): permission denied")

    rc = publish.main(_prs_argv(path), gh=FakeGh(), git=BrokenGit(), adapters=_adapters(), fetch=_no_fetch)
    assert rc == 1
    assert "permission denied" in capsys.readouterr().err


def test_main_prs_default_clients(tmp_path, monkeypatch):
    built = {}

    class Gh(FakeGh):
        def __init__(self, repo, runner=None, base=None):
            super().__init__()
            built["gh"] = (repo, base)

    class Git(FakeGit):
        def __init__(self, root):
            super().__init__()
            built["git"] = root

    monkeypatch.setattr(publish, "GhCli", Gh)
    monkeypatch.setattr(publish, "GitCli", Git)
    path = tmp_path / "results.json"
    path.write_text(results_to_json([FamilyResult(f.key, (), None) for f in SEED.families], TODAY))
    rc = publish.main(["--results", str(path), "--run-url", RUN1, "--prs", "--repo", "o/r", "--base", "develop",
                      "--manifest", str(frozen.MANIFEST)])
    assert rc == 0
    assert built == {"gh": ("o/r", "develop"), "git": publish.REPO_ROOT}


# --- GhCli PR commands ---------------------------------------------------------------------------------


class Recorder:
    def __init__(self, *outputs):
        self.calls = []
        self._outputs = list(outputs)

    def __call__(self, args, stdin):
        self.calls.append((args, stdin))
        return self._outputs.pop(0) if self._outputs else ""


def test_ghcli_list_open_prs_filters_by_prefix():
    out = json.dumps([{"number": 1, "headRefName": "lifecycle/python-add-3.15"}, {"number": 2, "headRefName": "bot/x"}])
    rec = Recorder(out)
    assert GhCli("o/r", rec, base="develop").list_open_prs("lifecycle/") == [OpenPr(1, "lifecycle/python-add-3.15")]
    args, _ = rec.calls[0]
    assert args[:2] == ["pr", "list"] and ["--base", "develop"] == args[args.index("--base"):args.index("--base") + 2]


@pytest.mark.parametrize("out", ["nope", json.dumps([{"number": 1}])])
def test_ghcli_list_open_prs_rejects_malformed(out):
    with pytest.raises(PublishError, match="malformed"):
        GhCli("o/r", Recorder(out), base="develop").list_open_prs("lifecycle/")


def test_ghcli_list_open_prs_refuses_a_full_page(monkeypatch):
    monkeypatch.setattr(publish, "LIST_LIMIT", 1)
    with pytest.raises(PublishError, match="incomplete"):
        GhCli("o/r", Recorder(json.dumps([{"number": 1, "headRefName": "a"}])), base="d").list_open_prs("lifecycle/")


def test_ghcli_pr_methods_need_a_base():
    with pytest.raises(PublishError, match="base branch"):
        GhCli("o/r", Recorder()).create_pr("h", "t", "b")


def test_ghcli_create_update_close_pr():
    rec = Recorder("https://github.com/o/r/pull/77\n")
    cli = GhCli("o/r", rec, base="develop")
    assert cli.create_pr("lifecycle/python-add-3.15", "feat(versions): add python 3.15", "body") == 77
    cli.update_pr(77, "t2", "body2")
    cli.close_pr(78, "no longer reported in run x")
    assert rec.calls[0] == (
        ["pr", "create", "--repo", "o/r", "--base", "develop", "--head", "lifecycle/python-add-3.15",
         "--title", "feat(versions): add python 3.15", "--body-file", "-"],
        "body",
    )
    assert rec.calls[1] == (["pr", "edit", "77", "--repo", "o/r", "--title", "t2", "--body-file", "-"], "body2")
    assert rec.calls[2] == (
        ["pr", "close", "78", "--repo", "o/r", "--delete-branch", "--comment", "no longer reported in run x"], None
    )


def test_ghcli_create_pr_without_url_fails():
    with pytest.raises(PublishError, match="no PR URL"):
        GhCli("o/r", Recorder("oops"), base="develop").create_pr("h", "t", "b")


# --- GitCli, against a real local repository and remote ---------------------------------------------


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def checkout(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    _git(tmp_path, "init", "-q", "-b", "develop", str(work))
    _git(work, "config", "user.name", "t")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "commit.gpgsign", "false")
    (work / "docker/versions").mkdir(parents=True)
    (work / "docker/versions/manifest.yml").write_text("base\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "base")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "-q", "origin", "develop")
    return work, remote


def test_gitcli_pushes_once_then_only_on_change(checkout):
    work, remote = checkout
    git = GitCli(work)
    files = {Path("docker/versions/manifest.yml"): "added\n", Path("docker/new/file.txt"): "new\n"}
    assert git.publish_branch("lifecycle/python-add-3.15", files, "feat(versions): add python 3.15") is True
    first = _git(remote, "rev-parse", "refs/heads/lifecycle/python-add-3.15")
    assert _git(remote, "show", f"{first}:docker/versions/manifest.yml") == "added"
    assert _git(remote, "log", "-1", "--format=%an <%ae>|%s", first) == f"{publish.BOT_NAME} <{publish.BOT_EMAIL}>|feat(versions): add python 3.15"
    assert _git(remote, "rev-parse", f"{first}^") == _git(work, "rev-parse", "HEAD")

    # A rerun on the same base builds the identical commit: nothing to push.
    assert git.publish_branch("lifecycle/python-add-3.15", files, "feat(versions): add python 3.15") is False
    # The main checkout and its worktree list are untouched.
    assert _git(work, "status", "--porcelain") == ""
    assert len(_git(work, "worktree", "list").splitlines()) == 1

    # Changed content (or a moved base) force-pushes the same branch.
    files[Path("docker/versions/manifest.yml")] = "added again\n"
    assert git.publish_branch("lifecycle/python-add-3.15", files, "feat(versions): add python 3.15") is True
    second = _git(remote, "rev-parse", "refs/heads/lifecycle/python-add-3.15")
    assert second != first and _git(remote, "rev-parse", f"{second}^") == _git(work, "rev-parse", "HEAD")


def test_gitcli_refuses_a_change_that_writes_nothing(checkout):
    work, _ = checkout
    git = GitCli(work)
    with pytest.raises(PublishError, match="writes nothing new"):
        git.publish_branch("lifecycle/x-add-1", {Path("docker/versions/manifest.yml"): "base\n"}, "m")
    with pytest.raises(PublishError, match="nothing to commit"):
        git.publish_branch("lifecycle/x-add-1", {}, "m")
    assert len(_git(work, "worktree", "list").splitlines()) == 1


def test_gitcli_push_failure_raises(checkout, tmp_path):
    work, _ = checkout
    git = GitCli(work, remote=str(tmp_path / "missing.git"))
    with pytest.raises(PublishError, match="git"):
        git.publish_branch("lifecycle/x-add-1", {Path("docker/versions/manifest.yml"): "new\n"}, "m")


def test_apply_keeps_toolchains_and_base_parent():
    # Review Focus 1 (epic vergil-project/.github#607): a lifecycle PR rewrites
    # manifest.yml from apply_change's result, so it must keep every section it
    # does not change, not only the families.
    toolchain = mf.Toolchain("pkg-ubuntu", "UBUNTU_VERSION", ("26.04", "24.04"))
    m = replace(SEED, toolchains=(toolchain,), base_parent=mf.Parent("pkg-ubuntu", "24.04"))
    after = apply_change(m, Change("python", "drop", "3.12", "EOL reached"))
    assert after.toolchains == (toolchain,)
    assert after.base_parent == mf.Parent("pkg-ubuntu", "24.04")
    assert mf.parse_manifest(yaml.safe_load(mf.dump_manifest(after))) == after


def test_apply_change_keeps_core():
    m = replace(SEED, core=mf.Core(python="3.16", node="24"))
    for change, target in (
        (Change("python", "drop", "3.12", "EOL reached"), None),
        (Change("python", "add", "3.15", ""), TargetVersion("3.15", None, None, True)),
    ):
        after = apply_change(m, change, target)
        assert after.core == mf.Core(python="3.16", node="24")
        assert mf.parse_manifest(yaml.safe_load(mf.dump_manifest(after))) == after


def test_render_add_resolves_a_missing_toolchain_pin(repo):  # noqa: F811
    # An add of a series toolchains.yml does not pin resolves it through the
    # injected fetch (it used to fail the change); an unresolvable pin is the
    # ApplyError of test_unresolvable_pin_is_apply_error.
    m = mf.load_manifest(repo / g.MANIFEST)
    fetch = Upstreams(_pbs("20261101", "3.16.0"))
    files = render_change(m, Change("python", "add", "3.16", ""), TargetVersion("3.16", None, None, True), repo, fetch=fetch)
    assert _parsed_pins(files).series["python"]["3.16"] == _pin("3.16.0", release="20261101")
    include = json.loads(files[g.MATRIX_JSON])["include"]
    (entry,) = [e for e in include if e["language"] == "python" and e["version"] == "3.16"]
    assert entry["build-args"]["TOOLCHAIN_VERSION"] == "3.16.0"
    assert entry["build-args"]["PBS_RELEASE"] == "20261101"
