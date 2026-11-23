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


def test_cleanup_and_reap_never_run_at_the_same_time():
    # Issue #911: overlapping legs on one package made reap-aliases read
    # manifests cleanup was deleting, and fail with 404. reap-aliases must wait
    # for the whole cleanup job, and these must be the only two deleting jobs.
    # The third, `report`, deletes nothing: it reports the run to the
    # operations queue (test_ops_reporting.py pins it).
    jobs = _workflow()["jobs"]
    assert set(jobs) == {*JOBS, "report"}
    assert not any(ACTION.match(str(s.get("uses", ""))) for s in jobs["report"]["steps"])
    assert "needs" not in jobs["cleanup"]
    assert jobs["reap-aliases"]["needs"] in ("cleanup", ["cleanup"])


def test_reap_still_runs_after_a_failed_cleanup_leg():
    # The default `success()` would skip every reap leg when one cleanup leg
    # failed; `!cancelled()` still stops it when the run is cancelled.
    assert _workflow()["jobs"]["reap-aliases"]["if"] == "${{ !cancelled() }}"


def _on() -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    wf = _workflow()
    return wf["on"] if "on" in wf else wf[True]


# Issue #912: live by default. Only a manual run that asks for a preview is a
# dry run; a scheduled run, or a manual run with default inputs, deletes.
LIVE_DRY_RUN = "${{ github.event_name == 'workflow_dispatch' && inputs.dry_run == true }}"


def test_manual_run_deletes_unless_a_preview_is_asked_for():
    dry_run = _on()["workflow_dispatch"]["inputs"]["dry_run"]
    assert dry_run["type"] == "boolean"
    assert dry_run["default"] is False


def test_schedule_is_not_gated_by_a_repository_variable():
    assert "schedule" in _on()
    # Nothing outside git may arm or disarm the deletions: no `vars.` read
    # anywhere but the report job, whose only reads are the trust layer's
    # inputs to its ops-report step (test_ops_reporting.py).
    wf = _workflow()
    gating = {key: value for key, value in wf.items() if key != "jobs"}
    gating["jobs"] = {job: wf["jobs"][job] for job in JOBS}
    assert "vars." not in yaml.safe_dump(gating)
    report_vars = set(re.findall(r"vars\.\w+", yaml.safe_dump(wf["jobs"]["report"])))
    assert report_vars == {"vars.VRG_TRUSTED_AUTHORS", "vars.VRG_AUTOMATION_APP"}


@pytest.mark.parametrize("job", JOBS)
@pytest.mark.parametrize("step_id", ["attempt1", "attempt2"])
def test_dry_run_only_for_a_manual_preview(job, step_id):
    assert _step(job, step_id=step_id)["with"]["dry-run"] == LIVE_DRY_RUN


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
    # dry-run expression; drift here would let a retry delete when attempt 1
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
        # A 404 is named too, so a race is not read as a rate limit (#911).
        assert "Request failed with status code 404" in result.stdout
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
    # Issue #911: a 404 is a deletion race, not a rate limit, and says so.
    assert "Request failed with status code 404" in line
    assert "not a rate limit" in line
    assert "max-parallel" in line
    assert not (tmp_path / "slept").exists()


@pytest.mark.parametrize("step_id", ["attempt1", "attempt2"])
def test_untagged_prune_spares_in_flight_publish_digests(step_id):
    # cd-docker-publish.yml pushes per-arch images by digest, untagged, and
    # tags them only at the stitch once every build in the run is done
    # (vergil-containers#515); the prune must not reap them in between.
    with_ = _step("cleanup", step_id=step_id)["with"]
    assert with_["delete-untagged"] is True
    assert with_["older-than"] == "24 hours"
