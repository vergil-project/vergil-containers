"""Per-arch push retry in .github/workflows/cd-docker-publish.yml (issue #794).

GHCR sporadically refuses one per-arch push by digest with
"denied: permission_denied: write_package" while the same token pushes the
same package seconds before and after. Each build job therefore runs "Build
and push by digest" as up to three attempts: attempts 1 and 2 are absorbed
(continue-on-error), each retry is preceded by a bounded, jittered back-off
that warns, attempt 3 decides the job, and a final step fails loudly naming
the image and arch. The recorded digest is the one from the attempt that
succeeded. These tests pin that shape on every tier's build job and run the
back-off, report and record scripts for real (with `sleep` stubbed).
"""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

import frozen

WORKFLOW = frozen.LIVE_ROOT / ".github" / "workflows" / "cd-docker-publish.yml"
ACTION = re.compile(r"^docker/build-push-action@")
JOBS = ("build-0", "build-1", "build-2")
BACKOFF_2 = "Back off before push attempt 2"
BACKOFF_3 = "Back off before push attempt 3"
REPORT = "Report persistent push failure"
RECORD = "Record the pushed digest"
SEQUENCE = ["build1", BACKOFF_2, "build2", BACKOFF_3, "build3", REPORT, RECORD, "Upload the digest"]
ENV_KEYS = ("PUSH_RETRY_BACKOFF_BASE_SECONDS", "PUSH_RETRY_BACKOFF_JITTER_SECONDS")
REPO = "ghcr.io/vergil-project/dev-python"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _steps(job: str) -> list[dict]:
    return _workflow()["jobs"][job]["steps"]


def _keys(job: str) -> list[str]:
    return [s.get("id", s.get("name")) for s in _steps(job)]


def _step(job: str, key: str) -> dict:
    for step in _steps(job):
        if key in (step.get("id"), step.get("name")):
            return step
    raise AssertionError(f"{job}: no step {key!r}")


def _env() -> dict[str, int]:
    env = _workflow()["env"]
    return {k: int(env[k]) for k in ENV_KEYS}


