from datetime import date
from pathlib import Path

import pytest

import frozen
import manifest as mf
from lifecycle import core
from lifecycle.adapters.go import GoAdapter
from lifecycle.adapters.python import PythonAdapter
from lifecycle.core import Change, NotFoundError, SourceError
from lifecycle.runtime import AptIndex

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
TODAY = date(2026, 10, 21)
SEED = frozen.SEED  # the frozen test manifest, not the live one (#654)


def RUNTIME_314():
    """A vergil apt index publishing only the 3.14 runtime, as live today."""
    return AptIndex({("noble", "amd64"): frozenset({"vergil-python3.14"})})


def _family(key):
    (family,) = [f for f in SEED.families if f.key == key]
    return family


def _fixture_fetch(product):
    def fetch(url):
        assert url == f"https://endoflife.date/api/{product}.json", url
        return (FIXTURES / f"endoflife-{product}.json").read_bytes()

    return fetch


class Tags:
    """A fake Docker Hub: records each (image, tag) asked about."""

    def __init__(self, missing=()):
        self.missing = set(missing)
        self.asked = []

    def __call__(self, image, tag):
        self.asked.append((image, tag))
        return (image, tag) not in self.missing


def _kinds(changes):
    return [(c.kind, c.version) for c in changes]


# --- Python ----------------------------------------------------------------------


def test_python_target_from_fixture():
    tags = Tags()
    adapter = PythonAdapter(fetch=_fixture_fetch("python"), tag_exists=tags, runtime_index=RUNTIME_314)
    target = adapter.target(adapter.fetch(), TODAY)
    assert [t.version for t in target] == ["3.15", "3.14", "3.13", "3.12", "3.11"]
    assert all(t.installable for t in target)
    assert tags.asked == [("python", f"{v}-slim") for v in ("3.15", "3.14", "3.13", "3.12", "3.11")]
    assert target[0].ga == date(2026, 10, 9)
    assert target[0].eol == date(2031, 10, 31)


def test_python_classify_against_seed_is_add_315():
    adapter = PythonAdapter(fetch=_fixture_fetch("python"), tag_exists=Tags(), runtime_index=RUNTIME_314)
    changes = core.classify(_family("python"), adapter.target(adapter.fetch(), TODAY), TODAY, 90)
    assert _kinds(changes) == [("add", "3.15")]


def test_python_missing_slim_tag_is_blocked():
    adapter = PythonAdapter(
        fetch=_fixture_fetch("python"), tag_exists=Tags(missing={("python", "3.15-slim")}), runtime_index=RUNTIME_314
    )
    changes = core.classify(_family("python"), adapter.target(adapter.fetch(), TODAY), TODAY, 90)
    assert _kinds(changes) == [("blocked", "3.15")]


def test_python_default_tag_check_uses_docker_hub_through_the_fetcher():
    def fetch(url):
        if url.startswith("https://endoflife.date/"):
            return (FIXTURES / "endoflife-python.json").read_bytes()
        assert url.startswith("https://hub.docker.com/v2/namespaces/library/repositories/python/tags/"), url
        tag = url.rsplit("/", 1)[1]
        if tag == "3.11-slim":
            raise NotFoundError(f"{url}: HTTP 404")
        return ('{"name": "%s"}' % tag).encode()

    adapter = PythonAdapter(fetch=fetch, runtime_index=RUNTIME_314)
    target = adapter.target(adapter.fetch(), TODAY)
    assert {t.version: t.installable for t in target}["3.11"] is False
    assert {t.version: t.installable for t in target}["3.15"] is True


def test_python_has_no_extra_changes():
    assert PythonAdapter(fetch=_fixture_fetch("python")).extra_changes(Change("python", "drop", "3.12", "")) == []


# --- Go --------------------------------------------------------------------------


def test_go_target_from_fixture():
    tags = Tags()
    adapter = GoAdapter(fetch=_fixture_fetch("go"), tag_exists=tags)
    target = adapter.target(adapter.fetch(), TODAY)
    assert [t.version for t in target] == ["1.27", "1.26"]
    assert tags.asked == [("golang", "1.27"), ("golang", "1.26")]
    assert target[0].eol is None


