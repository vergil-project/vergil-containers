"""PR CI's selective image build and scan, .github/workflows/ci-images.yml
(vergil-containers#514, epic vergil-project/.github#213 T6').

`images / select` maps the PR's changed paths and matrix diff to the entries to
build (selection.py) and groups them into jobs (pr_jobs.py); `images / build`
builds, scans and smoke-tests each job's entries on the native runner of its
architecture, pushing nothing; `images / evidence` is the one aggregating
gate. These tests pin that shape and run the select and evidence scripts, and
scripts/bin/pr-image-build, for real (with `docker` stubbed).
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

import frozen
import generate as g
from test_generate import _tree
from test_includes import _synthetic_repo

WORKFLOWS = frozen.LIVE_ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "ci-images.yml"
BUILD_SCRIPT = frozen.LIVE_ROOT / "scripts" / "bin" / "pr-image-build"
VERSIONS = frozen.LIVE_ROOT / "docker" / "versions"
RUNNERS = {"amd64": "ubuntu-24.04", "arm64": "ubuntu-24.04-arm"}
REGISTRY = "localhost:5000"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _job(job: str) -> dict:
    return _workflow()["jobs"][job]


def _step(job: str, key: str) -> dict:
    for step in _job(job)["steps"]:
        if key in (step.get("id"), step.get("name")):
            return step
    raise AssertionError(f"{job}: no step {key!r}")


def _uses(job: str, action: str) -> dict:
    for step in _job(job)["steps"]:
        if step.get("uses", "").startswith(action + "@"):
            return step
    raise AssertionError(f"{job}: no {action} step")


def _bash(script: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-e", "-c", script], cwd=cwd, env={**os.environ, **env},
        capture_output=True, text=True, check=False,
    )


def _outputs(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


def _executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# --- shape -----------------------------------------------------------------


def test_ci_runs_the_images_workflow_on_pull_requests():
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    images = ci["jobs"]["images"]
    assert images["uses"] == "./.github/workflows/ci-images.yml"
    # PR CI only: the base and head commits come from the pull_request event.
    assert images["if"] == "github.event_name == 'pull_request'"


def test_jobs_are_select_build_and_one_evidence_gate():
    wf = _workflow()
    # PyYAML reads the bare `on` key as True.
    assert wf[True] == {"workflow_call": None}
    assert list(wf["jobs"]) == ["select", "build", "evidence"]
    assert _job("select")["name"] == "select"
    assert _job("build")["name"] == "build: ${{ matrix.name }} (${{ matrix.arch }})"
    assert _job("evidence")["name"] == "evidence"


def test_every_run_step_is_bash():
    # The select job runs in a container, where a step with no shell gets
    # `sh -e`; its scripts use bash (`[[ =~ ]]`, `set -o pipefail`), and the
    # tests here run them under bash.
    wf = _workflow()
    assert wf["defaults"] == {"run": {"shell": "bash"}}
    for name, job in wf["jobs"].items():
        assert "defaults" not in job, name
        for step in job.get("steps", []):
            assert step.get("shell", "bash") == "bash", f"{name}: {step.get('name')}"


def test_reads_only_and_pushes_nothing():
    wf = _workflow()
    assert wf["permissions"] == {"contents": "read"}
    for job in wf["jobs"].values():
        assert "permissions" not in job
    text = WORKFLOW.read_text()
    for banned in ("docker/login-action", "push=true", "cache-to", "packages: write", "secrets."):
        assert banned not in text
    assert "--push" not in BUILD_SCRIPT.read_text()
    assert "cache-to" not in BUILD_SCRIPT.read_text()


def test_no_emulation_anywhere():
    for text in (WORKFLOW.read_text(), BUILD_SCRIPT.read_text()):
        assert "setup-qemu-action" not in text
        assert "binfmt" not in text


def test_select_reads_the_whole_history_and_outputs_the_matrices():
    job = _job("select")
    assert job["container"] == {"image": "ghcr.io/vergil-project/prod-base:latest"}
    checkout = _uses("select", "actions/checkout")
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
    assert job["outputs"] == {
        "matrix": "${{ steps.select.outputs.matrix }}",
        "arch-matrix": "${{ steps.select.outputs.arch-matrix }}",
        "has": "${{ steps.select.outputs.has }}",
    }
    env = _step("select", "select")["env"]
    assert env["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert env["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"


def test_build_runs_each_job_on_its_native_runner():
    job = _job("build")
    assert job["needs"] == "select"
    assert job["if"] == "${{ needs.select.outputs.has == 'true' }}"
    assert job["runs-on"] == "${{ matrix.runner }}"
    assert job["strategy"] == {"fail-fast": False, "matrix": "${{ fromJSON(needs.select.outputs.arch-matrix) }}"}


def test_build_has_a_job_local_registry_for_its_parents():
    job = _job("build")
    # A parent built in this job is handed to its children through a
    # throwaway registry on the runner, never through GHCR.
    assert job["services"]["registry"]["ports"] == ["5000:5000"]
    assert job["services"]["registry"]["image"].startswith("registry:")
    buildx = _uses("build", "docker/setup-buildx-action")
    assert buildx["with"] == {"driver-opts": "network=host"}


def test_build_runs_the_build_script_with_its_entries():
    step = _step("build", "Build, scan and smoke-test")
    assert step["run"].strip() == 'scripts/bin/pr-image-build "$ARCH"'
    assert step["env"]["ARCH"] == "${{ matrix.arch }}"
    assert step["env"]["ENTRIES_JSON"] == "${{ toJSON(matrix.entries) }}"
    # The publish pipeline's Trivy image, so PR CI scans as publish does.
    publish = (WORKFLOWS / "cd-docker-publish.yml").read_text()
    assert f"TRIVY_IMAGE: {step['env']['TRIVY_IMAGE']}" in publish


def test_evidence_runs_whatever_the_builds_did():
    job = _job("evidence")
    assert job["needs"] == ["select", "build"]
    assert job["if"] == "${{ always() }}"
    env = _step("evidence", "evidence")["env"]
    assert env == {
        "SELECT_RESULT": "${{ needs.select.result }}",
        "HAS": "${{ needs.select.outputs.has }}",
        "BUILD_RESULT": "${{ needs.build.result }}",
    }


# --- images / evidence -----------------------------------------------------


def _evidence(tmp_path, select, has, build):
    env = {"SELECT_RESULT": select, "HAS": has, "BUILD_RESULT": build}
    return _bash(_step("evidence", "evidence")["run"], tmp_path, env)


@pytest.mark.parametrize(("select", "has", "build"), [
    ("success", "true", "success"),
    ("success", "false", "skipped"),
])
def test_evidence_passes_when_every_selected_image_was_proved(tmp_path, select, has, build):
    result = _evidence(tmp_path, select, has, build)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::error" not in result.stdout


@pytest.mark.parametrize(("select", "has", "build", "why"), [
    ("success", "true", "failure", "failure"),
    ("success", "true", "cancelled", "cancelled"),
    ("success", "true", "skipped", "skipped"),
    ("success", "false", "success", "nothing was selected"),
    ("failure", "", "skipped", "selection"),
    ("cancelled", "", "skipped", "selection"),
    ("success", "", "skipped", "has"),
    ("success", "maybe", "skipped", "has"),
])
def test_evidence_fails_closed_otherwise(tmp_path, select, has, build, why):
    result = _evidence(tmp_path, select, has, build)
    assert result.returncode != 0
    assert result.stdout.startswith("::error title=")
    assert why in result.stdout


# --- images / evidence: the ci-evidence-images artifact ---------------------

EMIT = "vergil-project/vergil-actions/actions/ci/evidence/emit"


def test_vergil_toml_declares_the_images_gate():
    # vergil-tooling#4132: `[ci].images` makes `images / evidence` a required
    # check and makes a release harvest `ci-evidence-images`, which the emit
    # step below uploads. Both live in the same commit.
    config = tomllib.loads((frozen.LIVE_ROOT / "vergil.toml").read_text())
    assert config["ci"]["images"] is True


def test_evidence_steps_check_then_report_then_emit():
    steps = _job("evidence")["steps"]
    assert [s.get("id") or s.get("uses", "").split("@")[0] for s in steps] == ["evidence", "report", EMIT]
    # No step carries an `if`: the report and the upload run on every passing
    # run, whatever was selected, and never after the check has failed.
    for step in steps:
        assert "if" not in step, step.get("name")


def test_emit_uploads_the_images_gate_with_the_report():
    emit = _uses("evidence", EMIT)
    # Pinned like the repo's other vergil-actions uses.
    assert emit["uses"] == f"{EMIT}@v2.1"
    assert emit["with"]["gate"] == "images"
    assert emit["with"]["files"] == "${{ steps.report.outputs.path }}"
    assert emit["with"]["metrics"] == "${{ steps.report.outputs.metrics }}"
    tools = json.loads(emit["with"]["tools"])
    trivy = next(t for t in tools if t["name"] == "trivy")
    assert trivy["image"] == _step("build", "Build, scan and smoke-test")["env"]["TRIVY_IMAGE"]


def test_report_reads_the_select_and_build_results():
    env = _step("evidence", "report")["env"]
    assert env == {
        "SELECT_RESULT": "${{ needs.select.result }}",
        "HAS": "${{ needs.select.outputs.has }}",
        "BUILD_RESULT": "${{ needs.build.result }}",
        "MATRIX": "${{ needs.select.outputs.matrix }}",
        "JOBS": "${{ needs.select.outputs.arch-matrix }}",
        "REPORT_DIR": "${{ runner.temp }}/images-report",
    }


def _report(tmp_path, has, build, matrix, jobs):
    out = tmp_path / "out"
    out.write_text("")
    env = {"SELECT_RESULT": "success", "HAS": has, "BUILD_RESULT": build,
           "MATRIX": matrix, "JOBS": jobs, "REPORT_DIR": str(tmp_path / "report"),
           "GITHUB_OUTPUT": str(out)}
    return _bash(_step("evidence", "report")["run"], tmp_path, env), out


def test_report_of_a_build_lists_what_was_selected_and_each_job(tmp_path):
    matrix = {"include": [{"language": "go", "version": "1.26"}]}
    jobs = {"include": [{"name": "go:1.26", "arch": a, "runner": RUNNERS[a], "entries": []}
                        for a in ("amd64", "arm64")]}
    result, out = _report(tmp_path, "true", "success", json.dumps(matrix), json.dumps(jobs))
    assert result.returncode == 0, result.stdout + result.stderr
    outputs = _outputs(out)
    report = json.loads(Path(outputs["path"]).read_text())
    assert Path(outputs["path"]) == tmp_path / "report" / "selected.json"
    assert report == {
        "select": "success", "has": True, "build": "success",
        "selected": matrix["include"],
        "jobs": [{"name": "go:1.26", "arch": "amd64", "runner": RUNNERS["amd64"], "result": "success"},
                 {"name": "go:1.26", "arch": "arm64", "runner": RUNNERS["arm64"], "result": "success"}],
    }
    assert json.loads(outputs["metrics"]) == {"selected": 1, "jobs": 2, "build": "success"}


def test_report_is_written_when_nothing_was_selected(tmp_path):
    empty = '{"include":[]}'
    result, out = _report(tmp_path, "false", "skipped", empty, empty)
    assert result.returncode == 0, result.stdout + result.stderr
    outputs = _outputs(out)
    report = json.loads(Path(outputs["path"]).read_text())
    assert report == {"select": "success", "has": False, "build": "skipped", "selected": [], "jobs": []}
    assert json.loads(outputs["metrics"]) == {"selected": 0, "jobs": 0, "build": "skipped"}


@pytest.mark.parametrize(("matrix", "jobs"), [
    ("", '{"include":[]}'),
    ('{"include":[]}', "not json"),
])
def test_report_fails_on_malformed_select_outputs(tmp_path, matrix, jobs):
    result, out = _report(tmp_path, "false", "skipped", matrix, jobs)
    assert result.returncode != 0
    assert out.read_text() == ""


# --- images / select -------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A git repo of `_tree()`'s synthetic manifest (pkg-ubuntu <- base <-
    python, go on an upstream image), with the live selector and job tooling,
    and a base commit."""
    root = _synthetic_repo(tmp_path / "repo")
    for script in VERSIONS.glob("*.py"):
        if not script.name.startswith("test_"):
            shutil.copy(script, root / "docker" / "versions" / script.name)
    (root / "docker" / "versions" / "matrix.json").write_text(g.render_matrix_json(_tree()))
    (root / "README.md").write_text("synthetic\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    return root


def _commit(repo: Path, path: str, text: str) -> str:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", path)
    return _git(repo, "rev-parse", "HEAD")


def _select(tmp_path, repo, base_sha, head_sha):
    # `uv run <script>` in the step runs the script with this interpreter,
    # which has PyYAML. Any other uv use fails the step.
    shim = tmp_path / "bin" / "uv"
    _executable(
        shim,
        '#!/bin/sh\n[ "$1" = run ] || { echo "uv shim: only uv run is supported" >&2; exit 2; }\n'
        f'shift\nexec "{sys.executable}" "$@"\n',
    )
    out = tmp_path / "out"
    out.write_text("")
    summary = tmp_path / "summary"
    env = {"BASE_SHA": base_sha, "HEAD_SHA": head_sha, "WORK": str(tmp_path / "work"),
           "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary),
           "HOME": str(tmp_path), "PATH": f"{shim.parent}{os.pathsep}{os.environ['PATH']}"}
    return _bash(_step("select", "select")["run"], repo, env), out


def _job_names(outputs):
    return [(j["name"], j["arch"]) for j in json.loads(outputs["arch-matrix"])["include"]]


def test_select_builds_only_the_changed_family(tmp_path, repo):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, "docker/common/go-only.dockerfile", "RUN true\n")
    result, out = _select(tmp_path, repo, base, head)
    assert result.returncode == 0, result.stdout + result.stderr
    outputs = _outputs(out)
    assert set(outputs) == {"matrix", "arch-matrix", "has"}
    assert [e["language"] for e in json.loads(outputs["matrix"])["include"]] == ["go"]
    assert _job_names(outputs) == [("go:1.26", "amd64"), ("go:1.26", "arm64")]
    for job in json.loads(outputs["arch-matrix"])["include"]:
        assert job["runner"] == RUNNERS[job["arch"]]
    assert outputs["has"] == "true"


