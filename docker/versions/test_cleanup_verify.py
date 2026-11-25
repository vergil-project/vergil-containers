"""The check that package-cleanup's legs deleted what they set out to delete
(vergil-containers#1051, docker/versions/cleanup_verify.py).

The fixtures copy the log lines dataaxiom/ghcr-cleanup-action v1.2.2 writes
(src/package-repo.ts): " deleting package id: <id> digest: <digest>" before
each delete, and, for a delete answered 404, the warning "The package
"<name>" version id <id> wasn't found while trying to delete it; treating as
already deleted." As the Actions job log has them: a timestamp first, and a
warning marked `##[warning]`.
"""

import json

import pytest
import yaml

import cleanup_verify
import frozen

WORKFLOW = frozen.LIVE_ROOT / ".github" / "workflows" / "package-cleanup.yml"
STAMP = "2026-11-25T12:00:00.0000000Z"


def _deleting(version_id: int, label: str = "linux/amd64") -> str:
    return f"{STAMP}  deleting package id: {version_id} digest: sha256:{version_id:064x} {label}"


def _not_found(version_id: int, package: str = "dev-base") -> str:
    return (
        f'{STAMP} ##[warning]The package "{package}" version id {version_id} '
        "wasn't found while trying to delete it; treating as already deleted."
    )


def _never_present(package: str, version_id: int) -> bool:
    raise AssertionError(f"asked whether {package} {version_id} is present")


# Run 45635208056: every delete answered "not found".
ALL_NOT_FOUND = "\n".join(
    [f"{STAMP} Run dataaxiom/ghcr-cleanup-action@v1.2.2"]
    + [line for i in (101, 102, 103) for line in (_deleting(i), _not_found(i))]
)
# A healthy run: every delete went through.
NORMAL = "\n".join(
    [f"{STAMP} Run dataaxiom/ghcr-cleanup-action@v1.2.2"]
    + [_deleting(i) for i in (201, 202, 203)]
    + [f"{STAMP} manifest cache: 3/3 digests served from cache (100%)"]
)
# Two deletes went through and one was raced (#911).
RACED = "\n".join([_deleting(301), _deleting(302), _deleting(303), _not_found(303)])


def test_all_not_found_fails_naming_the_package_and_the_token():
    log = cleanup_verify.parse_log(ALL_NOT_FOUND)
    assert log.planned == {101, 102, 103}
    assert log.not_found == {101, 102, 103}
    (error,) = cleanup_verify.judge("cleanup: dev-base", "dev-base", log, _never_present)
    assert error.startswith("::error title=Package cleanup deleted nothing::")
    assert "dev-base" in error
    assert "all 3 deletes" in error
    assert "the token could not delete" in error


def test_normal_deletions_pass():
    log = cleanup_verify.parse_log(NORMAL)
    assert log.planned == {201, 202, 203}
    assert log.not_found == set()
    assert cleanup_verify.judge("cleanup: dev-base", "dev-base", log, _never_present) == []


def test_a_raced_delete_whose_version_is_gone_passes():
    log = cleanup_verify.parse_log(RACED)
    asked = []

    def gone(package, version_id):
        asked.append((package, version_id))
        return False

    assert cleanup_verify.judge("cleanup: dev-base", "dev-base", log, gone) == []
    assert asked == [("dev-base", 303)]


def test_a_not_found_delete_whose_version_is_still_present_fails():
    log = cleanup_verify.parse_log(RACED)
    (error,) = cleanup_verify.judge(
        "reap: dev-base (older than 7 days)", "dev-base", log, lambda p, i: True
    )
    assert error.startswith("::error title=Package cleanup left versions behind::")
    assert "dev-base" in error
    assert "303" in error
    assert "the token could not delete" in error


def test_a_retried_leg_counts_each_version_once():
    # Attempt 2 lists and deletes again; a version failed in both attempts
    # is one planned delete.
    log = cleanup_verify.parse_log(ALL_NOT_FOUND + "\n" + ALL_NOT_FOUND)
    assert log.planned == {101, 102, 103}
    (error,) = cleanup_verify.judge("cleanup: dev-base", "dev-base", log, _never_present)
    assert "all 3 deletes" in error


def test_a_leg_with_nothing_to_delete_passes():
    log = cleanup_verify.parse_log(f"{STAMP} Nothing to delete")
    assert cleanup_verify.judge("cleanup: dev-base", "dev-base", log, _never_present) == []


@pytest.mark.parametrize(
    ("name", "package"),
    [
        ("cleanup: dev-base", "dev-base"),
        ("reap: prod-cpp-clang (older than 30 days)", "prod-cpp-clang"),
    ],
)
def test_leg_names_match_the_workflow(name, package):
    match = cleanup_verify.LEG.match(name)
    assert match and match["package"] == package


@pytest.mark.parametrize("name", ["verify-deletes", "report", "Report persistent failure"])
def test_other_jobs_are_not_legs(name):
    assert cleanup_verify.LEG.match(name) is None


API = cleanup_verify.API
RUN = f"{API}/repos/vergil-project/vergil-containers/actions/runs/7/attempts/1/jobs?per_page=100&page=1"
STORAGE = "https://logs.example.invalid/job"


