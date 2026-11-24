"""Where this repo's workflows read their write-capable secrets (epic
vergil-project/.github#1384, Task 3c: vergil-containers#1014).

The automation App keys (`APP_CLIENT_ID`, `APP_PRIVATE_KEY`) and every other
secret that can write or act (`GHCR_CLEANUP_TOKEN`) live only in the repo's
`automation` deployment environment, which only `develop` and `main` may
deploy to. A job reads an environment secret only when it declares the
environment, so every job that reads one itself declares `environment:
automation`. The publish workflow's push jobs read the App keys only on an
App login to GHCR (vergil-containers#1029), so they declare the environment
only then, in the one conditional form `_declares_the_environment` accepts.

A job that calls a reusable workflow cannot declare an environment, so it
hands the callee its secrets: all of them with `secrets: inherit`, or the ones
an explicit `secrets:` map names. Each caller of a vergil-actions workflow
that reads the App keys inherits, the route the fleet has chosen for in-org
callers of those workflows, and nothing else does: inheriting hands the callee
every secret the caller can read. vrg-validate's
`secrets-inherit` check enforces the allow-list fleet-wide; these tests pin
this repo's callers to exactly that set.

A call job may also pass a secret by name, in an explicit `secrets:` map, and
that reaches the called workflow even when the secret lives only in an
environment: the called workflow's jobs that declare the environment read it.
logical-minds-foundry/mq-gateway-replay-lab run 45390389192 was green with the
org-level App keys hidden from that repo, the keys passed by name from a call
job, and GitHub's reusable-workflow docs say a secret can be passed by name
"even if it only exists in the environment". By the human's ruling N0.16 on
epic vergil-project/.github#1384, a call job here may pass exactly the two App
keys by name to this repo's own workflow, as long as every job there that
reads them declares `environment: automation`. By the human's ruling on R2 of
the merge review of vergil-containers#1030, that workflow may be called by its
local path or as this repo's workflow at exactly `@main` (the prod nightly
rebuild runs main's copy, issue #731); the check reads the local copy, which
can run ahead of main's between releases. A prod login then fails loudly
until the release, and no key is exposed. Every other map of a write-capable
secret, and every other repository or ref, is refused.
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

# (workflow, job) of every job that reads the App keys only when an input asks
# for it, and declares the environment only then (vergil-containers#1029): the
# publish workflow's push jobs, on an App login to GHCR.
APP_LOGIN_ENVIRONMENT = "${{ inputs.app-registry-login && 'automation' || '' }}"
CONDITIONAL_READERS = [
    ("cd-docker-publish.yml", f"{kind}-{tier}") for tier in range(3) for kind in ("build", "publish")
]

# (workflow, job, reusable workflow) of every caller of an App-key workflow.
INHERITORS = [
    ("cd.yml", "docs", "cd-docs.yml"),
    ("cd.yml", "release", "cd-release.yml"),
    ("epic-rollup.yml", "epic-rollup", "ops-epic-rollup.yml"),
    ("ops.yml", "github-config", "ops-github-config.yml"),
    ("ops.yml", "upstream-refresh", "ops-upstream-refresh.yml"),
    ("ops.yml", "agent-audit", "ops-agent-audit.yml"),
]
ACTIONS_WORKFLOWS = "vergil-project/vergil-actions/.github/workflows/"


# The by-name map a call job may pass to this repo's own workflow
# (ruling N0.16 on epic vergil-project/.github#1384).
APP_KEYS = ("APP_CLIENT_ID", "APP_PRIVATE_KEY")
_FILE = r"([A-Za-z0-9_.-]+\.ya?ml)"
LOCAL_WORKFLOW = re.compile(r"\./\.github/workflows/" + _FILE)
# This repo's own workflow at main (the R2 ruling of vergil-containers#1030).
OWN_WORKFLOWS = "vergil-project/vergil-containers/.github/workflows/"
OWN_AT_MAIN = re.compile(re.escape(OWN_WORKFLOWS) + _FILE + r"@main")
# A read of a named secret, by property or by index.
_NAMED = r"secrets\s*(?:\.\s*({names})\b|\[\s*['\"]({names})['\"]\s*\])"
WRITE_READ = re.compile(_NAMED.format(names="|".join(WRITE_SECRETS)))
APP_KEY_READ = re.compile(_NAMED.format(names="|".join(APP_KEYS)))
# A read of the whole secrets context, as in toJSON(secrets).
WHOLE_SECRETS = re.compile(r"\bsecrets\b(?!\s*[.\[])")
EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
# The one conditional form a key-reading job may use: the automation
# environment when the condition holds, none otherwise.
CONDITIONAL_ENVIRONMENT = re.compile(
    r"\$\{\{\s*(?P<condition>[^'\"|]+?)\s*&&\s*'" + ENVIRONMENT + r"'\s*\|\|\s*''\s*\}\}"
)


def _expressions(node, key=None):
    """Every expression in a job: the `${{ }}` spans, and each `if:` whole."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _expressions(v, k)
    elif isinstance(node, list):
        for item in node:
            yield from _expressions(item, key)
    elif isinstance(node, str):
        if key == "if":
            yield node
        yield from EXPRESSION.findall(node)


