# Pushback Review: Host-Only Tool Guardrails (Issue #91)

**Date:** 2026-04-29
**Spec:** docs/plans/issue-91-host-only-guardrails.md
**Commit:** d7d17a6

## Source Control Conflicts

None — no conflicts with recent changes.

## Issues Reviewed

### [1] Remove `gh` from container images instead of shimming it

- **Category:** omissions
- **Severity:** serious
- **Issue:** The plan installed `gh` via apt and then immediately disabled it with a shim that renamed the binary to `gh.real`. This adds ~50MB of dead weight per image for a binary no container-side command uses. The simpler approach is to remove `github-cli.dockerfile` from all templates entirely and replace it with a lightweight shim-only fragment that provides the helpful error message without installing the real binary.
- **Resolution:** Accepted. Remove `github-cli.dockerfile` includes from all templates. Create a shim-only `gh-guardrail.dockerfile` that writes a small error script to `/usr/local/bin/gh` — no apt-get, no real binary, no escape hatch.

### [2] `BLOCKED_CONTAINER_COMMANDS` flat set doesn't fit the revised git model

- **Category:** feasibility
- **Severity:** moderate
- **Issue:** The original plan defined `BLOCKED_CONTAINER_COMMANDS: frozenset[str] = frozenset({"gh", "git"})` as a flat set. After the audit showed git is legitimately needed inside containers (git-cliff, validate_local, uv/pip), the model changed to: read-only git operations are container-safe, read-write/remote operations are host-only. A flat set can't express "block `git push` but allow `git log`."
- **Resolution:** Accepted. Two constants: `BLOCKED_TOOLS = frozenset({"gh"})` for fully-blocked tools, `BLOCKED_GIT_SUBCOMMANDS = frozenset({"push", "pull", ...})` for mutating/remote git operations. `check_blocked_command()` inspects argv[0] for the first set, then argv[1] for git specifically.

### [3] Container-side git wrapper closes the documented gap

- **Category:** omissions
- **Severity:** moderate
- **Issue:** The original plan documented `st-docker-run -- bash -c "git push"` as an intentional gap that could not be closed because shimming git would break git-cliff. With the read-only/read-write model, a container-side git wrapper can block mutating operations while allowing read-only ones, closing the gap entirely.
- **Resolution:** Accepted. Add a container-side git wrapper at `/usr/local/bin/git` that checks `$1` against the blocked subcommands list. If blocked, prints an error and exits 1. If allowed, execs the real git at `/usr/bin/git`.

### [4] Blocked subcommands list duplicated across repos and languages

- **Category:** ambiguity
- **Severity:** minor
- **Issue:** The same blocked git subcommands list exists in `docker.py` (Python, standard-tooling repo) and the container-side git wrapper (shell, vergil-docker repo). If someone updates one but not the other, they drift.
- **Resolution:** Accepted. Accept the duplication (the list is stable — git rarely adds new write operations). Add a cross-referencing comment at each site pointing to the other location, so any agent or human modifying either list is aware of its counterpart.

## Summary

- **Issues found:** 4
- **Issues resolved:** 4
- **Unresolved:** 0
- **Spec status:** ready for implementation (after spec update applied)