def test_select_builds_a_parent_with_its_descendants(tmp_path, repo):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, "docker/common/base-only.dockerfile", "RUN true\n")
    result, out = _select(tmp_path, repo, base, head)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _job_names(_outputs(out)) == [("base:latest + 3 descendants", "amd64"),
                                         ("base:latest + 3 descendants", "arm64")]


def test_select_of_a_docs_change_selects_nothing(tmp_path, repo):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, "README.md", "changed\n")
    result, out = _select(tmp_path, repo, base, head)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _outputs(out) == {"matrix": '{"include":[]}', "arch-matrix": '{"include":[]}', "has": "false"}


def test_select_warns_and_builds_everything_for_an_unclassified_path(tmp_path, repo):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, "docker/new-thing/x", "x\n")
    result, out = _select(tmp_path, repo, base, head)
    assert result.returncode == 0, result.stdout + result.stderr
    # The selector's warning reaches the step's log, where the runner turns it
    # into an annotation.
    assert "::warning::unclassified path(s) under docker/" in result.stderr
    selected = json.loads(_outputs(out)["matrix"])["include"]
    assert selected == json.loads(g.render_matrix_json(_tree()))["include"]


def test_select_reads_the_base_commits_matrix(tmp_path, repo):
    base = _git(repo, "rev-parse", "HEAD")
    matrix = json.loads(g.render_matrix_json(_tree()))
    go = next(e for e in matrix["include"] if e["language"] == "go")
    go["build-args"]["EXTRA"] = "1"
    head = _commit(repo, "docker/versions/matrix.json", json.dumps(matrix, indent=2) + "\n")
    result, out = _select(tmp_path, repo, base, head)
    assert result.returncode == 0, result.stdout + result.stderr
    assert [e["language"] for e in json.loads(_outputs(out)["matrix"])["include"]] == ["go"]


