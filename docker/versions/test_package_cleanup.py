"""Rate-limit posture of .github/workflows/package-cleanup.yml (issue #652).

The cleanup itself is the third-party dataaxiom/ghcr-cleanup-action, so the
retry lives in the workflow: a capped matrix fan-out, then per leg one retry of
the action after a bounded, jittered back-off, then a loud failure if the retry
fails too. These tests pin that structure and run the back-off and report
scripts for real (with `sleep` stubbed) so the bounds and the fail-loud exit
are exercised, not just asserted.
"""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

import frozen

WORKFLOW = frozen.LIVE_ROOT / ".github" / "workflows" / "package-cleanup.yml"
ACTION = re.compile(r"^dataaxiom/ghcr-cleanup-action@")
JOBS = ("cleanup", "reap-aliases")
# The failing runs started 32 legs at once; anything above this is back in the
# burst range that drew the 429s.
MAX_PARALLEL_CEILING = 4


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _steps(job: str) -> list[dict]:
    return _workflow()["jobs"][job]["steps"]


def _step(job: str, *, step_id: str | None = None, name: str | None = None) -> dict:
    for step in _steps(job):
        if (step_id and step.get("id") == step_id) or (name and step.get("name") == name):
            return step
    raise AssertionError(f"{job}: no step id={step_id!r} name={name!r}")


def _env() -> dict[str, int]:
    env = _workflow()["env"]
    return {k: int(env[k]) for k in ("RETRY_BACKOFF_BASE_SECONDS", "RETRY_BACKOFF_JITTER_SECONDS")}


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
def test_matrix_fan_out_is_capped(job):
    strategy = _workflow()["jobs"][job]["strategy"]
    assert strategy["fail-fast"] is False
    assert isinstance(strategy.get("max-parallel"), int)
    assert 1 <= strategy["max-parallel"] <= MAX_PARALLEL_CEILING


@pytest.mark.parametrize("job", JOBS)
def test_steps_are_attempt_backoff_retry_report_in_order(job):
    ids_or_names = [s.get("id", s["name"]) for s in _steps(job)]
    assert ids_or_names == ["attempt1", "Back off before retrying", "attempt2", "Report persistent failure"]


@pytest.mark.parametrize("job", JOBS)
def test_attempt1_failure_is_absorbed_and_retried(job):
    first = _step(job, step_id="attempt1")
    assert ACTION.match(first["uses"])
    assert first["continue-on-error"] is True
    assert "if" not in first
    backoff = _step(job, name="Back off before retrying")
    assert backoff["if"] == "steps.attempt1.outcome == 'failure'"


@pytest.mark.parametrize("job", JOBS)
def test_attempt2_is_an_identical_rerun_that_can_fail_the_leg(job):
    first, second = _step(job, step_id="attempt1"), _step(job, step_id="attempt2")
    assert second["uses"] == first["uses"]
    # Same inputs, so the retry is the same cleanup — including the dry-run
    # arming expression; drift here would let a retry delete when attempt 1
    # only previewed, or the reverse.
    assert second["with"] == first["with"]
    assert second["if"] == "steps.attempt1.outcome == 'failure'"
    # No continue-on-error: a second failure must fail the leg.
    assert not second.get("continue-on-error", False)


@pytest.mark.parametrize("job", JOBS)
def test_report_runs_only_when_the_retry_failed(job):
    report = _step(job, name="Report persistent failure")
    assert report["if"] == "failure() && steps.attempt2.outcome == 'failure'"
    assert report["env"]["PACKAGE"] == "${{ matrix.package }}"


def test_backoff_bounds_are_sane():
    env = _env()
    assert env["RETRY_BACKOFF_BASE_SECONDS"] >= 30
    assert env["RETRY_BACKOFF_JITTER_SECONDS"] >= 1
    # The whole retry must stay well inside a job's default timeout.
    assert env["RETRY_BACKOFF_BASE_SECONDS"] + env["RETRY_BACKOFF_JITTER_SECONDS"] <= 600


@pytest.mark.parametrize("job", JOBS)
def test_backoff_sleeps_within_bounds_and_warns(job, tmp_path):
    script = _step(job, name="Back off before retrying")["run"]
    env = _env()
    lo = env["RETRY_BACKOFF_BASE_SECONDS"]
    hi = lo + env["RETRY_BACKOFF_JITTER_SECONDS"]
    for _ in range(25):
        result = _run(script, tmp_path, {})
        assert result.returncode == 0, result.stderr
        assert "::warning title=Package cleanup retry::" in result.stdout
        assert "429" in result.stdout
    slept = [int(x) for x in (tmp_path / "slept").read_text().split()]
    assert len(slept) == 25
    assert all(lo <= s <= hi for s in slept), slept
    # Jitter actually varies the delay, so the legs do not re-synchronise.
    assert len(set(slept)) > 1


@pytest.mark.parametrize("job", JOBS)
def test_report_fails_loudly_with_rate_limit_details(job, tmp_path):
    script = _step(job, name="Report persistent failure")["run"]
    result = _run(script, tmp_path, {"PACKAGE": "dev-python"})
    assert result.returncode != 0
    env = _env()
    lo = env["RETRY_BACKOFF_BASE_SECONDS"]
    hi = lo + env["RETRY_BACKOFF_JITTER_SECONDS"]
    line = result.stdout.strip()
    assert line.startswith("::error title=Package cleanup failed twice::")
    assert "dev-python" in line
    assert f"{lo}-{hi}s back-off" in line
    assert "Request failed with status code 429" in line
    assert "max-parallel" in line
    assert not (tmp_path / "slept").exists()
