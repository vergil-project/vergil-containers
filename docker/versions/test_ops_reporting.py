"""The reporting jobs of this repo's unattended jobs (epic
vergil-project/.github#1494, Task 8).

Each unattended job here reports its result to the org's operations queue
through vergil-actions' `ops-report` action: a final job that runs whatever
happened (`always()`), reads `needs.<job>.result` of every GitHub job that
makes up the named job, and passes them to the action under the job's stable
name (spec §3, §4.1). The action itself mints the App token only on
refs/heads/develop and turns the results into one report (spec §5.3).

The jobs reported by vergil-actions' shared workflows (`branch-sweep` and
`upstream-refresh`, called from ops.yml, and `docs-deploy-develop`, called
from cd.yml) report from inside those workflows, so they have no reporting
job here. `language-lifecycle` is disabled and `github-config` is a
security-signal job (spec §2.3): neither is reported.

The report-only pin-exposure job is deprecated (spec §5.5): a job reports
only whether it worked, and `upstream-refresh` is the path that fixes pin lag.
A lag it cannot fix fails that job, and the failure reaches the operations
queue. docker/pins/report_exposure.py stays, runnable by hand.
"""

import re

import pytest
import yaml

import frozen

WORKFLOWS = frozen.LIVE_ROOT / ".github" / "workflows"
ACTION_PATH = "vergil-project/vergil-actions/actions/ops/report"
ACTION = f"{ACTION_PATH}@v2.1"
CHECKOUT = "actions/checkout@v6"

# (workflow, reporting job, stable name, every GitHub job of that name).
REPORTS = [
    ("ops.yml", "report-nightly-rebuild-dev", "nightly-rebuild-dev", ["nightly-rebuild-dev"]),
    ("ops.yml", "report-nightly-rebuild-prod", "nightly-rebuild-prod", ["nightly-rebuild-prod"]),
    ("cd.yml", "report-image-publish", "image-publish", ["docker-publish"]),
    ("package-cleanup.yml", "report", "package-cleanup", ["cleanup", "reap-aliases"]),
    ("package-cache-warm.yml", "report", "package-cache-warm", ["warm"]),
]
IDS = [stable for _, _, stable, _ in REPORTS]
# Workflows that keep a run-level concurrency group, which their reporting
# job sits inside, with the reason beside it (vergil-containers#1010).
RUN_LEVEL_GROUPS = {"package-cleanup.yml", "package-cache-warm.yml"}


def _jobs(workflow: str) -> dict:
    return yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"]


def _expr(value: str) -> str:
    """The expression inside `${{ }}`, or the bare `if:` value as written."""
    value = " ".join(str(value).split())
    match = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", value)
    return match.group(1) if match else value


def _report_steps(job: dict) -> list[dict]:
    # A reusable-workflow call job has no steps.
    return [s for s in job.get("steps", []) if str(s.get("uses", "")).startswith(f"{ACTION_PATH}@")]


def _report_step(job: dict) -> dict:
    steps = _report_steps(job)
    assert len(steps) == 1, f"expected one ops-report step, found {len(steps)}"
    return steps[0]


@pytest.mark.parametrize(("workflow", "job_id", "stable", "needs"), REPORTS, ids=IDS)
def test_each_job_has_a_reporting_job(workflow, job_id, stable, needs):
    jobs = _jobs(workflow)
    assert job_id in jobs, f"{workflow} has no {job_id} job"
    job = jobs[job_id]
    # Every GitHub job of the name exists, and the reporting job waits on all.
    for name in needs:
        assert name in jobs, f"{workflow} has no {name} job"
    job_needs = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
    assert sorted(job_needs) == sorted(needs)
    # Runs whatever the reported jobs did: a failed or cancelled job is
    # exactly what must be reported.
    condition = _expr(job["if"])
    if stable == "image-publish":
        # Plus the release-push skip, pinned below.
        assert condition.startswith("always() && ")
    else:
        assert condition == "always()"
    step = _report_step(job)
    assert step["with"]["job"] == stable
    assert step["with"]["results"] == ",".join(
        f"${{{{ needs.{name}.result }}}}" for name in needs
    )
    assert step["with"]["app-client-id"] == "${{ secrets.APP_CLIENT_ID }}"
    assert step["with"]["app-private-key"] == "${{ secrets.APP_PRIVATE_KEY }}"