@pytest.mark.parametrize("which", ["base", "head"])
@pytest.mark.parametrize("sha", ["", "HEAD", "not-a-sha"])
def test_select_refuses_a_missing_commit(tmp_path, repo, which, sha):
    real = _git(repo, "rev-parse", "HEAD")
    shas = {"base": real, "head": real, which: sha}
    result, out = _select(tmp_path, repo, shas["base"], shas["head"])
    assert result.returncode != 0
    assert result.stdout.startswith("::error title=Image selection failed::")
    assert out.read_text() == ""


def test_select_fails_on_an_unknown_commit(tmp_path, repo):
    real = _git(repo, "rev-parse", "HEAD")
    result, out = _select(tmp_path, repo, "0" * 40, real)
    assert result.returncode != 0
    assert "::error title=Image selection failed::" in result.stdout
    assert out.read_text() == ""


def test_select_fails_when_the_selector_fails(tmp_path, repo):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, "docker/versions/matrix.json", '{"include": "broken"}\n')
    result, out = _select(tmp_path, repo, base, head)
    assert result.returncode != 0
    assert "::error title=Image selection failed::" in result.stderr
    assert out.read_text() == ""


# --- scripts/bin/pr-image-build --------------------------------------------

STUB_DOCKER = r"""#!/usr/bin/env bash
# Records each call; `buildx build` and `push` fail for the tags named in
# STUB_FAIL_BUILD / STUB_FAIL_PUSH, and the Trivy `run` writes its report and
# reports findings for the images named in STUB_FINDINGS.
printf 'docker %s\n' "$*" >> "$STUB_LOG"
case "$1" in
  buildx)
    tag=""
    prev=""
    for a in "$@"; do
      if [ "$prev" = "--tag" ]; then tag="$a"; fi
      prev="$a"
    done
    case " ${STUB_FAIL_BUILD:-} " in *" $tag "*) exit 1 ;; esac
    ;;
  push)
    case " ${STUB_FAIL_PUSH:-} " in *" $2 "*) exit 1 ;; esac
    ;;
  run)
    printf '{}\n' > "${GITHUB_WORKSPACE}/${REPORT_FILE}"
    case " ${STUB_FINDINGS:-} " in *" $IMAGE_REF "*) exit 1 ;; esac
    ;;
esac
exit 0
"""

