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
job here. `language-lifecycle` is disabled, and `github-config` and
`agent-audit` are security-signal jobs (spec §2.3): none is reported.

The report-only pin-exposure job is deprecated (spec §5.5): a job reports
only whether it worked, and `upstream-refresh` is the path that fixes pin lag.
A lag it cannot fix fails that job, and the failure reaches the operations
queue. docker/pins/report_exposure.py stays, runnable by hand.
"""

import os
import re
import subprocess

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


def test_agent_audit_runs_after_the_config_job():
    # The daily agent audit (epic vergil-project/.github#1384, Task 13): a job
    # named agent-audit, the name hoshin reads it by. It runs after the config
    # job, but a failed config job must not skip it (the epic's ruling N0.14).
    job = _jobs("ops.yml")["agent-audit"]
    assert job["uses"] == "vergil-project/vergil-actions/.github/workflows/ops-agent-audit.yml@v2.1"
    assert job["needs"] == "github-config"
    assert _expr(job["if"]) == "!cancelled()"
    assert job["secrets"] == "inherit"
    assert job["permissions"] == {"contents": "read"}




# The container jobs' identity (epic vergil-project/.github#1494, Task 17,
# spec §5.4; vergil-containers#990). The GHCR proof (vergil-project/.github#1516)
# passed on the Packages API path and failed on the registry push path, so the
# human's scope change on #990 splits the jobs: those that log in to the
# registry keep GITHUB_TOKEN, each a recorded exception. Of the jobs that use
# only the Packages API, the cache warm only reads and runs as the App, with
# no fallback. The cleanup jobs delete, which the Packages API allows only a
# personal access token (classic): run 45635208056 on the App token deleted
# nothing (vergil-containers#1050), so they use GHCR_CLEANUP_TOKEN alone, a
# recorded exception too.
APP_TOKEN_ACTION = "actions/create-github-app-token@v3"
CLEANUP_ACTION = "dataaxiom/ghcr-cleanup-action@"
APP_TOKEN = "${{ steps.app-token.outputs.token }}"
WARM_MISS = "steps.touch.outputs.cache-matched-key == ''"
# (workflow, job, the packages permission its App token asks for, the `if:`
# of its App-token steps: None when every run mints one).
APP_JOBS = [
    ("package-cache-warm.yml", "warm", "read", WARM_MISS),
]
APP_IDS = [f"{w}:{j}" for w, j, _, _ in APP_JOBS]
EXCEPTION_REASON = (
    "GHCR rejects App installation tokens for registry pushes "
    "(`installation not allowed to Write organization package`)"
)
CLEANUP_WORKFLOW = "package-cleanup.yml"
CLEANUP_JOBS = ("cleanup", "reap-aliases")
CLEANUP_TOKEN = "${{ secrets.GHCR_CLEANUP_TOKEN }}"
CLEANUP_EXCEPTION_REASON = (
    "the Packages API accepts only a personal access token (classic), "
    "not an App installation token"
)
PUBLISH = "cd-docker-publish.yml"
# (workflow, job) of every caller of the registry-push workflow.
REGISTRY_JOBS = [
    ("ops.yml", "nightly-rebuild-dev"),
    ("ops.yml", "nightly-rebuild-prod"),
    ("cd.yml", "docker-publish"),
]
REGISTRY_IDS = [j for _, j in REGISTRY_JOBS]
# The inputs main's cd-docker-publish.yml declares, as of v2.1.50 (checked
# against origin/main when vergil-containers#990 was written). A test cannot
# read origin/main: CI's checkout and a worktree mounted into the validation
# container have no such ref. The prod rebuild calls main's copy, so it may
# pass only these, and no secret; develop's copy must declare them too.
MAIN_PUBLISH_INPUTS = {"image-prefix", "no-cache", "ref"}


def _comment_above(text: str, marker: str) -> list[str]:
    """The `#` comment lines directly above the line `marker` starts, joined
    into one line, for each occurrence of `marker` in `text`."""
    lines = text.splitlines()
    blocks = []
    for index, line in enumerate(lines):
        if line != marker:
            continue
        comment = []
        for above in reversed(lines[:index]):
            stripped = above.strip()
            if not stripped.startswith("#"):
                break
            comment.insert(0, stripped.lstrip("#").strip())
        blocks.append(" ".join(comment))
    return blocks


@pytest.mark.parametrize(("workflow", "job_id", "packages", "condition"), APP_JOBS, ids=APP_IDS)
def test_ghcr_jobs_use_app_token(workflow, job_id, packages, condition):
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text())
    job = doc["jobs"][job_id]
    # The App's keys live only in the automation environment.
    assert job["environment"] == "automation"
    # GITHUB_TOKEN has no packages access, so it cannot stand in for the App.
    assert doc["permissions"] == {"contents": "read"}
    assert "permissions" not in job

    steps = job["steps"]
    ids = [s.get("id") for s in steps]
    mint = steps[ids.index("app-token")]
    check = steps[ids.index("app-token-set")]
    assert ids.index("app-token-set") == ids.index("app-token") + 1
    assert mint["uses"] == APP_TOKEN_ACTION
    assert mint["with"] == {
        "app-id": "${{ secrets.APP_CLIENT_ID }}",
        "private-key": "${{ secrets.APP_PRIVATE_KEY }}",
        "permission-packages": packages,
    }
    for step in (mint, check):
        # Never absorbed: a failed mint or an empty token fails the leg.
        assert "continue-on-error" not in step
        assert (_expr(step["if"]) if "if" in step else None) == condition
    assert check["env"] == {"APP_TOKEN": APP_TOKEN}
    for token, code in (("", 1), ("app", 0)):
        result = subprocess.run(
            ["bash", "-e", "-c", check["run"]],
            env={**os.environ, "APP_TOKEN": token},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == code, (job_id, token, result.stdout)
        assert ("::error title=No App token::" in result.stdout) is (code != 0)

    calls = [s for s in steps if str(s.get("uses", "")).startswith(CLEANUP_ACTION)]
    assert calls, job_id
    for call in calls:
        # After the check, and with the App token alone: no `||` fallback.
        assert steps.index(call) > steps.index(check)
        assert call["with"]["token"] == APP_TOKEN
        # A call runs only where the token was minted.
        if condition is not None:
            assert _expr(call["if"]) == condition


@pytest.mark.parametrize("job_id", CLEANUP_JOBS)
def test_cleanup_legs_use_only_the_cleanup_token(job_id):
    doc = yaml.safe_load((WORKFLOWS / CLEANUP_WORKFLOW).read_text())
    job = doc["jobs"][job_id]
    # The token lives only in the automation environment.
    assert job["environment"] == "automation"
    # GITHUB_TOKEN has no packages access, so it cannot stand in for the PAT.
    assert doc["permissions"] == {"contents": "read"}
    assert "permissions" not in job

    steps = job["steps"]
    # No App token: the Packages API refuses it for deletes.
    assert not any(str(s.get("uses", "")).startswith(APP_TOKEN_ACTION.split("@")[0]) for s in steps)
    check = steps[0]
    assert check["id"] == "cleanup-token-set"
    # Never absorbed, and checked on every run: an empty token fails the leg.
    assert "continue-on-error" not in check
    assert "if" not in check
    assert check["env"] == {"CLEANUP_TOKEN": CLEANUP_TOKEN}
    for token, code in (("", 1), ("pat", 0)):
        result = subprocess.run(
            ["bash", "-e", "-c", check["run"]],
            env={**os.environ, "CLEANUP_TOKEN": token},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == code, (job_id, token, result.stdout)
        assert ("::error title=No cleanup token::" in result.stdout) is (code != 0)

    calls = [s for s in steps if str(s.get("uses", "")).startswith(CLEANUP_ACTION)]
    assert len(calls) == 2, job_id
    for call in calls:
        # After the check, and with the PAT alone: no `||` fallback.
        assert steps.index(call) > steps.index(check)
        assert call["with"]["token"] == CLEANUP_TOKEN


def test_cleanup_token_is_read_only_by_package_cleanup():
    # No other workflow reads the PAT, and package-cleanup never falls back
    # to GITHUB_TOKEN or the App for a GHCR call.
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name != CLEANUP_WORKFLOW:
            assert "GHCR_CLEANUP_TOKEN" not in path.read_text(), path.name
    text = (WORKFLOWS / CLEANUP_WORKFLOW).read_text()
    assert "secrets.GITHUB_TOKEN" not in text
    assert "github.token" not in text
    assert "steps.app-token" not in text
    # The App-token dry run was the proof; it is not coming back.
    doc = yaml.safe_load(text)
    on = doc["on"] if "on" in doc else doc[True]
    assert set(on["workflow_dispatch"]["inputs"]) == {"dry_run"}
    # The cache warm stays on the App (test_ghcr_jobs_use_app_token): it only
    # reads, and test_package_cache_warm.py pins that it never deletes.


def test_cleanup_token_is_a_recorded_identity_exception():
    text = (WORKFLOWS / CLEANUP_WORKFLOW).read_text()
    # Beside each of the four GHCR calls' token, with its reason.
    comments = _comment_above(text, f"          token: {CLEANUP_TOKEN}")
    assert len(comments) == 4
    for comment in comments:
        assert "Identity exception" in comment
        assert CLEANUP_EXCEPTION_REASON in comment
    # And in the header, with the run that showed it.
    header = " ".join(
        line.lstrip("#").strip() for line in text.split("\non:\n", 1)[0].splitlines()
    )
    assert "Identity exception" in header
    assert CLEANUP_EXCEPTION_REASON in header
    assert "45635208056" in header


@pytest.mark.parametrize(("workflow", "job_id"), REGISTRY_JOBS, ids=REGISTRY_IDS)
def test_registry_jobs_keep_github_token(workflow, job_id):
    text = (WORKFLOWS / workflow).read_text()
    job = yaml.safe_load(text)["jobs"][job_id]
    assert job["uses"].split("@")[0].endswith(f".github/workflows/{PUBLISH}")
    # No App path: no secret passed, and no input beyond the publish's own.
    assert "secrets" not in job
    assert set(job["with"]) <= MAIN_PUBLISH_INPUTS
    # The exception is recorded beside the job, with its reason.
    (comment,) = _comment_above(text, f"  {job_id}:")
    assert "Identity exception" in comment
    assert EXCEPTION_REASON in comment


def test_registry_publish_logs_in_with_github_token():
    text = (WORKFLOWS / PUBLISH).read_text()
    doc = yaml.safe_load(text)
    assert "secrets" not in doc[True]["workflow_call"]
    assert APP_TOKEN_ACTION.split("@")[0] not in text
    logins = [
        step
        for job in doc["jobs"].values()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("docker/login-action@")
    ]
    # One login per push job (the YAML anchors share the build and publish
    # steps across tiers), each with GITHUB_TOKEN.
    assert logins
    for login in logins:
        assert login["with"]["password"] == "${{ secrets.GITHUB_TOKEN }}"
    # Each login step, as written (two: the build and publish anchors),
    # names the exception and its reason.
    comments = _comment_above(text, "      - name: Log in to GHCR")
    assert len(comments) == 2
    for comment in comments:
        assert "Identity exception" in comment
        assert EXCEPTION_REASON in comment


def test_prod_rebuild_passes_only_what_main_declares():
    job = _jobs("ops.yml")["nightly-rebuild-prod"]
    assert job["uses"] == f"vergil-project/vergil-containers/.github/workflows/{PUBLISH}@main"
    # Passing an input or secret main's copy does not declare is a workflow
    # error that fails every job in ops.yml.
    assert "secrets" not in job
    assert set(job["with"]) <= MAIN_PUBLISH_INPUTS
    declared = yaml.safe_load((WORKFLOWS / PUBLISH).read_text())[True]["workflow_call"]
    assert MAIN_PUBLISH_INPUTS <= set(declared["inputs"])