def _reads(job: dict, named: re.Pattern) -> bool:
    """Whether a job reads a secret `named` matches, or all of them."""
    if job.get("secrets") == "inherit":
        return True
    return any(
        named.search(expr) or WHOLE_SECRETS.search(expr) for expr in _expressions(job)
    )


def _declares_the_environment(job: dict) -> bool:
    environment = job.get("environment")
    if isinstance(environment, dict):
        environment = environment.get("name")
    if environment == ENVIRONMENT:
        return True
    return isinstance(environment, str) and bool(
        CONDITIONAL_ENVIRONMENT.fullmatch(environment)
    )


def _map_refusal(root, job: dict) -> str | None:
    """Why a call job's explicit secrets map is refused, or None if it is not.

    A map that reads no write secret is not this test's concern. One that
    does must pass only the App keys, each by its own name, to a workflow in
    `root` (this repo's .github/workflows), called by its local path or as
    this repo's workflow at exactly @main, and every job in `root`'s copy
    that reads a key must declare the automation environment.
    """
    secrets = job.get("secrets")
    if "uses" not in job or not isinstance(secrets, dict):
        return None
    values = [str(v) for v in secrets.values()]
    if not any(WRITE_READ.search(v) or WHOLE_SECRETS.search(v) for v in values):
        return None
    local = LOCAL_WORKFLOW.fullmatch(job["uses"]) or OWN_AT_MAIN.fullmatch(job["uses"])
    if not local or not (root / local.group(1)).is_file():
        return f"maps a write secret to {job['uses']}, not this repo's own workflow"
    for name, value in secrets.items():
        if name not in APP_KEYS:
            return f"maps {name}, not an App key"
        if not re.fullmatch(r"\$\{\{\s*secrets\." + name + r"\s*\}\}", str(value)):
            return f"maps {name} from {value}, not by its own name"
    callee = yaml.safe_load((root / local.group(1)).read_text())["jobs"]
    for callee_id, callee_job in callee.items():
        if not _reads(callee_job, APP_KEY_READ):
            continue
        if "uses" in callee_job:
            return f"{local.group(1)}:{callee_id} passes an App key on to {callee_job['uses']}"
        if not _declares_the_environment(callee_job):
            return f"{local.group(1)}:{callee_id} reads an App key without environment: {ENVIRONMENT}"
    return None


def _workflow_files() -> list[str]:
    return sorted(p.name for p in WORKFLOWS.glob("*.yml"))


def _jobs(workflow: str) -> dict:
    return yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"]


@pytest.mark.parametrize(("workflow", "job_id"), READERS, ids=[f"{w}:{j}" for w, j in READERS])
def test_reader_declares_the_automation_environment(workflow, job_id):
    job = _jobs(workflow)[job_id]
    assert job.get("environment") == ENVIRONMENT, f"{workflow}:{job_id}"