STUB_GENERATE = '#!/usr/bin/env bash\nprintf "generate %s\\n" "$*" >> "$STUB_LOG"\n'

STUB_SMOKE = (
    '#!/usr/bin/env bash\nprintf "smoke %s\\n" "$*" >> "$STUB_LOG"\n'
    'case " ${STUB_FAIL_SMOKE:-} " in *" $1 "*) exit 1 ;; esac\n'
)


def _entry(language, version, build_args=None, parent=None, depth=0, smoke=None,
           parent_local=False, push_local=False):
    return {"language": language, "version": version, "build-args": build_args or {},
            "parent": parent, "depth": depth, "smoke": smoke,
            "parent-local": parent_local, "push-local": push_local}


PYTHON = _entry("python", "3.15", {"PYTHON_VERSION": "3.15"})
BASE_PARENT = {"language": "base", "version": "latest"}


def _build(tmp_path, entries, arch="amd64", **fail):
    if shutil.which("jq") is None:
        raise AssertionError("jq is not on PATH; pr-image-build needs it")
    work = tmp_path / "workspace"
    _executable(work / "docker" / "generate.sh", STUB_GENERATE)
    _executable(work / "docker" / "cpp" / "smoke-test.sh", STUB_SMOKE)
    _executable(tmp_path / "bin" / "docker", STUB_DOCKER)
    log = tmp_path / "log"
    log.write_text("")
    summary = tmp_path / "summary"
    env = {"ENTRIES_JSON": json.dumps(entries), "GITHUB_WORKSPACE": str(work),
           "GITHUB_STEP_SUMMARY": str(summary), "TRIVY_IMAGE": "stub/trivy",
           "TRIVY_SCAN_ATTEMPTS": "1", "TRIVY_SCAN_RETRY_DELAY": "0", "STUB_LOG": str(log),
           "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
           **{f"STUB_{k.upper()}": " ".join(v) for k, v in fail.items()}}
    env.pop("GITHUB_OUTPUT", None)
    result = subprocess.run([str(BUILD_SCRIPT), arch], cwd=work, env={**os.environ, **env},
                            capture_output=True, text=True, check=False)
    return result, log.read_text().splitlines()


