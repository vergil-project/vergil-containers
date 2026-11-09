"""Native per-arch build and stitch in .github/workflows/cd-docker-publish.yml
(vergil-containers#515, epic vergil-project/.github#213 T7).

Each image is built once per architecture on that architecture's own runner
(no QEMU), pushed by digest, and the publish job stitches the two digests into
the multi-arch candidate before the unchanged scan, gate, attest and promote
tail. `base` is an ordinary matrix entry. These tests pin that shape and run the
matrix, digest and stitch scripts for real (with `docker` stubbed).
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


def test_jobs_are_lint_versions_build_publish():
    assert set(_workflow()["jobs"]) == {"hadolint", "versions", "build", "publish"}


def test_no_emulation_anywhere():
    text = WORKFLOW.read_text()
    assert "setup-qemu-action" not in text
    assert "binfmt" not in text


def test_versions_emits_matrix_and_arch_matrix(tmp_path):
    result = _read_matrix(tmp_path, MATRIX_JSON.read_text())
    assert result.returncode == 0, result.stderr
    outputs = _outputs(tmp_path / "out")
    assert set(_job("versions")["outputs"]) == {"matrix", "arch-matrix"}
    entries = json.loads(MATRIX_JSON.read_text())["include"]
    assert json.loads(outputs["matrix"]) == {"include": entries}
    expected = [{**e, "arch": arch, "runner": RUNNERS[arch]} for e in entries for arch in ("amd64", "arm64")]
    assert json.loads(outputs["arch-matrix"]) == {"include": expected}
    # base is built like any other entry.
    assert {(e["language"], e["arch"]) for e in expected if e["language"] == "base"} == {
        ("base", "amd64"), ("base", "arm64")}


@pytest.mark.parametrize("text", ['{"include": []}', "not json", "{}"])
def test_versions_fails_on_empty_or_malformed_matrix(tmp_path, text):
    assert _read_matrix(tmp_path, text).returncode != 0
    assert (tmp_path / "out").read_text() == ""


def test_build_runs_each_arch_on_its_native_runner():
    job = _job("build")
    assert job["runs-on"] == "${{ matrix.runner }}"
    assert job["strategy"]["fail-fast"] is False
    assert job["strategy"]["matrix"] == "${{ fromJSON(needs.versions.outputs.arch-matrix) }}"
    assert set(job["needs"]) == {"hadolint", "versions"}
    build = _step("build", "build")["with"]
    assert build["platforms"] == "linux/${{ matrix.arch }}"


def test_build_pushes_by_digest_with_a_per_arch_cache():
    job = _job("build")
    build = _step("build", "build")["with"]
    assert build["outputs"] == (
        "type=image,name=${{ env.REPO }},push-by-digest=true,name-canonical=true,push=true")
    # No tag: the only tagged ref is the stitched candidate.
    assert "tags" not in build and "push" not in build
    assert job["env"]["CACHE_TAG"].endswith(":cache-${{ matrix.version }}-${{ matrix.arch }}")
    assert build["cache-from"] == "type=registry,ref=${{ env.CACHE_TAG }}"
    assert build["cache-to"] == "type=registry,ref=${{ env.CACHE_TAG }},mode=max"
    assert build["no-cache"] == "${{ inputs.no-cache }}"
    # base's null build-arg passes no --build-arg.
    assert build["build-args"] == (
        "${{ matrix.build-arg && format('{0}={1}', matrix.build-arg, matrix.version) || '' }}")


def test_build_records_and_uploads_its_digest(tmp_path):
    keys = _keys("build")
    assert keys.index("build") < keys.index("Record the pushed digest") < keys.index("Upload the digest")
    upload = _step("build", "Upload the digest")["with"]
    assert upload["name"] == (
        "digest-${{ inputs.image-prefix }}-${{ matrix.language }}-${{ matrix.version }}-${{ matrix.arch }}")
    assert upload["path"] == "${{ runner.temp }}/digests/${{ matrix.arch }}"
    assert upload["if-no-files-found"] == "error"
    script = _step("build", "Record the pushed digest")["run"]
    digests = tmp_path / "digests"
    result = _bash(script, tmp_path, {"DIGEST": DIGEST_A, "ARCH": "arm64", "DIGESTS_DIR": str(digests), "REPO": REPO})
    assert result.returncode == 0, result.stderr
    assert (digests / "arm64").read_text() == DIGEST_A + "\n"


@pytest.mark.parametrize("digest", ["", "sha256:abc", "latest"])
def test_build_fails_loudly_without_a_digest(tmp_path, digest):
    script = _step("build", "Record the pushed digest")["run"]
    digests = tmp_path / "digests"
    result = _bash(script, tmp_path, {"DIGEST": digest, "ARCH": "amd64", "DIGESTS_DIR": str(digests), "REPO": REPO})
    assert result.returncode != 0
    assert result.stdout.startswith("::error title=No pushed digest::")
    assert not digests.exists()


def test_publish_runs_per_image_after_the_builds_whatever_their_outcome():
    job = _job("publish")
    assert job["name"] == "publish: ${{ inputs.image-prefix }}-${{ matrix.language }}:${{ matrix.version }}"
    assert job["strategy"]["matrix"] == "${{ fromJSON(needs.versions.outputs.matrix) }}"
    assert job["strategy"]["fail-fast"] is False
    assert set(job["needs"]) == {"hadolint", "versions", "build"}
    # One image's failed build must not skip every other image's publish.
    assert job["if"] == (
        "${{ !cancelled() && needs.hadolint.result == 'success' && needs.versions.result == 'success' }}")
    download = _step("publish", "Download the per-arch digests")["with"]
    assert download["pattern"] == "digest-${{ inputs.image-prefix }}-${{ matrix.language }}-${{ matrix.version }}-*"
    assert download["merge-multiple"] is True


def test_publish_stitches_before_the_unchanged_tail():
    keys = _keys("publish")
    order = ["Download the per-arch digests", "Stitch the multi-arch candidate", "trivy-amd64", "trivy-arm64",
             "Trivy gate", "digest", "attest1", "stamp", "Promote to final + immutable tags",
             "Verify digest preservation"]
    assert [k for k in keys if k in order] == order


def test_sarif_categories_keep_their_names():
    stem = _job("publish")["env"]["SARIF_STEM"]
    assert stem == ("trivy-image-${{ inputs.image-prefix }}-${{ matrix.language }}"
                    "${{ matrix.language != 'base' && format('-{0}', matrix.version) || '' }}")
    assert _step("publish", "trivy-amd64")["with"]["sarif-category"] == "${{ env.SARIF_STEM }}-amd64"
    assert _step("publish", "Upload SARIF (arm64)")["with"]["category"] == "${{ env.SARIF_STEM }}-arm64"


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
    script = _step("publish", "Stitch the multi-arch candidate")["run"]
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
