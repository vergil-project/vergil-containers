from datetime import date

import pytest
import yaml

import frozen
import manifest as mf

# The frozen test manifest (#654), not the live one: these tests must not break
# when a lifecycle PR adds or drops a real version.
MANIFEST = frozen.MANIFEST

# The publish matrix (image suffix, version, build-arg) the frozen manifest
# seeds: the `include:` list cd-docker-publish.yml carried at the start of the
# manifest work, less Ruby and GCC 13 (dropped in #619).
CURRENT_MATRIX = [
    ("python", "3.12", "PYTHON_VERSION"),
    ("python", "3.13", "PYTHON_VERSION"),
    ("python", "3.14", "PYTHON_VERSION"),
    ("java", "17", "JDK_VERSION"),
    ("java", "21", "JDK_VERSION"),
    ("go", "1.26", "GO_VERSION"),
    ("rust", "1.92", "RUST_VERSION"),
    ("rust", "1.93", "RUST_VERSION"),
    ("cpp-clang", "20", "CLANG_VERSION"),
    ("cpp-clang", "19", "CLANG_VERSION"),
    ("cpp-gcc", "14", "GCC_VERSION"),
    ("ts-node", "24", "NODE_MAJOR"),
    ("ts-node", "22", "NODE_MAJOR"),
]


def _family(**over):
    fam = {
        "key": "python",
        "language": "python",
        "token_prefix": "",
        "build_arg": "PYTHON_VERSION",
        "automation": "pr",
        "versions": [
            {"version": "3.14", "ga": None, "eol": None, "in_policy": True,
             "runtime_published": True},
            {"version": "3.13", "ga": None, "eol": None, "in_policy": True,
             "runtime_published": False},
        ],
    }
    fam.update(over)
    return fam


def _doc(*families):
    return {"schema": 1, "families": list(families) or [_family()]}


def _load(tmp_path, doc):
    p = tmp_path / "manifest.yml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False))
    return mf.load_manifest(p)


def test_load_manifest_seed_matches_current_matrix():
    m = mf.load_manifest(MANIFEST)
    triples = [(f.key, v.version, f.build_arg) for f in m.families for v in f.versions]
    assert sorted(triples) == sorted(CURRENT_MATRIX)
    assert len(triples) == len(set(triples))


def test_seed_runtime_published_and_policy():
    m = mf.load_manifest(MANIFEST)
    by_key = {f.key: f for f in m.families}
    python = {v.version: v.runtime_published for v in by_key["python"].versions}
    assert python == {"3.14": True, "3.13": False, "3.12": False}
    for f in m.families:
        assert all(v.in_policy for v in f.versions), f.key
        if f.key != "python":
            assert all(v.runtime_published is None for v in f.versions), f.key
    prefixes = {f.key: f.token_prefix for f in m.families}
    assert prefixes["cpp-clang"] == "clang-"
    assert prefixes["cpp-gcc"] == "gcc-"
    assert prefixes["ts-node"] == "node-"
    assert prefixes["python"] == ""


def test_load_manifest_rejects_unknown_key(tmp_path):
    with pytest.raises(mf.ManifestError, match=r"family 'python'.*unknown key.*'colour'"):
        _load(tmp_path, _doc(_family(colour="blue")))
    bad_version = _family()
    bad_version["versions"][0]["colour"] = "blue"
    with pytest.raises(mf.ManifestError, match=r"family 'python': versions\[0\].*'colour'"):
        _load(tmp_path, _doc(bad_version))


def test_rejects_missing_key(tmp_path):
    fam = _family()
    del fam["build_arg"]
    with pytest.raises(mf.ManifestError, match=r"family 'python'.*missing key.*'build_arg'"):
        _load(tmp_path, _doc(fam))


def test_rejects_duplicate_version(tmp_path):
    fam = _family()
    fam["versions"][1]["version"] = "3.14"
    with pytest.raises(mf.ManifestError, match=r"family 'python': versions: duplicate version '3.14'"):
        _load(tmp_path, _doc(fam))


def test_rejects_duplicate_family(tmp_path):
    with pytest.raises(mf.ManifestError, match=r"family 'python': key: duplicate"):
        _load(tmp_path, _doc(_family(), _family()))