def _builds(log):
    return [line for line in log if line.startswith("docker buildx build")]


def test_build_one_platform_loaded_with_its_args_and_the_read_only_cache(tmp_path):
    result, log = _build(tmp_path, [PYTHON], arch="arm64")
    assert result.returncode == 0, result.stdout + result.stderr
    (build,) = _builds(log)
    assert build == (
        "docker buildx build --platform linux/arm64 --load"
        " --cache-from type=registry,ref=ghcr.io/vergil-project/dev-python:cache-3.15-arm64"
        " --build-arg PYTHON_VERSION=3.15"
        f" --tag {REGISTRY}/pr/python:3.15 {tmp_path / 'workspace' / 'docker' / 'python'}")
    assert log.index("generate python") < log.index(build)
    # Nothing leaves the runner: a leaf image is not even pushed locally.
    assert not [line for line in log if line.startswith("docker push")]


def test_build_scans_each_image_with_the_publish_scan_and_gate(tmp_path):
    result, log = _build(tmp_path, [PYTHON])
    assert result.returncode == 0, result.stdout + result.stderr
    (scan,) = [line for line in log if line.startswith("docker run")]
    assert "stub/trivy" in scan
    assert "Trivy gate passed for dev-python:3.15 (amd64)" in result.stdout
    assert (tmp_path / "workspace" / "trivy-python-3.15-amd64.sarif").is_file()


