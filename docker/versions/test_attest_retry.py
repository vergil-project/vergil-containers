"""Attestation retry in .github/workflows/cd-docker-publish.yml (issue #743).

A transient Sigstore error ("error fetching tlog entry") failed a publish after
the image had built and passed the scan. actions/attest-build-provenance has no
retry input, so each publish job runs it as attempt 1 (absorbed), a bounded
jittered back-off, attempt 2 (decides the job) and a loud report, the shape
package-cleanup.yml uses (issue #652). These tests pin that structure, check
that promotion still comes after attestation, and run the back-off and report
scripts for real (with `sleep` stubbed).
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
ACTION = re.compile(r"^actions/attest-build-provenance@")
JOBS = ("publish-0", "publish-1", "publish-2")
SEQUENCE = [
    "attest1",
    "Back off before retrying attestation",
    "attest2",
    "Report persistent attestation failure",
]
ENV_KEYS = ("ATTEST_RETRY_BACKOFF_BASE_SECONDS", "ATTEST_RETRY_BACKOFF_JITTER_SECONDS")


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
        **extra_env,
    }
    return subprocess.run(
        ["bash", "-e", "-c", script], env=env, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize("job", JOBS)
def test_attestation_is_attempt_backoff_retry_report_after_digest_before_promotion(job):
    keys = _keys(job)
    start = keys.index("attest1")
    assert keys[start:start + len(SEQUENCE)] == SEQUENCE
    # The digest it attests comes first; nothing is promoted until it has run.
    assert keys.index("digest") < start
    assert keys.index("Promote to final + immutable tags") > start + len(SEQUENCE) - 1
    # Exactly the two attempts use the action: no unretried copy is left behind.
    assert [s.get("id") for s in _steps(job) if ACTION.match(s.get("uses", ""))] == ["attest1", "attest2"]


@pytest.mark.parametrize("job", JOBS)
def test_attempt1_failure_is_absorbed_and_retried(job):
    first = _step(job, "attest1")
    assert first["continue-on-error"] is True
    assert "if" not in first
    assert _step(job, "Back off before retrying attestation")["if"] == "steps.attest1.outcome == 'failure'"


@pytest.mark.parametrize("job", JOBS)
def test_attempt2_is_an_identical_rerun_that_can_fail_the_job(job):
    first, second = _step(job, "attest1"), _step(job, "attest2")
    assert second["uses"] == first["uses"]
    assert second["with"] == first["with"]
    assert second["if"] == "steps.attest1.outcome == 'failure'"
    # No continue-on-error: a second failure must fail the job.
    assert not second.get("continue-on-error", False)


@pytest.mark.parametrize("job", JOBS)
def test_report_runs_only_when_the_retry_failed(job):
    report = _step(job, "Report persistent attestation failure")
    assert report["if"] == "failure() && steps.attest2.outcome == 'failure'"
    assert not report.get("continue-on-error", False)


@pytest.mark.parametrize("job", JOBS)
def test_promotion_runs_only_on_success(job):
    # Promotion keeps the default success() gate, so a twice-failed
    # attestation stops the unattested candidate from being promoted.
    for key in ("Promote to final + immutable tags", "Verify digest preservation"):
        assert "if" not in _step(job, key)


def test_backoff_bounds_are_sane():
    env = _env()
    assert env["ATTEST_RETRY_BACKOFF_BASE_SECONDS"] >= 10
    assert env["ATTEST_RETRY_BACKOFF_JITTER_SECONDS"] >= 1
    assert env["ATTEST_RETRY_BACKOFF_BASE_SECONDS"] + env["ATTEST_RETRY_BACKOFF_JITTER_SECONDS"] <= 300


@pytest.mark.parametrize("job", JOBS)
def test_backoff_sleeps_within_bounds_and_warns(job, tmp_path):
    script = _step(job, "Back off before retrying attestation")["run"]
    env = _env()
    lo = env["ATTEST_RETRY_BACKOFF_BASE_SECONDS"]
    hi = lo + env["ATTEST_RETRY_BACKOFF_JITTER_SECONDS"]
    for _ in range(25):
        result = _run(script, tmp_path, {})
        assert result.returncode == 0, result.stderr
        assert "::warning title=Attestation retry::" in result.stdout
    slept = [int(x) for x in (tmp_path / "slept").read_text().split()]
    assert len(slept) == 25
    assert all(lo <= s <= hi for s in slept), slept
    assert len(set(slept)) > 1


@pytest.mark.parametrize("job", JOBS)
def test_report_fails_loudly(job, tmp_path):
    script = _step(job, "Report persistent attestation failure")["run"]
    result = _run(script, tmp_path, {"CANDIDATE": "ghcr.io/o/dev-python:3.14-candidate"})
    assert result.returncode != 0
    env = _env()
    lo = env["ATTEST_RETRY_BACKOFF_BASE_SECONDS"]
    hi = lo + env["ATTEST_RETRY_BACKOFF_JITTER_SECONDS"]
    line = result.stdout.strip()
    assert line.startswith("::error title=Attestation failed twice::")
    assert "ghcr.io/o/dev-python:3.14-candidate" in line
    assert f"{lo}-{hi}s back-off" in line
    assert not (tmp_path / "slept").exists()
