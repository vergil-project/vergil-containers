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
# manifest work, less Ruby and GCC 13 (dropped in #619) and the family dropped
# in vergil-project/.github#952.
CURRENT_MATRIX = [
    ("python", "3.12", "PYTHON_VERSION"),
    ("python", "3.13", "PYTHON_VERSION"),
    ("python", "3.14", "PYTHON_VERSION"),
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


# --- Manifest parents (vergil-containers#773, epic vergil-project/.github#213 T7b) ---
#
# No entry of the real manifest names a parent yet (epic vergil-project/.github#649
# sets the first ones), so these synthetic fixtures are the only exercise of a
# parent and of depths 1 and 2.


def _one(key, version="1", **over):
    return _family(key=key, language=key.replace("-", ""), build_arg=key.replace("-", "_").upper() + "_VERSION",
                   versions=[{"version": version, "ga": None, "eol": None, "in_policy": True,
                              "runtime_published": None}], **over)


def _tree_doc():
    """`pkg-ubuntu` (no parent) <- `base` <- `python`: depths 0, 1 and 2."""
    doc = _doc(_family(parent={"name": "base", "version": "latest"}), _one("pkg-ubuntu", "24.04"))
    doc["base"] = {"parent": {"name": "pkg-ubuntu", "version": "24.04"}}
    return doc


def test_no_parent_is_depth_zero(tmp_path):
    m = _load(tmp_path, _doc(_family(), _one("go")))
    assert all(f.parent is None for f in m.families)
    assert m.base_parent is None
    assert mf.entry_depths(m) == {"python": 0, "go": 0, "base": 0}


def test_parent_depth_emitted(tmp_path):
    m = _load(tmp_path, _tree_doc())
    assert m.base_parent == mf.Parent(name="pkg-ubuntu", version="24.04")
    assert m.families[0].parent == mf.Parent(name="base", version="latest")
    assert mf.entry_depths(m) == {"pkg-ubuntu": 0, "base": 1, "python": 2}


def test_parent_missing_refused(tmp_path):
    with pytest.raises(mf.ManifestError, match=r"family 'python': parent: no manifest entry 'rhel'"):
        _load(tmp_path, _doc(_family(parent={"name": "rhel", "version": "9"})))
    # The entry exists, but not at that version.
    with pytest.raises(mf.ManifestError, match=r"family 'python': parent: 'go' has no version '9'"):
        _load(tmp_path, _doc(_family(parent={"name": "go", "version": "9"}), _one("go")))
    doc = _doc()
    doc["base"] = {"parent": {"name": "pkg-ubuntu", "version": "24.04"}}
    with pytest.raises(mf.ManifestError, match=r"base: parent: no manifest entry 'pkg-ubuntu'"):
        _load(tmp_path, doc)


def test_parent_cycle_refused(tmp_path):
    doc = _doc(_family(parent={"name": "go", "version": "1"}),
               _one("go", parent={"name": "python", "version": "3.14"}))
    with pytest.raises(mf.ManifestError, match=r"family 'python': parent: cycle python -> go -> python"):
        _load(tmp_path, doc)
    with pytest.raises(mf.ManifestError, match=r"family 'python': parent: cycle python -> python"):
        _load(tmp_path, _doc(_family(parent={"name": "python", "version": "3.13"})))


def test_depth_over_max_refused(tmp_path):
    doc = _tree_doc()
    doc["families"].append(_one("lint", parent={"name": "python", "version": "3.14"}))
    with pytest.raises(mf.ManifestError, match=r"family 'lint': parent: depth 3 exceeds the maximum of 2"):
        _load(tmp_path, doc)


@pytest.mark.parametrize("parent", [
    "base", {"name": "base"}, {"name": "base", "version": "latest", "tag": "x"},
    {"name": 1, "version": "latest"}, {"name": "base", "version": 3},
])
def test_bad_parent_shape_refused(tmp_path, parent):
    with pytest.raises(mf.ManifestError, match=r"family 'python': parent"):
        _load(tmp_path, _doc(_family(parent=parent)))


@pytest.mark.parametrize("base", ["x", {"colour": "blue"}, None])
def test_bad_base_section_refused(tmp_path, base):
    doc = _doc()
    doc["base"] = base
    with pytest.raises(mf.ManifestError, match=r"^base"):
        _load(tmp_path, doc)


def test_family_may_not_be_keyed_base(tmp_path):
    with pytest.raises(mf.ManifestError, match=r"family 'base': key: 'base' is reserved"):
        _load(tmp_path, _doc(_one("base")))


def test_dataclass_manifest_is_checked_too():
    # A Manifest built in code, not loaded, gets the same parent checks.
    fam = mf.Family("python", "python", "", "PYTHON_VERSION", "pr",
                    (mf.ManifestVersion("3.14", None, None, True, None),), parent=mf.Parent("rhel", "9"))
    with pytest.raises(mf.ManifestError, match=r"no manifest entry 'rhel'"):
        mf.entry_depths(mf.Manifest((fam,)))


def test_dump_roundtrip_with_parents(tmp_path):
    m = _load(tmp_path, _tree_doc())
    p = tmp_path / "dumped.yml"
    p.write_text(mf.dump_manifest(m))
    assert mf.load_manifest(p) == m
    # A manifest with no parent dumps no parent or base section.
    seed = mf.load_manifest(MANIFEST)
    assert "  parent:" not in mf.dump_manifest(seed)
    assert "\nbase:" not in mf.dump_manifest(seed)