def test_build_fails_on_scan_findings_and_still_builds_the_rest(tmp_path):
    go = _entry("go", "1.26", {"GO_VERSION": "1.26"})
    result, log = _build(tmp_path, [PYTHON, go], findings=[f"{REGISTRY}/pr/python:3.15"])
    assert result.returncode == 1
    assert "::error::Trivy found CRITICAL/HIGH vulnerabilities in dev-python:3.15 (amd64)" in result.stdout
    assert len(_builds(log)) == 2


def test_build_failure_is_reported_and_the_rest_still_build(tmp_path):
    go = _entry("go", "1.26", {"GO_VERSION": "1.26"})
    result, log = _build(tmp_path, [PYTHON, go], fail_build=[f"{REGISTRY}/pr/python:3.15"])
    assert result.returncode == 1
    assert "::error title=Image build failed::dev-python:3.15 (amd64)" in result.stdout
    assert len(_builds(log)) == 2
    # A failed build is not scanned: the one scan is go's, after its build.
    (scan,) = [line for line in log if line.startswith("docker run")]
    assert log.index(_builds(log)[1]) < log.index(scan)
    assert "Trivy gate passed for dev-go:1.26 (amd64)" in result.stdout


def test_child_alone_builds_on_the_published_dev_parent(tmp_path):
    child = _entry("python", "3.15", {"PYTHON_VERSION": "3.15"}, parent=BASE_PARENT, depth=2)
    result, log = _build(tmp_path, [child])
    assert result.returncode == 0, result.stdout + result.stderr
    (build,) = _builds(log)
    assert "--build-arg PYTHON_VERSION=3.15 --build-arg PARENT_IMAGE=ghcr.io/vergil-project/dev-base:latest " in build


