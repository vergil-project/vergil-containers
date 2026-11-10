"""Native per-arch build and stitch in .github/workflows/cd-docker-publish.yml
(vergil-containers#515, epic vergil-project/.github#213 T7), run in tiers by
depth in the manifest's image tree (vergil-containers#773, T7b).

Each image is built once per architecture on that architecture's own runner
(no QEMU), pushed by digest, and the publish job stitches the two digests into
the multi-arch candidate before the unchanged scan, gate, attest and promote
tail. `base` is an ordinary matrix entry. Tier N+1 starts after tier N's
publishes, and a child is built FROM its parent's promoted digest. These tests
pin that shape and run the matrix, build-argument, digest and stitch scripts
for real (with `docker` stubbed).
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

import frozen
import generate as g
import manifest as mf
from test_generate import _tree

WORKFLOW = frozen.LIVE_ROOT / ".github" / "workflows" / "cd-docker-publish.yml"
MATRIX_JSON = frozen.LIVE_ROOT / "docker" / "versions" / "matrix.json"
# vergil-tooling lib/package/matrix.py RUNNERS: the native runner per arch.
RUNNERS = {"amd64": "ubuntu-24.04", "arm64": "ubuntu-24.04-arm"}
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
REPO = "ghcr.io/vergil-project/dev-python"
CANDIDATE = f"{REPO}:3.14-candidate"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _job(job: str) -> dict:
    return _workflow()["jobs"][job]


def _step(job: str, key: str) -> dict:
    for step in _job(job)["steps"]:
        if key in (step.get("id"), step.get("name")):
            return step
    raise AssertionError(f"{job}: no step {key!r}")


def _keys(job: str) -> list[str]:
    return [s.get("id", s.get("name")) for s in _job(job)["steps"]]


def _bash(script: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-e", "-c", script], cwd=cwd, env={**os.environ, **env},
        capture_output=True, text=True, check=False,
    )


def _outputs(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


def _read_matrix(tmp_path: Path, matrix_text: str) -> subprocess.CompletedProcess:
    if shutil.which("jq") is None:
        raise AssertionError("jq is not on PATH; the versions job's script needs it")
    (tmp_path / "docker" / "versions").mkdir(parents=True)
    (tmp_path / "docker" / "versions" / "matrix.json").write_text(matrix_text)
    out = tmp_path / "out"
    out.write_text("")
    script = _step("versions", "read")["run"]
    return _bash(script, tmp_path, {"GITHUB_OUTPUT": str(out)})


TIERS = (0, 1, 2)


def test_jobs_are_lint_versions_and_a_build_and_publish_per_tier():
    assert list(_workflow()["jobs"]) == [
        "hadolint", "versions", "build-0", "publish-0", "build-1", "publish-1", "build-2", "publish-2"]
    # One tier per depth the manifest allows.
    assert TIERS == tuple(range(mf.MAX_DEPTH + 1))


def test_no_emulation_anywhere():
    text = WORKFLOW.read_text()
    assert "setup-qemu-action" not in text
    assert "binfmt" not in text


def _tier_outputs(outputs: dict[str, str], tier: int) -> tuple[list, list, str]:
    return (json.loads(outputs[f"matrix-{tier}"])["include"],
            json.loads(outputs[f"arch-matrix-{tier}"])["include"], outputs[f"has-{tier}"])


def _arch(entries: list[dict]) -> list[dict]:
    return [{**e, "arch": arch, "runner": RUNNERS[arch]} for e in entries for arch in ("amd64", "arm64")]


def test_versions_emits_a_matrix_and_arch_matrix_per_tier(tmp_path):
    assert set(_job("versions")["outputs"]) == {
        f"{name}-{t}" for t in TIERS for name in ("matrix", "arch-matrix", "has")}
    result = _read_matrix(tmp_path, MATRIX_JSON.read_text())
    assert result.returncode == 0, result.stderr
    outputs = _outputs(tmp_path / "out")
    assert set(outputs) == set(_job("versions")["outputs"])
    entries = json.loads(MATRIX_JSON.read_text())["include"]
    # base is built FROM pkg-ubuntu (epic vergil-project/.github#649), so it is
    # tier 1, and the language images built FROM base are tier 2.
    tiers = {t: [e for e in entries if e["depth"] == t] for t in TIERS}
    assert [e["language"] for e in tiers[1]] == ["base"]
    assert tiers[2] and all(e["parent"] == {"language": "base", "version": "latest"} for e in tiers[2])
    for tier in TIERS:
        assert _tier_outputs(outputs, tier) == (tiers[tier], _arch(tiers[tier]), "true")
    # base is built like any other entry.
    assert {(e["language"], e["arch"]) for e in _arch(entries) if e["language"] == "base"} == {
        ("base", "amd64"), ("base", "arm64")}


def test_versions_splits_a_tree_into_tiers(tmp_path):
    # The synthetic tree pkg-ubuntu <- base <- python: the only exercise of
    # tiers 1 and 2 until #649 sets a real parent.
    entries = json.loads(g.render_matrix_json(_tree(), frozen.PINS))["include"]
    result = _read_matrix(tmp_path, json.dumps({"include": entries}))
    assert result.returncode == 0, result.stderr
    outputs = _outputs(tmp_path / "out")
    for tier in TIERS:
        tier_entries = [e for e in entries if e["depth"] == tier]
        assert tier_entries
        assert _tier_outputs(outputs, tier) == (tier_entries, _arch(tier_entries), "true")
    assert [e["language"] for e in json.loads(outputs["matrix-1"])["include"]] == ["base"]
    assert {e["language"] for e in json.loads(outputs["matrix-2"])["include"]} == {"python"}


@pytest.mark.parametrize("text", ['{"include": []}', "not json", "{}"])
def test_versions_fails_on_empty_or_malformed_matrix(tmp_path, text):
    assert _read_matrix(tmp_path, text).returncode != 0
    assert (tmp_path / "out").read_text() == ""


@pytest.mark.parametrize("depth", [3, -1, 0.5, "0", None])
def test_versions_refuses_an_entry_outside_the_tiers(tmp_path, depth):
    entries = json.loads(MATRIX_JSON.read_text())["include"]
    entries[-1] = {**entries[-1], "depth": depth}
    result = _read_matrix(tmp_path, json.dumps({"include": entries}))
    assert result.returncode != 0
    assert result.stdout.startswith("::error title=Matrix depth out of range::")
    assert (tmp_path / "out").read_text() == ""


ALWAYS = "!cancelled() && needs.hadolint.result == 'success' && needs.versions.result == 'success'"


@pytest.mark.parametrize("tier", TIERS)
def test_tiers_run_in_order_and_skip_when_empty(tier):
    build, publish = _job(f"build-{tier}"), _job(f"publish-{tier}")
    has = f"needs.versions.outputs.has-{tier} == 'true'"
    if tier == 0:
        assert build["needs"] == ["hadolint", "versions"]
        assert build["if"] == f"${{{{ {has} }}}}"
    else:
        # Tier N+1 starts once every tier-N publish has finished, whatever its
        # outcome: one failed parent stops only its own descendants.
        assert build["needs"] == ["hadolint", "versions", f"publish-{tier - 1}"]
        assert build["if"] == f"${{{{ {ALWAYS} && {has} }}}}"
    assert publish["needs"] == ["hadolint", "versions", f"build-{tier}"]
    assert publish["if"] == f"${{{{ {ALWAYS} && {has} }}}}"
    assert build["strategy"] == {
        "fail-fast": False, "matrix": f"${{{{ fromJSON(needs.versions.outputs.arch-matrix-{tier}) }}}}"}
    assert publish["strategy"] == {
        "fail-fast": False, "matrix": f"${{{{ fromJSON(needs.versions.outputs.matrix-{tier}) }}}}"}


@pytest.mark.parametrize("tier", (1, 2))
def test_every_tier_runs_tier_zeros_steps(tier):
    for kind in ("build", "publish"):
        first, job = _job(f"{kind}-0"), _job(f"{kind}-{tier}")
        assert job["steps"] == first["steps"]
        assert job["env"] == first["env"]
        assert job["name"] == first["name"]
        assert job["runs-on"] == first["runs-on"]


def test_build_runs_each_arch_on_its_native_runner():
    job = _job("build-0")
    assert job["runs-on"] == "${{ matrix.runner }}"
    build = _step("build-0", "build1")["with"]
    assert build["platforms"] == "linux/${{ matrix.arch }}"


def test_build_pushes_by_digest_with_a_per_arch_cache():
    job = _job("build-0")
    build = _step("build-0", "build1")["with"]
    assert build["outputs"] == (
        "type=image,name=${{ env.REPO }},push-by-digest=true,name-canonical=true,push=true")
    # No tag: the only tagged ref is the stitched candidate.
    assert "tags" not in build and "push" not in build
    assert job["env"]["CACHE_TAG"].endswith(":cache-${{ matrix.version }}-${{ matrix.arch }}")
    assert build["cache-from"] == "type=registry,ref=${{ env.CACHE_TAG }}"
    assert build["cache-to"] == "type=registry,ref=${{ env.CACHE_TAG }},mode=max"
    assert build["no-cache"] == "${{ inputs.no-cache }}"
    assert build["build-args"] == "${{ steps.args.outputs.build-args }}"


def test_build_resolves_its_args_and_parent_before_building():
    keys = _keys("build-0")
    assert keys.index("Download the parent's published digest") < keys.index("args") < keys.index("build1")
    download = _step("build-0", "Download the parent's published digest")
    assert download["if"] == "${{ matrix.parent != null }}"
    assert download["with"] == {
        "pattern": "image-digest-${{ inputs.image-prefix }}-${{ matrix.parent.language }}-${{ matrix.parent.version }}",
        "path": "${{ runner.temp }}/parent",
        "merge-multiple": True,
    }
    env = _step("build-0", "args")["env"]
    assert env["BUILD_ARGS_JSON"] == "${{ toJSON(matrix['build-args']) }}"
    assert env["PARENT_JSON"] == "${{ toJSON(matrix.parent) }}"


def _resolve(tmp_path: Path, build_args: dict, parent: dict | None, digest: str | None = None):
    pdir = tmp_path / "parent"
    pdir.mkdir()
    if digest is not None:
        (pdir / "digest").write_text(digest + "\n")
    out = tmp_path / "out"
    out.write_text("")
    script = _step("build-0", "args")["run"]
    env = {"BUILD_ARGS_JSON": json.dumps(build_args, indent=2), "PARENT_JSON": json.dumps(parent),
           "PARENT_DIR": str(pdir), "PREFIX": "dev", "REPO": REPO, "VERSION": "3.14", "GITHUB_OUTPUT": str(out)}
    return _bash(script, tmp_path, env), out.read_text()


def test_resolve_passes_every_build_arg(tmp_path):
    result, out = _resolve(tmp_path, {"PYTHON_VERSION": "3.14", "UV_VERSION": "0.9"}, None)
    assert result.returncode == 0, result.stderr
    assert out == "build-args<<BUILD_ARGS_EOF\nPYTHON_VERSION=3.14\nUV_VERSION=0.9\nBUILD_ARGS_EOF\n"


def test_resolve_passes_no_build_arg_for_base(tmp_path):
    result, out = _resolve(tmp_path, {}, None)
    assert result.returncode == 0, result.stderr
    assert out == "build-args<<BUILD_ARGS_EOF\nBUILD_ARGS_EOF\n"


def test_resolve_builds_a_child_from_its_parent_by_digest(tmp_path):
    result, out = _resolve(tmp_path, {"PYTHON_VERSION": "3.14"}, {"language": "base", "version": "latest"}, DIGEST_A)
    assert result.returncode == 0, result.stderr
    assert out.splitlines() == [
        "build-args<<BUILD_ARGS_EOF", "PYTHON_VERSION=3.14",
        f"PARENT_IMAGE=ghcr.io/vergil-project/dev-base@{DIGEST_A}", "BUILD_ARGS_EOF"]


@pytest.mark.parametrize("digest", [None, "", "sha256:short"])
def test_resolve_fails_naming_an_unpublished_parent(tmp_path, digest):
    result, out = _resolve(tmp_path, {"PYTHON_VERSION": "3.14"}, {"language": "base", "version": "latest"}, digest)
    assert result.returncode != 0
    assert result.stdout.startswith("::error title=Parent not published::")
    assert "its parent dev-base:latest" in result.stdout
    assert out == ""


@pytest.mark.parametrize("build_args", [{"PYTHON_VERSION": "3 14"}, {"python": "3.14"}, {"X": "a\nb"}])
def test_resolve_refuses_a_bad_build_arg(tmp_path, build_args):
    result, out = _resolve(tmp_path, build_args, None)
    assert result.returncode != 0
    assert out == ""


def test_build_records_and_uploads_its_digest(tmp_path):
    keys = _keys("build-0")
    assert keys.index("build1") < keys.index("Record the pushed digest") < keys.index("Upload the digest")
    upload = _step("build-0", "Upload the digest")["with"]
    assert upload["name"] == (
        "digest-${{ inputs.image-prefix }}-${{ matrix.language }}-${{ matrix.version }}-${{ matrix.arch }}")
    assert upload["path"] == "${{ runner.temp }}/digests/${{ matrix.arch }}"
    assert upload["if-no-files-found"] == "error"
    script = _step("build-0", "Record the pushed digest")["run"]
    digests = tmp_path / "digests"
    result = _bash(script, tmp_path, {"OUTCOME_1": "success", "DIGEST_1": DIGEST_A, "ARCH": "arm64", "DIGESTS_DIR": str(digests), "REPO": REPO})
    assert result.returncode == 0, result.stderr
    assert (digests / "arm64").read_text() == DIGEST_A + "\n"


@pytest.mark.parametrize("digest", ["", "sha256:abc", "latest"])
def test_build_fails_loudly_without_a_digest(tmp_path, digest):
    script = _step("build-0", "Record the pushed digest")["run"]
    digests = tmp_path / "digests"
    result = _bash(script, tmp_path, {"OUTCOME_1": "success", "DIGEST_1": digest, "ARCH": "amd64", "DIGESTS_DIR": str(digests), "REPO": REPO})
    assert result.returncode != 0
    assert result.stdout.startswith("::error title=No pushed digest::")
    assert not digests.exists()


def test_publish_runs_per_image_after_the_builds_whatever_their_outcome():
    job = _job("publish-0")
    assert job["name"] == "publish: ${{ inputs.image-prefix }}-${{ matrix.language }}:${{ matrix.version }}"
    # One image's failed build must not skip every other image's publish
    # (the `if` is pinned in test_tiers_run_in_order_and_skip_when_empty).
    assert job["if"].startswith("${{ !cancelled() && ")
    download = _step("publish-0", "Download the per-arch digests")["with"]
    assert download["pattern"] == "digest-${{ inputs.image-prefix }}-${{ matrix.language }}-${{ matrix.version }}-*"
    assert download["merge-multiple"] is True


def test_publish_stitches_before_the_unchanged_tail():
    keys = _keys("publish-0")
    order = ["Download the per-arch digests", "Stitch the multi-arch candidate", "trivy-amd64", "trivy-arm64",
             "Trivy gate", "digest", "attest1", "stamp", "Promote to final + immutable tags",
             "Verify digest preservation", "Record the published digest", "Upload the published digest"]
    assert [k for k in keys if k in order] == order
    # The published digest is the children's parent: recorded last, after
    # promotion, so an image that failed any gate is never built on.
    assert keys[-2:] == ["Record the published digest", "Upload the published digest"]


def test_publish_uploads_the_promoted_digest(tmp_path):
    upload = _step("publish-0", "Upload the published digest")["with"]
    # The name the children's "Download the parent's published digest" looks for.
    assert upload["name"] == "image-digest-${{ inputs.image-prefix }}-${{ matrix.language }}-${{ matrix.version }}"
    assert upload["path"] == "${{ runner.temp }}/image-digest/digest"
    assert upload["if-no-files-found"] == "error"
    record = _step("publish-0", "Record the published digest")
    assert record["env"]["DIGEST"] == "${{ steps.digest.outputs.digest }}"
    ddir = tmp_path / "image-digest"
    result = _bash(record["run"], tmp_path, {"DIGEST": DIGEST_B, "DIGEST_DIR": str(ddir), "IMAGE": CANDIDATE})
    assert result.returncode == 0, result.stderr
    assert (ddir / "digest").read_text() == DIGEST_B + "\n"
    result = _bash(record["run"], tmp_path / "image-digest", {"DIGEST": "", "DIGEST_DIR": str(tmp_path / "x"),
                                                               "IMAGE": CANDIDATE})
    assert result.returncode != 0
    assert result.stdout.startswith("::error title=No published digest::")
    assert not (tmp_path / "x").exists()


def test_sarif_categories_keep_their_names():
    stem = _job("publish-0")["env"]["SARIF_STEM"]
    assert stem == ("trivy-image-${{ inputs.image-prefix }}-${{ matrix.language }}"
                    "${{ matrix.language != 'base' && format('-{0}', matrix.version) || '' }}")
    assert _step("publish-0", "trivy-amd64")["with"]["sarif-category"] == "${{ env.SARIF_STEM }}-amd64"
    assert _step("publish-0", "Upload SARIF (arm64)")["with"]["category"] == "${{ env.SARIF_STEM }}-arm64"


def _stitch(tmp_path: Path, digests: dict[str, str]) -> tuple[subprocess.CompletedProcess, Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    record = tmp_path / "docker-args"
    stub = bindir / "docker"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{record}"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    ddir = tmp_path / "digests"
    ddir.mkdir()
    for arch, digest in digests.items():
        (ddir / arch).write_text(digest + "\n")
    script = _step("publish-0", "Stitch the multi-arch candidate")["run"]
    env = {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "DIGESTS_DIR": str(ddir),
           "REPO": REPO, "CANDIDATE": CANDIDATE}
    return _bash(script, tmp_path, env), record


def test_stitch_creates_the_candidate_from_both_digests(tmp_path):
    result, record = _stitch(tmp_path, {"amd64": DIGEST_A, "arm64": DIGEST_B})
    assert result.returncode == 0, result.stderr
    assert record.read_text().splitlines() == [
        "buildx", "imagetools", "create", "--tag", CANDIDATE, f"{REPO}@{DIGEST_A}", f"{REPO}@{DIGEST_B}"]


@pytest.mark.parametrize(("digests", "bad"), [
    ({"amd64": DIGEST_A}, ["arm64"]),
    ({"arm64": DIGEST_B}, ["amd64"]),
    ({}, ["amd64", "arm64"]),
    ({"amd64": DIGEST_A, "arm64": "sha256:short"}, ["arm64"]),
])
def test_stitch_fails_loudly_on_a_missing_digest(tmp_path, digests, bad):
    result, record = _stitch(tmp_path, digests)
    assert result.returncode != 0
    errors = [line for line in result.stdout.splitlines() if line.startswith("::error ")]
    assert [e.split("::")[1] for e in errors] == [f"error title=No {arch} digest" for arch in bad]
    assert all(CANDIDATE in e for e in errors)
    # Nothing is stitched from one architecture.
    assert not record.exists()
