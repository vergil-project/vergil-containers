"""Where this repo's workflows read their write-capable secrets (epic
vergil-project/.github#1384, Task 3c: vergil-containers#1014).

The automation App keys (`APP_CLIENT_ID`, `APP_PRIVATE_KEY`) and every other
secret that can write or act (`GHCR_CLEANUP_TOKEN`) live only in the repo's
`automation` deployment environment, which only `develop` and `main` may
deploy to. A job reads an environment secret only when it declares the
environment, so every job that reads one itself declares `environment:
automation`.

A job that calls a reusable workflow cannot declare an environment, and
environment secrets reach a reusable workflow in another repository only when
the caller passes `secrets: inherit`. So each caller of a vergil-actions
workflow that reads the App keys inherits, and nothing else does: inheriting
hands the callee every secret the caller can read. vrg-validate's
`secrets-inherit` check enforces the allow-list fleet-wide; these tests pin
this repo's callers to exactly that set.
"""

import re

import pytest
import yaml

import frozen

WORKFLOWS = frozen.LIVE_ROOT / ".github" / "workflows"
ENVIRONMENT = "automation"
# The secrets only the automation environment holds.
WRITE_SECRETS = ("APP_CLIENT_ID", "APP_PRIVATE_KEY", "GHCR_CLEANUP_TOKEN")
SECRET_REF = re.compile(r"secrets\.(" + "|".join(WRITE_SECRETS) + r")\b")

# (workflow, job) of every job that reads a write-capable secret itself.
READERS = [
    ("cd.yml", "report-image-publish"),
    ("ops.yml", "language-lifecycle"),
    ("ops.yml", "report-nightly-rebuild-dev"),
    ("ops.yml", "report-nightly-rebuild-prod"),
    ("package-cache-warm.yml", "report"),
    ("package-cleanup.yml", "cleanup"),
    ("package-cleanup.yml", "reap-aliases"),
    ("package-cleanup.yml", "report"),
]

# (workflow, job, reusable workflow) of every caller of an App-key workflow.
INHERITORS = [
    ("cd.yml", "docs", "cd-docs.yml"),
    ("cd.yml", "release", "cd-release.yml"),
    ("epic-rollup.yml", "epic-rollup", "ops-epic-rollup.yml"),
    ("ops.yml", "github-config", "ops-github-config.yml"),
    ("ops.yml", "upstream-refresh", "ops-upstream-refresh.yml"),
]
ACTIONS_WORKFLOWS = "vergil-project/vergil-actions/.github/workflows/"


def _workflow_files() -> list[str]:
    return sorted(p.name for p in WORKFLOWS.glob("*.yml"))


def _jobs(workflow: str) -> dict:
    return yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"]


@pytest.mark.parametrize(("workflow", "job_id"), READERS, ids=[f"{w}:{j}" for w, j in READERS])
def test_reader_declares_the_automation_environment(workflow, job_id):
    job = _jobs(workflow)[job_id]
    assert job.get("environment") == ENVIRONMENT, f"{workflow}:{job_id}"


def test_every_reader_is_listed():
    # A job that reads a write-capable secret without the environment sees it
    # unset once the secret lives only there, so none may be missed.
    found = set()
    for workflow in _workflow_files():
        for job_id, job in _jobs(workflow).items():
            if "uses" in job:
                continue
            if SECRET_REF.search(yaml.safe_dump(job)):
                found.add((workflow, job_id))
    assert found == set(READERS)


def test_only_readers_declare_the_environment():
    declaring = {
        (workflow, job_id)
        for workflow in _workflow_files()
        for job_id, job in _jobs(workflow).items()
        if "environment" in job
    }
    assert declaring == set(READERS)


@pytest.mark.parametrize(
    ("workflow", "job_id", "callee"), INHERITORS, ids=[f"{w}:{j}" for w, j, _ in INHERITORS]
)
def test_app_key_caller_inherits(workflow, job_id, callee):
    job = _jobs(workflow)[job_id]
    assert job["uses"] == f"{ACTIONS_WORKFLOWS}{callee}@v2.1"
    assert job["secrets"] == "inherit", f"{workflow}:{job_id}"


def test_only_app_key_callers_inherit():
    inheriting = {
        (workflow, job_id)
        for workflow in _workflow_files()
        for job_id, job in _jobs(workflow).items()
        if job.get("secrets") == "inherit"
    }
    assert inheriting == {(w, j) for w, j, _ in INHERITORS}


def test_no_caller_maps_a_write_secret():
    # An explicit map reads the secret in the calling job, which cannot
    # declare the environment, so it would pass the callee nothing.
    for workflow in _workflow_files():
        for job_id, job in _jobs(workflow).items():
            if "uses" in job and isinstance(job.get("secrets"), dict):
                assert not SECRET_REF.search(yaml.safe_dump(job["secrets"])), (
                    f"{workflow}:{job_id}"
                )