def test_rejects_versions_not_newest_first(tmp_path):
    fam = _family()
    fam["versions"].reverse()
    with pytest.raises(mf.ManifestError, match=r"family 'python': versions must be newest first"):
        _load(tmp_path, _doc(fam))


def test_newest_first_is_semantic_not_lexical(tmp_path):
    fam = _family()
    fam["versions"][0]["version"] = "3.10"
    fam["versions"][1]["version"] = "3.9"
    m = _load(tmp_path, _doc(fam))
    assert [v.version for v in m.families[0].versions] == ["3.10", "3.9"]


def test_rejects_bad_automation(tmp_path):
    with pytest.raises(mf.ManifestError, match=r"family 'python': automation 'auto'"):
        _load(tmp_path, _doc(_family(automation="auto")))


@pytest.mark.parametrize(
    ("field", "value", "pattern"),
    [
        ("version", 3.14, r"versions\[0\]: version 3.14"),
        ("version", "3.14.1", r"versions\[0\]: version '3.14.1'"),
        ("in_policy", None, r"versions\[0\]: in_policy None"),
        ("runtime_published", "yes", r"versions\[0\]: runtime_published 'yes'"),
        ("eol", "soon", r"versions\[0\]: eol 'soon'"),
        ("ga", 2025, r"versions\[0\]: ga 2025"),
    ],
)
def test_rejects_bad_version_fields(tmp_path, field, value, pattern):
    fam = _family()
    fam["versions"][0][field] = value
    with pytest.raises(mf.ManifestError, match=r"family 'python': " + pattern):
        _load(tmp_path, _doc(fam))


@pytest.mark.parametrize(
    ("field", "value"),
    [("key", "Python"), ("language", "C++"), ("token_prefix", "clang"),
     ("build_arg", "python_version"), ("versions", [])],
)
def test_rejects_bad_family_fields(tmp_path, field, value):
    with pytest.raises(mf.ManifestError, match=field):
        _load(tmp_path, _doc(_family(**{field: value})))


def test_rejects_bad_top_level(tmp_path):
    with pytest.raises(mf.ManifestError, match="schema 2"):
        _load(tmp_path, {"schema": 2, "families": [_family()]})
    with pytest.raises(mf.ManifestError, match="families must be a non-empty list"):
        _load(tmp_path, {"schema": 1, "families": []})
    with pytest.raises(mf.ManifestError, match="unknown key"):
        _load(tmp_path, {"schema": 1, "families": [_family()], "extra": 1})
    p = tmp_path / "bad.yml"
    p.write_text("families: [")
    with pytest.raises(mf.ManifestError, match="not valid YAML"):
        mf.load_manifest(p)
    with pytest.raises(mf.ManifestError, match="cannot read"):
        mf.load_manifest(tmp_path / "absent.yml")


def test_dates_parse_from_yaml_and_strings(tmp_path):
    fam = _family()
    fam["versions"][0]["eol"] = date(2030, 10, 31)
    fam["versions"][0]["ga"] = "2025-10-07"
    m = _load(tmp_path, _doc(fam))
    v = m.families[0].versions[0]
    assert v.eol == date(2030, 10, 31)
    assert v.ga == date(2025, 10, 7)


def test_dump_roundtrip(tmp_path):
    fam = _family()
    fam["versions"][0]["eol"] = date(2030, 10, 31)
    fam["versions"][0]["ga"] = date(2025, 10, 7)
    clang = _family(key="cpp-clang", language="cpp", token_prefix="clang-",
                    build_arg="CLANG_VERSION", automation="report",
                    versions=[{"version": "20", "ga": None, "eol": None,
                               "in_policy": False, "runtime_published": None}])
    m = _load(tmp_path, _doc(fam, clang))
    p = tmp_path / "dumped.yml"
    p.write_text(mf.dump_manifest(m))
    assert mf.load_manifest(p) == m
    seed = mf.load_manifest(MANIFEST)
    p.write_text(mf.dump_manifest(seed))
    assert mf.load_manifest(p) == seed
