#!/usr/bin/env python3
"""Publish lifecycle check results as GitHub issues and add/drop PRs (spec §6.2).

    python3 docker/versions/lifecycle/publish.py --results PATH --run-url URL
        [--manifest PATH] [--repo OWNER/NAME] [--prs --base BRANCH]

Reads the results JSON written by `check.py --json` and makes the open issues
(default) or the open add/drop PRs (`--prs`) match it, so "no open issue and
no PR" reliably means "in sync".

Issues:

- one issue per change on a `report` family, and per change on a `pr` family
  that no PR can carry (`blocked`, `eol_soon`, `runtime_missing`), titled
  `language lifecycle: <family> <kind> <version>`;
- one issue per family whose check failed, titled
  `lifecycle check failing for <family>`, with the error text as its body.

Every run refreshes the issues that are still reported (never duplicating
them), closes a failure issue with `recovered in run <url>` once its family
checks cleanly, and closes a change issue that is no longer reported. Every
issue this script manages carries the `language-lifecycle` label; it only ever
touches open issues with that label and one of the two titles.

PRs (`--prs`): one PR per `add`, `drop` or `runtime` on a `pr` family, on the branch
`lifecycle/<family>-<kind>-<version>`. Each run rebuilds the branch from the
base as one commit (the manifest edit plus every regenerated file), pushes it
only when that commit differs from the branch, and refreshes the open PR's
title and body; it never opens a second PR for the same change. A managed PR
whose change is no longer reported is closed, unless its family's check
failed this run. Nothing here ever enables auto-merge: a human reviews and
merges every PR.

Any `gh` or `git` failure raises: a half-published run is never reported as
success.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

if __package__ in (None, ""):  # run as a script: make `docker/versions` importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lifecycle.apply import (  # noqa: E402
    BRANCH_PREFIX,
    PR_KINDS,
    ApplyError,
    branch_name,
    parse_branch,
    pr_title,
    render_change,
)
from lifecycle.core import Adapter, Change, FamilyResult, SourceError, has_runtime  # noqa: E402
from lifecycle.report import results_from_json  # noqa: E402
from lifecycle.runtime import APT_URL  # noqa: E402
from manifest import Family, Manifest, ManifestError, load_manifest  # noqa: E402

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.yml"
REPO_ROOT = Path(__file__).resolve().parents[3]

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
        else:
            for c in r.changes:
                # A `pr` family's adds and drops get PRs (sync_prs); anything
                # else it reports (blocked, EOL soon) still needs a signal.
                if automation[r.family] == REPORT_AUTOMATION or c.kind not in PR_KINDS:
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


# --- Add/drop PRs ------------------------------------------------------------------

# The upstream evidence a PR cites, for the kinds whose evidence is not the
# family's release metadata: a runtime flip is read from the package index.
EVIDENCE_URLS: dict[str, str] = {"runtime": APT_URL}


@dataclass(frozen=True)
class OpenPr:
    number: int
    head: str


class PrClient(Protocol):
    def list_open_prs(self, head_prefix: str) -> list[OpenPr]: ...

    def create_pr(self, head: str, title: str, body: str) -> int: ...

    def update_pr(self, number: int, title: str, body: str) -> None: ...

    def close_pr(self, number: int, comment: str) -> None: ...


class BranchPublisher(Protocol):
    def publish_branch(self, branch: str, files: Mapping[Path, str], message: str) -> bool:
        """Make `branch` the base plus one commit writing `files`; True if
        that needed a push, False if the branch already was exactly that."""
        ...


def _eol_of(change: Change, result: FamilyResult, manifest: Manifest) -> date | None:
    """The EOL date for `change.version`: upstream's, else the manifest's."""
    for r in result.releases:
        if r.version == change.version and r.eol is not None:
            return r.eol
    for f in manifest.families:
        if f.key == change.family:
            for v in f.versions:
                if v.version == change.version:
                    return v.eol
    return None


def pr_body(
    change: Change,
    *,
    evidence_url: str,
    files: Sequence[Path],
    follow_ups: Sequence[str],
    run_url: str,
    runtime_pending: bool,
) -> str:
    lines = [
        f"The scheduled language lifecycle check reports `{change.kind}` for "
        f"`{change.family}` {change.version}:",
        "",
        f"> {change.detail}",
        "",
        f"- Upstream evidence: {evidence_url}",
        f"- Policy: `docs/site/docs/languages/{change.family}.md`",
        f"- Last refreshed by {run_url}",
        "",
        "## Merging",
        "",
        "- This PR is **not** set to auto-merge, and the lifecycle automation never "
        "enables it. A human reviews and merges it.",
    ]
    if change.kind == "runtime":
        lines.append(
            "- Merging records `runtime_published: true` for this version, so packaged "
            "consumers may resolve to it on their next build (spec §7)."
        )
    if runtime_pending:
        lines.append(
            "- The new version is recorded with `runtime_published: false`: no runtime "
            "package is published for it yet, so packaged consumers stay on an older "
            "version until the runtime signal flips it."
        )
    lines += ["", "## Regenerated files", ""]
    lines += [f"- `{p.as_posix()}`" for p in files]
    lines += ["", "## Manual follow-ups", ""]
    lines += [f"- [ ] {f}" for f in follow_ups] or ["None."]
    lines += [
        "",
        "This PR is refreshed in place by every run of the check: its branch is rebuilt "
        "from the base (force-pushed only when the content changes) and it is closed "
        "automatically once the change is no longer reported.",
    ]
    return "\n".join(lines) + "\n"


def sync_prs(
    results: Sequence[FamilyResult],
    gh: PrClient,
    git: BranchPublisher,
    *,
    manifest: Manifest,
    adapters: Mapping[str, Adapter],
    root: Path,
    run_url: str,
) -> None:
    """Make the open managed PRs match the adds and drops in `results`.

    `manifest` is the base's manifest and `root` a checkout of the base."""
    if not run_url:
        raise PublishError("a run URL is required for the PR bodies and closing comments")
    families = {f.key: f for f in manifest.families}
    by_family: dict[str, FamilyResult] = {}
    for r in results:
        if r.family not in families:
            raise PublishError(f"result for family {r.family!r}, which the manifest does not list")
        if r.family in by_family:
            raise PublishError(f"two results for family {r.family!r}")
        by_family[r.family] = r

    wanted = [
        (r, c)
        for r in results
        if r.error is None and families[r.family].automation != REPORT_AUTOMATION
        for c in r.changes
        if c.kind in PR_KINDS
    ]
    open_prs = {pr.head: pr.number for pr in gh.list_open_prs(BRANCH_PREFIX)}

    # One change that cannot be published must not hold back the others, and
    # must not close its own open PR as stale: its branch counts as wanted, the
    # error is collected, and the run fails at the end with every error.
    heads: set[str] = set()
    errors: list[str] = []
    for r, c in wanted:
        branch = branch_name(c)
        heads.add(branch)
        try:
            _publish_change(
                r, c, gh, git,
                branch=branch, number=open_prs.get(branch), families=families, manifest=manifest,
                adapters=adapters, root=root, run_url=run_url,
            )
        except (ApplyError, SourceError, PublishError) as exc:
            errors.append(f"{c.family} {c.kind} {c.version}: {exc}")

    for head, number in sorted(open_prs.items()):
        if head in heads:
            continue
        parsed = parse_branch(head)
        if parsed is None:
            continue  # not a branch this script manages
        result = by_family.get(parsed[0])
        if result is not None and result.error is not None:
            continue  # this run could not check the family: its changes are unknown, not gone
        gh.close_pr(number, f"no longer reported in run {run_url}")

    if errors:
        raise PublishError("could not publish every add/drop PR:\n  " + "\n  ".join(errors))