def test_selected_parent_is_built_first_and_its_children_build_on_it(tmp_path):
    base = _entry("base", "latest", parent={"language": "pkg-ubuntu", "version": "24.04"}, depth=1,
                  push_local=True)
    child = _entry("python", "3.15", {"PYTHON_VERSION": "3.15"}, parent=BASE_PARENT, depth=2,
                   parent_local=True)
    result, log = _build(tmp_path, [base, child])
    assert result.returncode == 0, result.stdout + result.stderr
    base_build, child_build = _builds(log)
    assert "--build-arg PARENT_IMAGE=ghcr.io/vergil-project/dev-pkg-ubuntu:24.04 " in base_build
    assert f"--tag {REGISTRY}/pr/base:latest " in base_build
    assert f"--build-arg PARENT_IMAGE={REGISTRY}/pr/base:latest " in child_build
    push = f"docker push {REGISTRY}/pr/base:latest"
    assert log.index(base_build) < log.index(push) < log.index(child_build)


@pytest.mark.parametrize("fail", ["fail_build", "fail_push"])
def test_children_of_a_failed_parent_are_not_built(tmp_path, fail):
    base = _entry("base", "latest", push_local=True)
    child = _entry("python", "3.15", {"PYTHON_VERSION": "3.15"}, parent=BASE_PARENT, depth=1,
                   parent_local=True)
    result, log = _build(tmp_path, [base, child], **{fail: [f"{REGISTRY}/pr/base:latest"]})
    assert result.returncode == 1
    assert len(_builds(log)) == 1
    assert ("::error title=Parent not built::dev-python:3.15 (amd64) is built FROM dev-base:latest,"
            in result.stdout)


def test_parent_local_without_the_parent_in_the_job_fails(tmp_path):
    child = _entry("python", "3.15", parent=BASE_PARENT, depth=1, parent_local=True)
    result, log = _build(tmp_path, [child])
    assert result.returncode == 1
    assert "::error title=Parent not built::" in result.stdout
    assert _builds(log) == []


def test_smoke_test_runs_on_the_built_image(tmp_path):
    clang = _entry("cpp-clang", "20", {"CLANG_VERSION": "20"}, smoke="cpp")
    result, log = _build(tmp_path, [clang])
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"smoke {REGISTRY}/pr/cpp-clang:20 docker" in log


def test_smoke_test_failure_fails_the_job(tmp_path):
    clang = _entry("cpp-clang", "20", {"CLANG_VERSION": "20"}, smoke="cpp")
    result, _ = _build(tmp_path, [clang], fail_smoke=[f"{REGISTRY}/pr/cpp-clang:20"])
    assert result.returncode == 1
    assert "::error title=Smoke test failed::dev-cpp-clang:20 (amd64)" in result.stdout


def test_summary_lists_each_image(tmp_path):
    go = _entry("go", "1.26", {"GO_VERSION": "1.26"})
    result, _ = _build(tmp_path, [PYTHON, go], fail_build=[f"{REGISTRY}/pr/go:1.26"])
    assert result.returncode == 1
    summary = (tmp_path / "summary").read_text()
    assert "| dev-python:3.15 | amd64 | passed |" in summary
    assert "| dev-go:1.26 | amd64 | build failed |" in summary


@pytest.mark.parametrize("build_args", [{"bad name": "x"}, {"A": "has space"}, {"A": ""}])
def test_bad_build_arg_refused(tmp_path, build_args):
    result, log = _build(tmp_path, [_entry("python", "3.15", build_args)])
    assert result.returncode == 1
    assert "::error title=Bad build argument::" in result.stdout
    assert _builds(log) == []


@pytest.mark.parametrize("entries", [[], "x", [{"language": "../x", "version": "1"}]])
def test_bad_entries_refused(tmp_path, entries):
    result, log = _build(tmp_path, entries)
    assert result.returncode != 0
    assert "::error title=" in result.stdout
    assert _builds(log) == []


@pytest.mark.parametrize("arch", ["", "386", "linux/amd64"])
def test_bad_arch_refused(tmp_path, arch):
    result, log = _build(tmp_path, [PYTHON], arch=arch)
    assert result.returncode != 0
    assert "::error title=" in result.stdout
    assert log == []