def test_go_classify_against_seed_is_add_127():
    adapter = GoAdapter(fetch=_fixture_fetch("go"), tag_exists=Tags())
    changes = core.classify(_family("go"), adapter.target(adapter.fetch(), TODAY), TODAY, 90)
    assert _kinds(changes) == [("add", "1.27")]


def test_go_window_ignores_a_not_yet_released_cycle():
    adapter = GoAdapter(fetch=_fixture_fetch("go"), tag_exists=Tags())
    releases = adapter.fetch()
    releases.insert(0, core.UpstreamRelease("1.28", date(2027, 2, 9), None, False))
    assert [t.version for t in adapter.target(releases, TODAY)] == ["1.27", "1.26"]


def test_go_extra_changes_names_case_branch():
    follow_ups = GoAdapter().extra_changes(Change("go", "drop", "1.26", "EOL reached"))
    assert any("`case go1.26*)`" in f and "docker/go/Dockerfile.template" in f for f in follow_ups)
    assert any("`go-test-coverage`" in f and "docker/pins/pins.yml" in f for f in follow_ups)


def test_go_extra_changes_none_for_add_or_unreferenced_version():
    adapter = GoAdapter()
    assert adapter.extra_changes(Change("go", "add", "1.27", "")) == []
    assert adapter.extra_changes(Change("go", "drop", "1.2", "")) == []


def _fake_root(tmp_path, template, pins):
    (tmp_path / "docker/go").mkdir(parents=True)
    (tmp_path / "docker/pins").mkdir(parents=True)
    (tmp_path / "docker/go/Dockerfile.template").write_text(template)
    (tmp_path / "docker/pins/pins.yml").write_text(pins)
    return tmp_path


def test_go_extra_changes_matches_exact_version_only(tmp_path):
    root = _fake_root(
        tmp_path,
        "case x in \\\n  go1.260*) A ;; \\\n  go1.26*) B ;; \\\nesac\n",
        'pins:\n  a:\n    constraint: "==1 on Go 1.260"\n  b:\n    constraint: "==2 on Go 1.26.1"\n'
        '  c:\n    constraint: "==3 on Go 1.26, else latest"\n  d: {}\n',
    )
    follow_ups = GoAdapter(root=root).extra_changes(Change("go", "out_of_policy", "1.26", ""))
    assert follow_ups == [
        "remove the `case go1.26*)` branch from `docker/go/Dockerfile.template` (line 3)",
        "retire or update the `c` pin in `docker/pins/pins.yml` (constraint: ==3 on Go 1.26, else latest)",
    ]


@pytest.mark.parametrize(
    "template, pins, needle",
    [
        (None, "pins: {}\n", "cannot read docker/go/Dockerfile.template"),
        ("", None, "cannot read docker/pins/pins.yml"),
        ("", "pins: [\n", "cannot read docker/pins/pins.yml"),
        ("", "other: {}\n", "has no `pins` mapping"),
    ],
)
def test_go_extra_changes_fails_loud_on_unreadable_files(tmp_path, template, pins, needle):
    (tmp_path / "docker/go").mkdir(parents=True)
    (tmp_path / "docker/pins").mkdir(parents=True)
    if template is not None:
        (tmp_path / "docker/go/Dockerfile.template").write_text(template)
    if pins is not None:
        (tmp_path / "docker/pins/pins.yml").write_text(pins)
    with pytest.raises(SourceError, match=needle):
        GoAdapter(root=tmp_path).extra_changes(Change("go", "drop", "1.26", ""))


def test_go_fetch_failure_becomes_family_error():
    def fetch(url):
        raise SourceError(f"{url}: HTTP 503")

    m = mf.Manifest(families=(_family("python"), _family("go")))
    adapters = {
        "python": PythonAdapter(fetch=_fixture_fetch("python"), tag_exists=Tags(), runtime_index=RUNTIME_314),
        "go": GoAdapter(fetch=fetch, tag_exists=Tags()),
    }
    python, go = core.run(m, adapters, TODAY)
    assert _kinds(python.changes) == [("add", "3.15")]
    assert go.changes == ()
    assert "https://endoflife.date/api/go.json: HTTP 503" in go.error