def _publish_change(
    result: FamilyResult,
    change: Change,
    gh: PrClient,
    git: BranchPublisher,
    *,
    branch: str,
    number: int | None,
    families: Mapping[str, Family],
    manifest: Manifest,
    adapters: Mapping[str, Adapter],
    root: Path,
    run_url: str,
) -> None:
    """Rebuild `change`'s branch and open or refresh its PR."""
    adapter = adapters.get(change.family)
    if adapter is None:
        raise PublishError(f"no lifecycle adapter is registered for family {change.family!r}")
    target = next((t for t in result.target if t.version == change.version), None)
    files = render_change(manifest, change, target, root)
    title = pr_title(change, _eol_of(change, result, manifest))
    body = pr_body(
        change,
        evidence_url=EVIDENCE_URLS.get(change.kind, adapter.evidence_url),
        files=list(files),
        follow_ups=adapter.extra_changes(change),
        run_url=run_url,
        runtime_pending=change.kind == "add" and has_runtime(families[change.family]),
    )
    pushed = git.publish_branch(branch, files, title)
    if number is None:
        number = gh.create_pr(branch, title, body)
    else:
        gh.update_pr(number, title, body)
        print(f"#{number}: branch {branch} {'force-pushed' if pushed else 'unchanged'}")


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
    """`GhClient` and `PrClient` backed by the `gh` CLI, for repository `repo`.
    The PR methods need `base`, the branch PRs target."""

    def __init__(self, repo: str, runner: Runner | None = None, base: str | None = None) -> None:
        self._repo = repo
        self._run = runner or run_gh
        self._base = base

    def _require_base(self) -> str:
        if not self._base:
            raise PublishError("PR operations need a base branch")
        return self._base

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

    def list_open_prs(self, head_prefix: str) -> list[OpenPr]:
        out = self._run(
            ["pr", "list", "--repo", self._repo, "--state", "open", "--base", self._require_base(),
             "--limit", str(LIST_LIMIT), "--json", "number,headRefName"],
            None,
        )
        try:
            data = json.loads(out)
            prs = [OpenPr(int(p["number"]), str(p["headRefName"])) for p in data]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise PublishError(f"gh pr list returned malformed JSON: {exc!r}") from exc
        if len(prs) >= LIST_LIMIT:
            raise PublishError(
                f"{len(prs)} open PRs fill the listing limit; refusing to sync from a possibly incomplete list"
            )
        return [p for p in prs if p.head.startswith(head_prefix)]

    def create_pr(self, head: str, title: str, body: str) -> int:
        out = self._run(
            ["pr", "create", "--repo", self._repo, "--base", self._require_base(), "--head", head,
             "--title", title, "--body-file", "-"],
            body,
        )
        m = _PR_URL_RE.search(out)
        if m is None:
            raise PublishError(f"gh pr create printed no PR URL: {out.strip()!r}")
        number = int(m.group(1))
        print(f"opened PR #{number}: {title}")
        return number

    def update_pr(self, number: int, title: str, body: str) -> None:
        self._run(["pr", "edit", str(number), "--repo", self._repo, "--title", title, "--body-file", "-"], body)
        print(f"refreshed PR #{number}")

    def close_pr(self, number: int, comment: str) -> None:
        self._run(["pr", "close", str(number), "--repo", self._repo, "--delete-branch", "--comment", comment], None)
        print(f"closed PR #{number}: {comment}")


