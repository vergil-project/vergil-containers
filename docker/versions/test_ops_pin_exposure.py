"""Failure visibility of the pin-exposure job in .github/workflows/ops.yml (#819).

The report is informational: a finding is printed and report_exposure.py exits
0. But the script itself failing (an import error, a crash before it reports)
must fail the nightly. Two things used to mask that: `continue-on-error: true`
on the job, and a `| tee` pipeline under the container job's default `sh -e`,
whose status is tee's. These tests pin the job's structure and run the step's
script for real, with `uv` stubbed, so the masking cannot come back unnoticed.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

import frozen

WORKFLOW = frozen.LIVE_ROOT / ".github" / "workflows" / "ops.yml"
JOB = "pin-exposure"
STEP = "Report pin exposure"


def _job() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"][JOB]


def _step() -> dict:
    for step in _job()["steps"]:
        if step.get("name") == STEP:
            return step
    raise AssertionError(f"{JOB}: no step {STEP!r}")


def _run(script: str, tmp_path: Path, uv_exit: int) -> tuple[subprocess.CompletedProcess, Path]:
    """Run the step's `run:` script under plain bash (no -e, no pipefail from
    the caller, so only the script's own settings count), with `uv` stubbed to
    print a line and exit with `uv_exit`."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    uv = bindir / "uv"
    uv.write_text(f"#!/usr/bin/env bash\necho 'report line'\nexit {uv_exit}\n")
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR)
    summary = tmp_path / "summary.md"
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    result = subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True, check=False
    )
    return result, summary


def test_job_failure_is_not_absorbed():
    assert not _job().get("continue-on-error", False)
    assert not _step().get("continue-on-error", False)


def test_step_runs_under_bash_with_pipefail():
    step = _step()
    assert step["shell"] == "bash"
    assert "set -euo pipefail" in step["run"]
    assert "report_exposure.py --no-probe" in step["run"]


@pytest.mark.parametrize("code", [1, 2])
def test_script_failure_fails_the_step(tmp_path, code):
    result, summary = _run(_step()["run"], tmp_path, uv_exit=code)
    assert result.returncode == code, result.stderr
    # What the script printed before it failed still reaches the summary.
    assert "report line" in summary.read_text()


def test_clean_report_passes_and_reaches_the_summary(tmp_path):
    result, summary = _run(_step()["run"], tmp_path, uv_exit=0)
    assert result.returncode == 0, result.stderr
    assert "report line" in result.stdout
    assert "report line" in summary.read_text()
