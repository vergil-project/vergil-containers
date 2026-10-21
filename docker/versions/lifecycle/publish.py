#!/usr/bin/env python3
"""Publish lifecycle check results as GitHub issues (spec §6.2).

    python3 docker/versions/lifecycle/publish.py --results PATH --run-url URL
        [--manifest PATH] [--repo OWNER/NAME]

Reads the results JSON written by `check.py --json` and makes the open issues
match it, so "no open issue and no PR" reliably means "in sync":

- one issue per change on a `report` family, titled
  `language lifecycle: <family> <kind> <version>`;
- one issue per family whose check failed, titled
  `lifecycle check failing for <family>`, with the error text as its body.

Every run refreshes the issues that are still reported (never duplicating
them), closes a failure issue with `recovered in run <url>` once its family
checks cleanly, and closes a change issue that is no longer reported. Changes
on `pr` families open no issue: they get add/drop PRs instead.

Every issue this script manages carries the `language-lifecycle` label; it
only ever touches open issues with that label and one of the two titles.
Any `gh` failure raises: a half-published run is never reported as success.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

if __package__ in (None, ""):  # run as a script: make `docker/versions` importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lifecycle.core import Change, FamilyResult  # noqa: E402
from lifecycle.report import results_from_json  # noqa: E402
from manifest import ManifestError, load_manifest  # noqa: E402

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.yml"

LABEL = "language-lifecycle"
LABEL_COLOR = "1d76db"
LABEL_DESCRIPTION = "Opened by the scheduled language lifecycle check"
CHANGE_PREFIX = "language lifecycle: "
FAILURE_PREFIX = "lifecycle check failing for "
REPORT_AUTOMATION = "report"

# `gh issue list` returns at most this many; a full page means the listing may
# be incomplete, which would hide issues from refresh and closure.
LIST_LIMIT = 1000


class PublishError(Exception):
    """Issues could not be listed or written, or the input made no sense."""


@dataclass(frozen=True)
class OpenIssue:
    number: int
    title: str


class GhClient(Protocol):
    def list_open_issues(self, label: str) -> list[OpenIssue]: ...

    def create_issue(self, title: str, body: str, labels: Sequence[str]) -> int: ...

    def update_issue(self, number: int, body: str) -> None: ...

    def close_issue(self, number: int, comment: str) -> None: ...


# --- Titles and bodies -----------------------------------------------------------


def change_title(change: Change) -> str:
    return f"{CHANGE_PREFIX}{change.family} {change.kind} {change.version}"


def failure_title(family: str) -> str:
    return f"{FAILURE_PREFIX}{family}"


def _change_family(title: str) -> str | None:
    """The family of a managed change-issue title, or None if it is not one."""
    if not title.startswith(CHANGE_PREFIX):
        return None
    parts = title[len(CHANGE_PREFIX):].split(" ")
    return parts[0] if len(parts) == 3 and all(parts) else None


def _failure_family(title: str) -> str | None:
    if not title.startswith(FAILURE_PREFIX):
        return None
    family = title[len(FAILURE_PREFIX):]
    return family if family and " " not in family else None


def change_body(change: Change, run_url: str) -> str:
    return (
        f"The scheduled language lifecycle check reports `{change.kind}` for "
        f"`{change.family}` {change.version}:\n\n"
        f"> {change.detail}\n\n"
        f"Last reported by {run_url}.\n\n"
        "This issue is refreshed by every run of the check and closed "
        "automatically once the change is no longer reported. The window rules "
        "are the family's policy page under `docs/site/docs/languages/`, and the "
        "manifest is `docker/versions/manifest.yml`.\n"
    )


def failure_body(family: str, error: str, run_url: str) -> str:
    return (
        f"The scheduled language lifecycle check failed for `{family}`, so its "
        "versions were not checked against upstream:\n\n"
        f"```text\n{error}\n```\n\n"
        f"Last failing run: {run_url}.\n\n"
        "This issue is refreshed by every failing run and closed automatically "
        "by the next run that checks this family cleanly.\n"
    )


# --- Sync ----------------------------------------------------------------------


def sync_issues(
    results: Sequence[FamilyResult],
    gh: GhClient,
    *,
    automation: Mapping[str, str],
    run_url: str,
) -> None:
    """Make the open `language-lifecycle` issues match `results`.

    `automation` maps each family key to its manifest automation (`pr` or
    `report`); a result for a family it does not name raises PublishError.
    """
    if not run_url:
        raise PublishError("a run URL is required for the issue bodies and closing comments")
    by_family: dict[str, FamilyResult] = {}
    for r in results:
        if r.family not in automation:
            raise PublishError(f"result for family {r.family!r}, which the manifest does not list")
        if r.family in by_family:
            raise PublishError(f"two results for family {r.family!r}")
        by_family[r.family] = r

    wanted: dict[str, str] = {}
    for r in results:
        if r.error is not None:
            wanted[failure_title(r.family)] = failure_body(r.family, r.error, run_url)
        elif automation[r.family] == REPORT_AUTOMATION:
            for c in r.changes:
                wanted[change_title(c)] = change_body(c, run_url)

    open_by_title: dict[str, list[int]] = {}
    for issue in gh.list_open_issues(LABEL):
        open_by_title.setdefault(issue.title, []).append(issue.number)

    for title, body in wanted.items():
        numbers = sorted(open_by_title.get(title, []))
        if not numbers:
            gh.create_issue(title, body, [LABEL])
            continue
        keep, *dupes = numbers
        gh.update_issue(keep, body)
        for n in dupes:
            gh.close_issue(n, f"duplicate of #{keep}, which tracks the same {title!r}")

    for title, numbers in sorted(open_by_title.items()):
        if title in wanted:
            continue
        comment = _closing_comment(title, by_family, run_url)
        if comment is None:
            continue
        for n in sorted(numbers):
            gh.close_issue(n, comment)


def _closing_comment(title: str, by_family: Mapping[str, FamilyResult], run_url: str) -> str | None:
    """The comment to close an open managed issue that this run no longer
    reports, or None to leave it open (or alone, if it is not managed)."""
    family = _failure_family(title)
    if family is not None:
        if family in by_family:
            return f"recovered in run {run_url}"  # it has no error, or the title would be wanted
        return f"no longer reported in run {run_url}: `{family}` is no longer in the manifest"
    family = _change_family(title)
    if family is None:
        return None  # labelled by hand, not one of ours
    result = by_family.get(family)
    if result is not None and result.error is not None:
        return None  # this run could not check the family: its changes are unknown, not gone
    return f"no longer reported in run {run_url}"


# --- The real client ---------------------------------------------------------------

Runner = Callable[[list[str], str | None], str]


def run_gh(args: list[str], stdin: str | None = None) -> str:
    """Run `gh` and return its stdout. A non-zero exit raises PublishError."""
    proc = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise PublishError(f"gh {' '.join(args[:2])} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


_ISSUE_URL_RE = re.compile(r"/issues/(\d+)\s*$")


class GhCli:
    """`GhClient` backed by the `gh` CLI, for repository `repo`."""

    def __init__(self, repo: str, runner: Runner | None = None) -> None:
        self._repo = repo
        self._run = runner or run_gh

    def ensure_label(self, label: str) -> None:
        self._run(
            ["label", "create", label, "--repo", self._repo, "--color", LABEL_COLOR,
             "--description", LABEL_DESCRIPTION, "--force"],
            None,
        )

    def list_open_issues(self, label: str) -> list[OpenIssue]:
        out = self._run(
            ["issue", "list", "--repo", self._repo, "--state", "open", "--label", label,
             "--limit", str(LIST_LIMIT), "--json", "number,title"],
            None,
        )
        try:
            data = json.loads(out)
            issues = [OpenIssue(int(i["number"]), str(i["title"])) for i in data]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise PublishError(f"gh issue list returned malformed JSON: {exc!r}") from exc
        if len(issues) >= LIST_LIMIT:
            raise PublishError(
                f"{len(issues)} open {label!r} issues fill the listing limit; "
                "refusing to sync from a possibly incomplete list"
            )
        return issues

    def create_issue(self, title: str, body: str, labels: Sequence[str]) -> int:
        args = ["issue", "create", "--repo", self._repo, "--title", title, "--body-file", "-"]
        for label in labels:
            args += ["--label", label]
        out = self._run(args, body)
        m = _ISSUE_URL_RE.search(out)
        if m is None:
            raise PublishError(f"gh issue create printed no issue URL: {out.strip()!r}")
        number = int(m.group(1))
        print(f"opened #{number}: {title}")
        return number

    def update_issue(self, number: int, body: str) -> None:
        self._run(["issue", "edit", str(number), "--repo", self._repo, "--body-file", "-"], body)
        print(f"refreshed #{number}")

    def close_issue(self, number: int, comment: str) -> None:
        self._run(["issue", "close", str(number), "--repo", self._repo, "--comment", comment], None)
        print(f"closed #{number}: {comment}")


# --- CLI -------------------------------------------------------------------------


def main(argv: list[str] | None = None, *, gh: GhClient | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, required=True, help="the JSON written by check.py --json")
    parser.add_argument("--run-url", required=True, help="the URL of this workflow run")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="OWNER/NAME")
    args = parser.parse_args(argv)

    try:
        results = results_from_json(args.results.read_text())
        manifest = load_manifest(args.manifest)
        automation = {f.key: f.automation for f in manifest.families}
        if gh is None:
            if not args.repo:
                raise PublishError("no repository: pass --repo or set $GITHUB_REPOSITORY")
            cli = GhCli(args.repo)
            cli.ensure_label(LABEL)
            gh = cli
        sync_issues(results, gh, automation=automation, run_url=args.run_url)
    except (OSError, ValueError, ManifestError, PublishError) as exc:
        print(f"lifecycle publish: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