def _run(script: str, tmp_path: Path, extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run a step's `run:` script under bash with `sleep` stubbed to record its
    argument instead of waiting."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    record = tmp_path / "slept"
    stub = bindir / "sleep"
    stub.write_text(f'#!/usr/bin/env bash\necho "$1" >> "{record}"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        **{k: str(v) for k, v in _env().items()},
        "REPO": REPO,
        "VERSION": "3.14",
        **extra_env,
    }
    return subprocess.run(
        ["bash", "-e", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize("job", JOBS)
def test_push_is_three_attempts_with_backoffs_then_report_then_record(job):
    keys = _keys(job)
    start = keys.index("build1")
    assert keys[start:start + len(SEQUENCE)] == SEQUENCE
    assert keys.index("args") < start
    # Exactly the three attempts use the action: no unretried copy is left behind.
    assert [s.get("id") for s in _steps(job) if ACTION.match(s.get("uses", ""))] == ["build1", "build2", "build3"]


@pytest.mark.parametrize("job", JOBS)
def test_attempts_are_identical_and_each_retry_follows_a_failure(job):
    first, second, third = (_step(job, k) for k in ("build1", "build2", "build3"))
    assert second["uses"] == first["uses"] and third["uses"] == first["uses"]
    assert second["with"] == first["with"] and third["with"] == first["with"]
    assert "if" not in first
    assert first["continue-on-error"] is True
    assert second["if"] == "steps.build1.outcome == 'failure'"
    assert second["continue-on-error"] is True
    assert third["if"] == "steps.build2.outcome == 'failure'"
    # No continue-on-error on the last attempt: its failure fails the job.
    assert not third.get("continue-on-error", False)


@pytest.mark.parametrize("job", JOBS)
def test_backoffs_run_only_before_a_retry(job):
    assert _step(job, BACKOFF_2)["if"] == "steps.build1.outcome == 'failure'"
    assert _step(job, BACKOFF_3)["if"] == "steps.build2.outcome == 'failure'"
    assert _step(job, BACKOFF_2)["env"]["ATTEMPT"] == 2
    assert _step(job, BACKOFF_3)["env"]["ATTEMPT"] == 3
    for key in (BACKOFF_2, BACKOFF_3):
        assert _step(job, key)["env"]["ARCH"] == "${{ matrix.arch }}"


@pytest.mark.parametrize("job", JOBS)
def test_report_runs_only_when_the_last_attempt_failed(job):
    report = _step(job, REPORT)
    assert report["if"] == "failure() && steps.build3.outcome == 'failure'"
    assert not report.get("continue-on-error", False)
    assert report["env"]["ARCH"] == "${{ matrix.arch }}"


@pytest.mark.parametrize("job", JOBS)
def test_record_and_upload_run_only_on_success(job):
    # They keep the default success() gate: nothing is recorded or uploaded
    # after three failed attempts, so the stitch reports the missing digest.
    for key in (RECORD, "Upload the digest"):
        assert "if" not in _step(job, key)


@pytest.mark.parametrize("job", JOBS)
def test_record_reads_every_attempts_outcome_and_digest(job):
    env = _step(job, RECORD)["env"]
    for n in (1, 2, 3):
        assert env[f"OUTCOME_{n}"] == f"${{{{ steps.build{n}.outcome }}}}"
        assert env[f"DIGEST_{n}"] == f"${{{{ steps.build{n}.outputs.digest }}}}"
    assert "DIGEST" not in env


def test_backoff_bounds_are_sane():
    env = _env()
    assert env["PUSH_RETRY_BACKOFF_BASE_SECONDS"] >= 10
    assert env["PUSH_RETRY_BACKOFF_JITTER_SECONDS"] >= 1
    assert env["PUSH_RETRY_BACKOFF_BASE_SECONDS"] + env["PUSH_RETRY_BACKOFF_JITTER_SECONDS"] <= 120


@pytest.mark.parametrize("job", JOBS)
@pytest.mark.parametrize("key", (BACKOFF_2, BACKOFF_3))
def test_backoff_sleeps_within_bounds_and_warns(job, key, tmp_path):
    step = _step(job, key)
    env = _env()
    lo = env["PUSH_RETRY_BACKOFF_BASE_SECONDS"]
    hi = lo + env["PUSH_RETRY_BACKOFF_JITTER_SECONDS"]
    attempt = step["env"]["ATTEMPT"]
    for _ in range(25):
        result = _run(step["run"], tmp_path, {"ATTEMPT": str(attempt), "ARCH": "arm64"})
        assert result.returncode == 0, result.stderr
        line = result.stdout.strip()
        assert line.startswith("::warning title=Push retry::")
        assert f"{REPO}:3.14 (arm64)" in line
        assert f"attempt {attempt - 1} of 3" in line
        assert f"attempt {attempt}" in line
    slept = [int(x) for x in (tmp_path / "slept").read_text().split()]
    assert len(slept) == 25
    assert all(lo <= s <= hi for s in slept), slept
    assert len(set(slept)) > 1


@pytest.mark.parametrize("job", JOBS)
def test_report_fails_loudly_naming_image_and_arch(job, tmp_path):
    result = _run(_step(job, REPORT)["run"], tmp_path, {"ARCH": "amd64"})
    assert result.returncode != 0
    line = result.stdout.strip()
    assert line.startswith("::error title=Push failed three times::")
    assert f"{REPO}:3.14 (amd64)" in line
    assert not (tmp_path / "slept").exists()


def _record(job: str, tmp_path: Path, attempts: dict[int, tuple[str, str]]):
    digests = tmp_path / "digests"
    env = {"ARCH": "arm64", "DIGESTS_DIR": str(digests)}
    for n in (1, 2, 3):
        outcome, digest = attempts.get(n, ("skipped", ""))
        env[f"OUTCOME_{n}"] = outcome
        env[f"DIGEST_{n}"] = digest
    return _run(_step(job, RECORD)["run"], tmp_path, env), digests


@pytest.mark.parametrize("job", JOBS)
@pytest.mark.parametrize("attempts, expected", [
    ({1: ("success", DIGEST_A)}, DIGEST_A),
    ({1: ("failure", ""), 2: ("success", DIGEST_B)}, DIGEST_B),
    # A failed attempt's output, if any, is never the one recorded.
    ({1: ("failure", DIGEST_A), 2: ("success", DIGEST_B)}, DIGEST_B),
    ({1: ("failure", DIGEST_A), 2: ("failure", DIGEST_A), 3: ("success", DIGEST_B)}, DIGEST_B),
])
def test_record_takes_the_digest_of_the_successful_attempt(job, tmp_path, attempts, expected):
    result, digests = _record(job, tmp_path, attempts)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (digests / "arm64").read_text() == expected + "\n"


@pytest.mark.parametrize("job", JOBS)
@pytest.mark.parametrize("attempts", [
    {},
    {1: ("failure", DIGEST_A), 2: ("failure", DIGEST_A), 3: ("failure", DIGEST_A)},
    {1: ("success", "")},
    {1: ("failure", ""), 2: ("success", "sha256:abc")},
])
def test_record_fails_loudly_without_a_successful_digest(job, tmp_path, attempts):
    result, digests = _record(job, tmp_path, attempts)
    assert result.returncode != 0
    assert result.stdout.startswith("::error title=No pushed digest::")
    assert not digests.exists()
