# Alignment Review: Host-Only Tool Guardrails (Issue #91)

**Date:** 2026-04-29
**Commit:** d7d17a6

## Documents Reviewed

- **Intent:** GitHub issue #91 (acceptance criteria)
- **Action:** docs/plans/issue-91-host-only-guardrails.md
- **Design:** none (plan includes design inline)

## Source Control Conflicts

None — no conflicts with recent changes (verified during pushback review).

## Issues Reviewed

### [1] `git clone` at build time blocked by wrapper ordering

- **Category:** missing coverage (AC-5 violated)
- **Severity:** critical
- **Documents:** Plan section 2.3 (template ordering) vs AC-5 (existing workflows unaffected)
- **Issue:** The plan placed `git-guardrail.dockerfile` early in the template include order — before `standard-tooling-uv.dockerfile` and `standard-tooling-pip.dockerfile`. Both fragments run `git clone` at build time. Installing the git wrapper before them would break the image build itself.
- **Resolution:** Move `git-guardrail.dockerfile` to the last include in every template, after all `standard-tooling-*` fragments. The wrapper only needs to exist at container runtime, not build time.

### [2] Issue AC-2 says "git ..." but plan allows read-only git

- **Category:** deviation between intent and action
- **Severity:** important
- **Documents:** Issue AC-2 vs Plan design section
- **Issue:** The issue acceptance criterion said "Running `st-docker-run -- git ...` fails with a clear, actionable error message" (implying all git). The plan allows read-only git operations based on the pushback-reviewed model that read-only=container-safe, read-write=host-only.
- **Resolution:** Updated issue AC-2 to: "Running `st-docker-run -- git push` (and other mutating/remote git subcommands) fails with a clear, actionable error message. Read-only git operations are allowed."

### [3] AC-3 says "one maintainable location" but plan has two with cross-refs

- **Category:** deviation between intent and action
- **Severity:** minor
- **Documents:** Issue AC-3 vs Plan sections 1.1 and 2.2
- **Issue:** The issue said "one maintainable location" but the implementation requires the blocked subcommands list in two locations (Python in standard-tooling, shell in vergil-docker) due to different repos and languages.
- **Resolution:** Updated issue AC-3 to: "defined in a maintainable way with cross-referencing comments at each site." Acknowledges inherent duplication across repos.

## Alignment Summary

- **Requirements:** 5 acceptance criteria, 5 covered (3 updated to match revised model)
- **Tasks:** All plan tasks trace to requirements, no scope creep
- **Status:** aligned (after issue update and plan ordering fix applied)