_PR_URL_RE = re.compile(r"/pull/(\d+)\s*$")

# --- The real branch publisher ---------------------------------------------------------

# The bot identity bump-tools.yml commits as. Fixed here, with the commit dates
# taken from the base, so the same change on the same base is the same commit:
# a rerun can tell "already pushed" from "changed" by comparing commit ids.
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

GitRunner = Callable[[list[str], Mapping[str, str] | None], str]


def run_git(args: list[str], env: Mapping[str, str] | None = None) -> str:
    """Run `git` and return its stdout. A non-zero exit raises PublishError."""
    full_env = {**os.environ, **env} if env else None
    proc = subprocess.run(["git", *args], capture_output=True, text=True, check=False, env=full_env)
    if proc.returncode != 0:
        raise PublishError(f"git {' '.join(args[:3])} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


class GitCli:
    """`BranchPublisher` backed by `git`, from the checkout at `root` (whose
    `base_ref` is the PR base), pushing to `remote`."""

    def __init__(self, root: Path, base_ref: str = "HEAD", remote: str = "origin", runner: GitRunner | None = None):
        self._root = root
        self._base_ref = base_ref
        self._remote = remote
        self._run = runner or run_git

    def _git(self, *args: str, env: Mapping[str, str] | None = None, cwd: Path | None = None) -> str:
        return self._run(["-C", str(cwd or self._root), *args], env)

    def publish_branch(self, branch: str, files: Mapping[Path, str], message: str) -> bool:
        if not files:
            raise PublishError(f"{branch}: nothing to commit")
        base = self._git("rev-parse", "--verify", f"{self._base_ref}^{{commit}}").strip()
        when = self._git("log", "-1", "--format=%cI", base).strip()
        env = {
            "GIT_AUTHOR_NAME": BOT_NAME, "GIT_AUTHOR_EMAIL": BOT_EMAIL, "GIT_AUTHOR_DATE": when,
            "GIT_COMMITTER_NAME": BOT_NAME, "GIT_COMMITTER_EMAIL": BOT_EMAIL, "GIT_COMMITTER_DATE": when,
        }
        with tempfile.TemporaryDirectory(prefix="lifecycle-") as tmp:
            tree = Path(tmp) / "tree"
            self._git("worktree", "add", "--detach", str(tree), base)
            try:
                for rel, content in files.items():
                    path = tree / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
                self._git("add", "--", *(str(rel) for rel in files), cwd=tree)
                if not self._git("diff", "--cached", "--name-only", cwd=tree).strip():
                    raise PublishError(f"{branch}: the change writes nothing new on the base")
                self._git("-c", "commit.gpgsign=false", "commit", "--no-verify", "-q", "-m", message, env=env, cwd=tree)
                commit = self._git("rev-parse", "HEAD", cwd=tree).strip()
            finally:
                self._git("worktree", "remove", "--force", str(tree))

        ref = f"refs/heads/{branch}"
        current = ""
        for line in self._git("ls-remote", "--heads", self._remote, ref).splitlines():
            sha, _, name = line.partition("\t")
            if name == ref:
                current = sha
        if current == commit:
            return False
        # The lease makes the force-push refuse if the branch moved since we looked.
        self._git("push", f"--force-with-lease={ref}:{current}", self._remote, f"{commit}:{ref}")
        return True


# --- CLI -------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    gh: GhClient | PrClient | None = None,
    git: BranchPublisher | None = None,
    adapters: Mapping[str, Adapter] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, required=True, help="the JSON written by check.py --json")
    parser.add_argument("--run-url", required=True, help="the URL of this workflow run")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="OWNER/NAME")
    parser.add_argument("--prs", action="store_true", help="sync the add/drop PRs instead of the issues")
    parser.add_argument("--base", help="the branch the PRs target (with --prs; the checkout must be at it)")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="the repo checkout (with --prs)")
    args = parser.parse_args(argv)

    try:
        results = results_from_json(args.results.read_text())
        manifest = load_manifest(args.manifest)
        if args.prs:
            if gh is None:
                if not args.repo or not args.base:
                    raise PublishError("--prs needs --base and a repository (--repo or $GITHUB_REPOSITORY)")
                gh = GhCli(args.repo, base=args.base)
            if git is None:
                git = GitCli(args.root)
            if adapters is None:
                from lifecycle.adapters import ADAPTERS

                adapters = ADAPTERS
            sync_prs(
                results, gh, git,  # type: ignore[arg-type]
                manifest=manifest, adapters=adapters, root=args.root, run_url=args.run_url,
            )
            return 0
        automation = {f.key: f.automation for f in manifest.families}
        if gh is None:
            if not args.repo:
                raise PublishError("no repository: pass --repo or set $GITHUB_REPOSITORY")
            cli = GhCli(args.repo)
            cli.ensure_label(LABEL)
            gh = cli
        sync_issues(results, gh, automation=automation, run_url=args.run_url)  # type: ignore[arg-type]
    except (OSError, ValueError, ManifestError, PublishError) as exc:
        print(f"lifecycle publish: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
