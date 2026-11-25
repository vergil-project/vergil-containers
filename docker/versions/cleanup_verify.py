"""Check that package-cleanup's legs deleted what they set out to delete
(vergil-containers#1051).

dataaxiom/ghcr-cleanup-action treats a 404 on a version delete as success: it
logs "The package "<name>" version id <id> wasn't found while trying to
delete it; treating as already deleted" and carries on, and counts the
version as deleted. A token that cannot delete gets exactly that 404 (GitHub
answers 404, not 403, when the caller may not act on a package), so a leg
whose every delete failed ended green (run 45635208056). The action has no
outputs to read, and a step cannot read another step's log while its job
runs, so this check runs as the workflow's `verify-deletes` job once every
leg has finished. For each leg it downloads the job's log through the Actions
API, takes the version IDs the action set out to delete ("deleting package
id: <id>") and those answered "not found", and fails when:

- every planned delete of the leg was answered "not found": the token could
  not delete; or
- a version answered "not found" is still among the package's active
  versions, listed through the Packages API with the cleanup token: the
  delete did not happen.

A version answered "not found" that is really gone was deleted by someone
else between the action's listing and its delete (the race of issue #911),
and passes. A dry run logs its planned deletes but never calls delete, so it
has no "not found" lines and passes.

Run from the workflow with the environment GITHUB_TOKEN (actions: read, for
the logs), CLEANUP_TOKEN (the Packages API), GITHUB_REPOSITORY,
GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT and PACKAGE_OWNER. Transient API failures
(5xx, 429, a dropped connection, a log not yet published) are retried with a
back-off; one that persists fails the check, never passes it.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

DELETING = re.compile(r" deleting package id: (?P<id>\d+) digest: ")
NOT_FOUND = re.compile(
    r"The package \"(?P<package>[^\"]+)\" version id (?P<id>\d+) wasn't found "
    r"while trying to delete it; treating as already deleted\."
)
# The matrix legs' job names (package-cleanup.yml): "cleanup: <package>" and
# "reap: <package> (older than <window>)".
LEG = re.compile(r"^(?P<kind>cleanup|reap): (?P<package>[A-Za-z0-9._-]+)(?: \(.*\))?$")
API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
ATTEMPTS = 6
BACKOFF_SECONDS = 5


@dataclass
class LegLog:
    planned: set[int] = field(default_factory=set)
    not_found: set[int] = field(default_factory=set)


def parse_log(text: str) -> LegLog:
    """The version IDs a leg's log says the action set out to delete, and
    those its delete was answered "not found" for. Both attempts of a leg are
    in the one log; an ID listed twice counts once."""
    log = LegLog()
    for line in text.splitlines():
        if match := DELETING.search(line):
            log.planned.add(int(match["id"]))
        if match := NOT_FOUND.search(line):
            log.not_found.add(int(match["id"]))
    # A "not found" is only ever logged for a delete the action planned.
    log.planned |= log.not_found
    return log


def judge(leg: str, package: str, log: LegLog, present: Callable[[str, int], bool]) -> list[str]:
    """The `::error` lines for one leg: none when its deletes happened."""
    if not log.not_found:
        return []
    if log.not_found == log.planned:
        return [
            f"::error title=Package cleanup deleted nothing::{leg}: all "
            f"{len(log.planned)} deletes of package {package} were answered "
            "\"not found\" (\"wasn't found while trying to delete it\"), so the "
            "token could not delete them. GHCR answers 404 when the token may "
            "not delete the package: check that GHCR_CLEANUP_TOKEN is a personal "
            "access token (classic) with delete:packages whose owner can delete "
            "this package (vergil-containers#1050, #1051)."
        ]
    still = sorted(i for i in log.not_found if present(package, i))
    if not still:
        return []
    shown = ", ".join(str(i) for i in still[:20]) + (" ..." if len(still) > 20 else "")
    return [
        f"::error title=Package cleanup left versions behind::{leg}: "
        f"{len(still)} of the {len(log.not_found)} deletes of package {package} "
        "answered \"not found\" are still present (version ids "
        f"{shown}), so the token could not delete them. Check "
        "GHCR_CLEANUP_TOKEN's access to this package (vergil-containers#1051)."
    ]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _transient(status: int) -> bool:
    return status == 429 or status >= 500


def _request(url: str, token: str | None, *, retry_404: bool = False) -> tuple[int, dict, bytes]:
    """GET `url`, retrying transient failures. Returns (status, headers,
    body) for a 2xx, a 3xx (redirects are not followed) or a 404."""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with _OPENER.open(urllib.request.Request(url, headers=headers), timeout=60) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            if 300 <= error.code < 400:
                return error.code, dict(error.headers), b""
            if error.code == 404 and not retry_404:
                return 404, dict(error.headers), b""
            if not (_transient(error.code) or error.code == 404):
                raise RuntimeError(f"GET {url}: HTTP {error.code}: {error.read()[:500]!r}") from error
            last = f"HTTP {error.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = str(error)
        if attempt < ATTEMPTS:
            delay = BACKOFF_SECONDS * 2 ** (attempt - 1)
            print(f"GET {url}: {last}; retrying in {delay}s ({attempt}/{ATTEMPTS})", file=sys.stderr)
            time.sleep(delay)
    raise RuntimeError(f"GET {url}: still failing after {ATTEMPTS} attempts ({last})")


def _jobs(repo: str, run_id: str, attempt: str, token: str) -> list[dict]:
    jobs, page = [], 1
    while True:
        url = f"{API}/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}"
        status, _, body = _request(url, token)
        if status != 200:
            raise RuntimeError(f"GET {url}: HTTP {status}")
        batch = json.loads(body)["jobs"]
        jobs.extend(batch)
        if len(batch) < 100:
            return jobs
        page += 1


def _log(repo: str, job_id: int, token: str) -> str:
    # The API answers with a short-lived redirect to the log's storage. It is
    # fetched without the token, which must not reach another host. A 404
    # can mean the log of a just-finished job is not published yet: retried.
    url = f"{API}/repos/{repo}/actions/jobs/{job_id}/logs"
    status, headers, body = _request(url, token, retry_404=True)
    if 300 <= status < 400:
        location = headers.get("Location") or headers.get("location")
        if not location:
            raise RuntimeError(f"GET {url}: HTTP {status} with no Location")
        status, _, body = _request(location, None, retry_404=True)
    if status != 200:
        raise RuntimeError(f"GET {url}: HTTP {status}")
    return body.decode("utf-8", errors="replace")


def main() -> int:
    env = os.environ
    repo, owner = env["GITHUB_REPOSITORY"], env["PACKAGE_OWNER"]
    actions_token, cleanup_token = env["GITHUB_TOKEN"], env["CLEANUP_TOKEN"]
    if not actions_token or not cleanup_token:
        print("::error title=Delete check misconfigured::GITHUB_TOKEN and CLEANUP_TOKEN must both be set.")
        return 1

    active: dict[str, set[int]] = {}

    def present(package: str, version_id: int) -> bool:
        # The package's active versions, listed once: a deleted version
        # leaves the active list, even while it can still be restored.
        if package not in active:
            active[package] = set()
            page = 1
            while True:
                url = (
                    f"{API}/orgs/{owner}/packages/container/{package}/versions"
                    f"?state=active&per_page=100&page={page}"
                )
                status, _, body = _request(url, cleanup_token)
                if status != 200:
                    raise RuntimeError(f"GET {url}: HTTP {status}")
                batch = json.loads(body)
                active[package].update(int(v["id"]) for v in batch)
                if len(batch) < 100:
                    break
                page += 1
        return version_id in active[package]

    legs = []
    for job in _jobs(repo, env["GITHUB_RUN_ID"], env["GITHUB_RUN_ATTEMPT"], actions_token):
        if match := LEG.match(job["name"]):
            legs.append((job, match["package"]))
    if not legs:
        print("::error title=Delete check found no legs::No cleanup or reap leg in this run's jobs; nothing was checked.")
        return 1

    errors = []
    for job, package in legs:
        if job["conclusion"] == "skipped":
            print(f"{job['name']}: skipped, nothing to check")
            continue
        if job["status"] != "completed":
            errors.append(f"::error title=Delete check ran too early::{job['name']} has not finished ({job['status']}).")
            continue
        log = parse_log(_log(repo, job["id"], actions_token))
        found = judge(job["name"], package, log, present)
        print(f"{job['name']}: {len(log.planned)} planned deletes, {len(log.not_found)} answered \"not found\"")
        errors.extend(found)
    for line in errors:
        print(line)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