@pytest.mark.parametrize(("workflow", "job_id", "stable", "needs"), REPORTS, ids=IDS)
def test_reporting_job_is_plain(workflow, job_id, stable, needs):
    job = _jobs(workflow)[job_id]
    # The App token carries the job's GitHub access; GITHUB_TOKEN reads only.
    assert job["permissions"] == {"contents": "read"}


@pytest.mark.parametrize(("workflow", "job_id", "stable", "needs"), REPORTS, ids=IDS)
def test_reporting_job_sits_in_no_concurrency_group(workflow, job_id, stable, needs):
    # A concurrency group keeps one pending run and cancels the older one,
    # which would drop a failure report (plan, Global Constraints).
    text = (WORKFLOWS / workflow).read_text()
    doc = yaml.safe_load(text)
    assert "concurrency" not in doc["jobs"][job_id]
    if "concurrency" not in doc:
        return
    # A run-level group puts the reporting job inside it too. Only the
    # workflows that must keep one have it (vergil-containers#1010), never
    # cancelling a run in flight, with the trade-off recorded beside it.
    assert workflow in RUN_LEVEL_GROUPS
    assert doc["concurrency"]["cancel-in-progress"] is False
    block = text.split("\nconcurrency:\n", 1)[0].rsplit("\n\n", 1)[-1]
    comment = " ".join(line.lstrip("#").strip() for line in block.splitlines())
    assert "The group stays at run level (issue #1010)." in comment
    assert "The trade-off with failure reporting:" in comment


def test_only_the_named_jobs_report():
    for workflow in sorted({w for w, _, _, _ in REPORTS}):
        reporting = {job_id for job_id, job in _jobs(workflow).items() if _report_steps(job)}
        expected = {job_id for w, job_id, _, _ in REPORTS if w == workflow}
        assert reporting == expected, workflow


def test_image_publish_report_skips_release_pushes():
    # A push to main and a release's develop back-merge report nothing: the
    # release records of epic vergil-project/.github#1440 track those (spec
    # §4.1). The back-merge is the merge commit of a release/* branch's PR.
    condition = _expr(_jobs("cd.yml")["report-image-publish"]["if"])
    assert "github.ref != 'refs/heads/main'" in condition
    assert "!(startsWith(github.event.head_commit.message, 'Merge pull request #')" in condition
    assert (
        "contains(github.event.head_commit.message, format(' from {0}/release/', github.repository_owner)))"
        in condition
    )


@pytest.mark.parametrize(("workflow", "job_id", "stable", "needs"), REPORTS, ids=IDS)
def test_reporting_uses_ops_report_action_at_v2_1(workflow, job_id, stable, needs):
    assert _report_step(_jobs(workflow)[job_id])["uses"] == ACTION


@pytest.mark.parametrize(("workflow", "job_id", "stable", "needs"), REPORTS, ids=IDS)
def test_reporting_job_checks_out_first(workflow, job_id, stable, needs):
    # Setting up Vergil inside the action reads the workspace's vergil.toml.
    steps = _jobs(workflow)[job_id]["steps"]
    assert steps[0]["uses"] == CHECKOUT
    assert steps[0]["with"]["persist-credentials"] is False
    assert steps.index(_report_step(_jobs(workflow)[job_id])) > 0


@pytest.mark.parametrize(("workflow", "job_id", "stable", "needs"), REPORTS, ids=IDS)
def test_reporting_step_sets_trusted_env(workflow, job_id, stable, needs):
    # A composite action cannot read `vars`, so the calling step delivers the
    # trust layer's inputs (the vergil-project/vergil-actions#1359 convention).
    env = _report_step(_jobs(workflow)[job_id]).get("env", {})
    assert env.get("VRG_TRUSTED_AUTHORS") == "${{ vars.VRG_TRUSTED_AUTHORS }}"
    assert env.get("VRG_AUTOMATION_APP") == "${{ vars.VRG_AUTOMATION_APP }}"


def test_pin_exposure_is_not_a_job():
    assert "pin-exposure" not in _jobs("ops.yml")


def test_upstream_refresh_is_a_job():
    assert "upstream-refresh" in _jobs("ops.yml")