def _job(job_id, name, conclusion="success"):
    return {"id": job_id, "name": name, "status": "completed", "conclusion": conclusion}


def _main(monkeypatch, capsys, jobs, logs, active):
    """Run main() against a stubbed API: `jobs` the run's jobs, `logs` each
    job's log by id, `active` each package's active version ids."""
    calls = []

    def fake(url, token, *, retry_404=False):
        calls.append((url, token))
        if url == RUN:
            return 200, {}, json.dumps({"jobs": jobs}).encode()
        for job_id, text in logs.items():
            if url == f"{API}/repos/vergil-project/vergil-containers/actions/jobs/{job_id}/logs":
                return 302, {"Location": f"{STORAGE}/{job_id}"}, b""
            if url == f"{STORAGE}/{job_id}":
                return 200, {}, text.encode()
        for package, ids in active.items():
            if url.startswith(f"{API}/orgs/vergil-project/packages/container/{package}/versions?"):
                return 200, {}, json.dumps([{"id": i} for i in ids]).encode()
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(cleanup_verify, "_request", fake)
    for key, value in {
        "GITHUB_REPOSITORY": "vergil-project/vergil-containers",
        "GITHUB_RUN_ID": "7",
        "GITHUB_RUN_ATTEMPT": "1",
        "PACKAGE_OWNER": "vergil-project",
        "GITHUB_TOKEN": "actions-token",
        "CLEANUP_TOKEN": "pat",
    }.items():
        monkeypatch.setenv(key, value)
    code = cleanup_verify.main()
    return code, capsys.readouterr().out, calls


def test_main_fails_the_run_whose_deletes_were_all_not_found(monkeypatch, capsys):
    jobs = [
        _job(1, "cleanup: dev-base"),
        _job(2, "reap: dev-base (older than 7 days)"),
        _job(3, "cleanup: dev-go", "skipped"),
        _job(4, "verify-deletes"),
    ]
    code, out, calls = _main(monkeypatch, capsys, jobs, {1: ALL_NOT_FOUND, 2: RACED}, {"dev-base": [999]})
    assert code == 1
    assert "::error title=Package cleanup deleted nothing::cleanup: dev-base" in out
    # The raced delete of the reap leg is gone, so that leg passes.
    assert "left versions behind" not in out
    assert "cleanup: dev-go: skipped" in out
    # The log storage is fetched without the token, which stays on the API.
    assert (f"{STORAGE}/1", None) in calls
    assert all(token is None for url, token in calls if url.startswith(STORAGE))
    assert all(token == "pat" for url, token in calls if "/packages/" in url)


def test_main_passes_a_run_whose_deletes_happened(monkeypatch, capsys):
    jobs = [_job(1, "cleanup: dev-base"), _job(2, "reap: dev-base (older than 7 days)")]
    code, out, _ = _main(monkeypatch, capsys, jobs, {1: NORMAL, 2: RACED}, {"dev-base": [301]})
    # 303 was raced and is gone; 301 is listed but was never answered "not found".
    assert code == 0, out
    assert "::error" not in out


def test_main_fails_when_it_finds_no_leg(monkeypatch, capsys):
    code, out, _ = _main(monkeypatch, capsys, [_job(4, "verify-deletes")], {}, {})
    assert code == 1
    assert "::error title=Delete check found no legs::" in out


def test_request_retries_a_transient_failure_then_gives_up(monkeypatch):
    attempts = []

    def failing(request, timeout):
        attempts.append(request.full_url)
        raise cleanup_verify.urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)

    monkeypatch.setattr(cleanup_verify._OPENER, "open", failing)
    monkeypatch.setattr(cleanup_verify.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="still failing"):
        cleanup_verify._request(f"{API}/x", "t")
    assert len(attempts) == cleanup_verify.ATTEMPTS


def test_leg_name_patterns_are_the_workflows():
    # The check finds the legs by name, so the names must keep their shape.
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    assert jobs["cleanup"]["name"] == "cleanup: ${{ matrix.package }}"
    assert jobs["reap-aliases"]["name"] == "reap: ${{ matrix.package }} (older than ${{ matrix.older_than }})"


def test_verify_job_runs_the_check_after_every_leg():
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    job = jobs["verify-deletes"]
    assert sorted(job["needs"]) == ["cleanup", "reap-aliases"]
    # It runs after failed legs too, and reads the cleanup token from the
    # environment it lives in; its GITHUB_TOKEN reads the logs and nothing else.
    assert job["if"] == "${{ !cancelled() }}"
    assert job["environment"] == "automation"
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    step = job["steps"][-1]
    assert step["run"].strip() == "python3 docker/versions/cleanup_verify.py"
    assert step["env"]["CLEANUP_TOKEN"] == "${{ secrets.GHCR_CLEANUP_TOKEN }}"
    assert step["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
    assert step["env"]["PACKAGE_OWNER"] == "vergil-project"
    assert "continue-on-error" not in step
    # The report counts it with the legs.
    assert "verify-deletes" in jobs["report"]["needs"]