@pytest.mark.parametrize(
    ("workflow", "job_id"), CONDITIONAL_READERS, ids=[f"{w}:{j}" for w, j in CONDITIONAL_READERS]
)
def test_conditional_reader_declares_the_environment_with_its_input(workflow, job_id):
    job = _jobs(workflow)[job_id]
    assert job.get("environment") == APP_LOGIN_ENVIRONMENT, f"{workflow}:{job_id}"
    assert _declares_the_environment(job), f"{workflow}:{job_id}"


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
    assert found == set(READERS) | set(CONDITIONAL_READERS)


def test_only_readers_declare_the_environment():
    declaring = {
        (workflow, job_id)
        for workflow in _workflow_files()
        for job_id, job in _jobs(workflow).items()
        if "environment" in job
    }
    assert declaring == set(READERS) | set(CONDITIONAL_READERS)


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


# A synthetic local reusable workflow whose push job reads both App keys.
CALLEE = """\
on:
  workflow_call:
    secrets:
      APP_CLIENT_ID:
        required: false
      APP_PRIVATE_KEY:
        required: false
jobs:
  versions:
    runs-on: ubuntu-24.04
    steps:
      - run: echo versions
  push:
    runs-on: ubuntu-24.04
    environment: ENVIRONMENT
    steps:
      - uses: actions/create-github-app-token@v2
        with:
          client-id: ${{ secrets.APP_CLIENT_ID }}
          private-key: ${{ secrets.APP_PRIVATE_KEY }}
"""
APP_KEY_MAP = {
    "APP_CLIENT_ID": "${{ secrets.APP_CLIENT_ID }}",
    "APP_PRIVATE_KEY": "${{ secrets.APP_PRIVATE_KEY }}",
}
CONDITIONAL = "\"${{ inputs.app-registry-login && 'automation' || '' }}\""


def _caller(uses="./.github/workflows/callee.yml", secrets=None) -> dict:
    return {"uses": uses, "secrets": APP_KEY_MAP if secrets is None else secrets}


def _with_callee(tmp_path, environment="automation", extra=""):
    text = CALLEE.replace("ENVIRONMENT", environment) + extra
    (tmp_path / "callee.yml").write_text(text)
    return tmp_path


def test_map_allowed_by_name_to_a_local_environment_callee(tmp_path):
    assert _map_refusal(_with_callee(tmp_path), _caller()) is None


def test_map_of_one_app_key_allowed(tmp_path):
    caller = _caller(secrets={"APP_CLIENT_ID": "${{ secrets.APP_CLIENT_ID }}"})
    assert _map_refusal(_with_callee(tmp_path), caller) is None


def test_map_allowed_to_a_conditional_environment_callee(tmp_path):
    assert _map_refusal(_with_callee(tmp_path, CONDITIONAL), _caller()) is None


def test_map_without_a_write_secret_is_not_checked(tmp_path):
    caller = _caller(
        uses="other/repo/.github/workflows/x.yml@v1",
        secrets={"TOKEN": "${{ secrets.GITHUB_TOKEN }}"},
    )
    assert _map_refusal(tmp_path, caller) is None


@pytest.mark.parametrize(
    "secrets",
    [
        {"GHCR_CLEANUP_TOKEN": "${{ secrets.GHCR_CLEANUP_TOKEN }}"},
        {**APP_KEY_MAP, "GHCR_CLEANUP_TOKEN": "${{ secrets.GHCR_CLEANUP_TOKEN }}"},
        {"TOKEN": "${{ secrets['GHCR_CLEANUP_TOKEN'] }}"},
        {"APP_CLIENT_ID": "${{ secrets.APP_PRIVATE_KEY }}"},
        {"KEY": "${{ secrets.APP_PRIVATE_KEY }}"},
        {"APP_CLIENT_ID": "${{ secrets.APP_CLIENT_ID || secrets.GITHUB_TOKEN }}"},
        {**APP_KEY_MAP, "OTHER": "${{ secrets.OTHER }}"},
    ],
    ids=[
        "other-write-secret",
        "app-keys-plus-other-write-secret",
        "bracket-form",
        "swapped-name",
        "new-name",
        "expression",
        "app-keys-plus-non-write-secret",
    ],
)
def test_map_of_any_other_write_secret_refused(tmp_path, secrets):
    assert _map_refusal(_with_callee(tmp_path), _caller(secrets=secrets))


