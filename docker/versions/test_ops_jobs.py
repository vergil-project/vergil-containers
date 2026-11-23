"""The jobs of .github/workflows/ops.yml.

The report-only pin-exposure job is deprecated (epic
vergil-project/.github#1494, spec §5.5): a job reports only whether it worked,
and `upstream-refresh` is the path that fixes pin lag. A lag it cannot fix
fails that job, and the failure reaches the operations queue.
docker/pins/report_exposure.py stays, runnable by hand.
"""

import yaml

import frozen

WORKFLOW = frozen.LIVE_ROOT / ".github" / "workflows" / "ops.yml"


def _jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def test_pin_exposure_is_not_a_job():
    assert "pin-exposure" not in _jobs()


def test_upstream_refresh_is_a_job():
    assert "upstream-refresh" in _jobs()