def test_map_allowed_to_the_own_workflow_at_main(tmp_path):
    caller = _caller(uses=f"{OWN_WORKFLOWS}callee.yml@main")
    assert _map_refusal(_with_callee(tmp_path), caller) is None


def test_map_to_the_own_workflow_at_main_checks_the_local_copy(tmp_path):
    caller = _caller(uses=f"{OWN_WORKFLOWS}callee.yml@main")
    assert _map_refusal(_with_callee(tmp_path, "other"), caller)


@pytest.mark.parametrize(
    "uses",
    [
        f"{OWN_WORKFLOWS}callee.yml@develop",
        f"{OWN_WORKFLOWS}callee.yml@v1.2.3",
        f"{OWN_WORKFLOWS}callee.yml@main2",
        f"{OWN_WORKFLOWS}callee.yml",
        f"{OWN_WORKFLOWS}missing.yml@main",
        "vergil-project/vergil-containers-fork/.github/workflows/callee.yml@main",
        "other-org/vergil-containers/.github/workflows/callee.yml@main",
        "vergil-project/vergil-actions/.github/workflows/callee.yml@v2.1",
        "./.github/workflows/../callee.yml",
        "./.github/workflows/missing.yml",
    ],
    ids=[
        "own-repo-other-branch",
        "own-repo-tag",
        "own-repo-ref-prefix",
        "own-repo-no-ref",
        "own-repo-missing-file",
        "other-repo-same-prefix",
        "other-org-same-name",
        "other-repo",
        "path-escape",
        "missing-file",
    ],
)
def test_map_to_another_workflow_or_ref_refused(tmp_path, uses):
    assert _map_refusal(_with_callee(tmp_path), _caller(uses=uses))


@pytest.mark.parametrize(
    "environment",
    [
        "other",
        "\"${{ inputs.app-registry-login && 'other' || '' }}\"",
        "\"${{ inputs.app-registry-login || 'automation' }}\"",
        "{name: other}",
    ],
    ids=["other", "conditional-other", "not-the-one-if-form", "mapping-other"],
)
def test_map_to_a_reader_in_another_environment_refused(tmp_path, environment):
    assert _map_refusal(_with_callee(tmp_path, environment), _caller())


def test_map_to_a_reader_without_the_environment_refused(tmp_path):
    root = _with_callee(tmp_path)
    callee = root / "callee.yml"
    callee.write_text(callee.read_text().replace("    environment: automation\n", ""))
    assert _map_refusal(root, _caller())


def test_map_to_a_whole_secrets_reader_without_the_environment_refused(tmp_path):
    extra = """\
  dump:
    runs-on: ubuntu-24.04
    steps:
      - run: echo '${{ toJSON(secrets) }}'
"""
    assert _map_refusal(_with_callee(tmp_path, extra=extra), _caller())


def test_map_to_a_callee_that_passes_a_key_on_refused(tmp_path):
    extra = """\
  nested:
    uses: ./.github/workflows/other.yml
    secrets:
      APP_PRIVATE_KEY: ${{ secrets.APP_PRIVATE_KEY }}
"""
    assert _map_refusal(_with_callee(tmp_path, extra=extra), _caller())


def test_no_caller_maps_a_write_secret_but_the_app_keys_by_name():
    # A by-name map reaches the called workflow's environment-declaring jobs
    # (mq-gateway-replay-lab run 45390389192), so the two App keys may go by
    # name to this repo's own workflow (local, or at @main) whose key
    # readers declare the environment.
    # No other write secret is ever mapped.
    refusals = [
        f"{workflow}:{job_id}: {refusal}"
        for workflow in _workflow_files()
        for job_id, job in _jobs(workflow).items()
        if (refusal := _map_refusal(WORKFLOWS, job))
    ]
    assert refusals == []
