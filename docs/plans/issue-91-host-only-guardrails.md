# Implementation Plan: Host-Only Tool Guardrails (Issue #91)

## Context

When `st-docker-run` launches a dev container, host-only tools like `gh` are
available inside the container, and read-write git operations (`git push`,
`git commit`, etc.) can run unchecked. Nothing prevents
`st-docker-run -- gh issue create ...` or `st-docker-run -- git push` — it
works by accident because the repo is mounted and credentials leak through.
This violates the host/container boundary and can't be fixed via documentation
alone (every agent in every repo would need to independently learn the
constraint).

**Guiding principle:** Read-only git operations are container-safe; read-write
and remote git operations are host-only. `gh` is entirely host-only — no
container-side command needs it.

**Tool audit results:**

- `gh` — NOT used by any container-side command. Only `st-prepare-release`
  and `st-finalize-repo` use it (both host-only). **Fully blocked.**
- `git` — legitimately used inside containers by `git-cliff`
  (`git log`, `git tag`), `validate_local_common_container.py`
  (`git rev-parse`), and `uv`/`pip` (git-based dependency installation).
  `docker.py` mounts `.gitconfig` and `.ssh` to support this.
  **Read-write/remote subcommands blocked; read-only allowed.**

## Design

Two layers of defense, each in a separate repo:

| Layer | Scope | Catches | Repo |
|-------|-------|---------|------|
| Host-side guard in `st-docker-run` | `gh` (all), `git` (mutating subcommands) | Direct invocation via `st-docker-run -- <tool> ...` | standard-tooling |
| Container-side wrappers | `gh` shim (all), `git` wrapper (mutating subcommands) | Indirect invocation from scripts inside the container | vergil-docker |

No intentional gaps — both direct and indirect invocation of blocked
operations are caught.

---

## Phase 1: Host-Side Guard (standard-tooling)

### 1.1 Add blocked-tools constants and checker to `docker.py`

**File:** `src/standard_tooling/lib/docker.py` (after `_FALLBACK_IMAGE`, line 28)

```python
# Tools fully blocked from running inside dev containers.
# Counterpart: container-side shim in vergil-docker
# docker/common/gh-guardrail.dockerfile — keep both in sync.
BLOCKED_TOOLS: frozenset[str] = frozenset({"gh"})

# Git subcommands that modify state or talk to a remote.
# Read-only git operations (log, tag, rev-parse, diff, etc.) are
# container-safe and allowed through.
# Counterpart: container-side wrapper in vergil-docker
# docker/common/git-guardrail.dockerfile — keep both in sync.
BLOCKED_GIT_SUBCOMMANDS: frozenset[str] = frozenset({
    "push", "pull", "fetch", "clone",
    "commit", "merge", "rebase", "reset",
    "checkout", "switch",
    "cherry-pick", "revert", "am",
    "stash",
})


def check_blocked_command(command: list[str]) -> str | None:
    if not command:
        return None
    tool_name = command[0].rsplit("/", 1)[-1]
    if tool_name in BLOCKED_TOOLS:
        return (
            f"ERROR: '{tool_name}' is a host-only tool and must not be run "
            f"inside a dev container.\n"
            f"Run '{tool_name}' directly on the host instead of via "
            f"st-docker-run."
        )
    if tool_name == "git" and len(command) > 1:
        subcmd = command[1]
        if subcmd in BLOCKED_GIT_SUBCOMMANDS:
            return (
                f"ERROR: 'git {subcmd}' is a host-only operation and must "
                f"not be run inside a dev container.\n"
                f"Read-only git commands (log, diff, status, etc.) are "
                f"allowed. Run write operations on the host directly."
            )
    return None
```

- `BLOCKED_TOOLS` for tools blocked entirely (currently just `gh`).
- `BLOCKED_GIT_SUBCOMMANDS` for mutating/remote git operations.
- Both constants include a comment cross-referencing the container-side
  counterpart in vergil-docker.
- Extracts basename from argv[0] to handle absolute paths like `/usr/bin/gh`.
- Lives in `docker.py` (shared) so future `st-docker-*` commands can reuse it.

### 1.2 Wire the guard into `docker_run.py`

**File:** `src/standard_tooling/bin/docker_run.py`

Add `check_blocked_command` to the import block (line 15-20).

Insert the guard between the empty-command check (line 63) and the GH_TOKEN
check (line 65):

```python
    blocked_msg = check_blocked_command(command)
    if blocked_msg:
        print(blocked_msg, file=sys.stderr)
        return 1
```

**Ordering rationale:** Before GH_TOKEN validation so that
`st-docker-run -- git push` gets the clear "host-only operation" error, not
the confusing "GH_TOKEN not set" error.

### 1.3 Update `_USAGE` string

**File:** `src/standard_tooling/bin/docker_run.py` (line 22-42)

Add one line to the description:

```
Host-only tools (gh) and mutating git commands are blocked — run them
on the host directly.
```

### 1.4 Tests

**File:** `tests/standard_tooling/test_docker.py`

Add tests for `check_blocked_command()`:

- `["gh", "issue", "create"]` → blocked (fully blocked tool)
- `["/usr/bin/gh", "pr", "list"]` → blocked (absolute path)
- `["git", "push"]` → blocked (mutating subcommand)
- `["git", "commit", "-m", "msg"]` → blocked
- `["git", "pull"]` ��� blocked
- `["git", "fetch", "origin"]` → blocked
- `["git", "log", "--oneline"]` → allowed (read-only)
- `["git", "rev-parse", "--show-toplevel"]` → allowed
- `["git", "diff"]` �� allowed
- `["git", "status"]` → allowed
- `["git", "tag", "-l"]` → allowed
- `["git"]` → allowed (bare git, no subcommand)
- `[]` → allowed (empty)
- `["uv", "run", "pytest"]` → allowed
- `["bash", "-c", "gh pr list"]` → allowed (only inspects argv[0])

**File:** `tests/standard_tooling/test_docker_run.py`

Add integration tests (follow existing patterns with `patch` and
`patch.dict`):

- `st-docker-run -- gh issue create` → returns 1, stderr contains
  "host-only tool"
- `st-docker-run -- git push` → returns 1, stderr contains
  "host-only operation"
- `st-docker-run -- git log` → not blocked, `execvp` called
- `st-docker-run git push` (no `--`) → also returns 1
- `st-docker-run -- uv run pytest` → not blocked, `execvp` called

---

## Phase 2: Container-Side Wrappers (vergil-docker)

### 2.1 Create the `gh` shim fragment

**New file:** `docker/common/gh-guardrail.dockerfile`

```dockerfile
# --- gh guardrail (issue #91) ------------------------------------------------
# gh is a host-only tool — no container-side command needs it.
# Instead of installing the real binary, place a shim that prints
# a clear error. This saves ~50 MB per image.
RUN printf '#!/bin/sh\n\
echo "ERROR: gh is a host-only tool — run it on the host, not inside a dev container." >&2\n\
exit 1\n' > /usr/local/bin/gh && \
    chmod +x /usr/local/bin/gh
```

- No real `gh` binary installed — just a ~3-line error script.
- Placed at `/usr/local/bin/gh` (earlier in PATH than `/usr/bin`).
- POSIX shell for compatibility and minimal overhead.

### 2.2 Create the `git` wrapper fragment

**New file:** `docker/common/git-guardrail.dockerfile`

```dockerfile
# --- git guardrail (issue #91) -----------------------------------------------
# Block mutating/remote git operations inside dev containers.
# Read-only operations (log, diff, status, rev-parse, tag, etc.) pass
# through to the real git at /usr/bin/git.
# Counterpart: BLOCKED_GIT_SUBCOMMANDS in standard-tooling
# src/standard_tooling/lib/docker.py — keep both in sync.
COPY common/git-wrapper.sh /usr/local/bin/git
RUN chmod +x /usr/local/bin/git
```

**New file:** `docker/common/git-wrapper.sh`

```sh
#!/bin/sh
# git guardrail — block mutating/remote operations inside dev containers.
# Read-only operations pass through to the real git.
# Counterpart: BLOCKED_GIT_SUBCOMMANDS in standard-tooling
# src/standard_tooling/lib/docker.py — keep both in sync.
case "$1" in
  push|pull|fetch|clone|commit|merge|rebase|reset|checkout|switch|cherry-pick|revert|am|stash)
    echo "ERROR: 'git $1' is a host-only operation — run it on the host, not inside a dev container." >&2
    echo "Read-only git commands (log, diff, status, etc.) are allowed." >&2
    exit 1
    ;;
esac
exec /usr/bin/git "$@"
```

- The wrapper is a separate file (not inlined via `printf`) because
  the `case` block is more readable and maintainable as a standalone
  script.
- Uses `COPY` in the dockerfile fragment; `generate.sh` resolves paths
  relative to `docker/`, so `common/git-wrapper.sh` is in the build
  context.
- Falls through to `exec /usr/bin/git "$@"` for allowed operations —
  zero overhead for read-only commands.

### 2.3 Update all six templates

**Remove** `# @include common/github-cli.dockerfile` from each template.
**Add** `# @include common/gh-guardrail.dockerfile` in its place.
**Add** `# @include common/git-guardrail.dockerfile` as the **last include**
in each template — after all `standard-tooling-*` fragments.

The git wrapper must come last because `standard-tooling-pip.dockerfile`
runs `git clone` at build time, and `standard-tooling-uv.dockerfile` runs
`uv pip install ... @ git+https://...` which clones internally. If the
wrapper is installed before those fragments, the image build itself fails.

Example resulting include order for `base/Dockerfile.template`:

```
# @include common/node-markdownlint.dockerfile
# @include common/gh-guardrail.dockerfile
# @include common/validation-tools.dockerfile
...
# @include common/standard-tooling-uv.dockerfile
# @include common/git-guardrail.dockerfile
```

Example for non-Python templates (e.g., `go/Dockerfile.template`):

```
# @include common/node-markdownlint.dockerfile
# @include common/gh-guardrail.dockerfile
# @include common/validation-tools.dockerfile
# @include common/python-support.dockerfile
...
# @include common/standard-tooling-pip.dockerfile
# @include common/git-guardrail.dockerfile
```

### 2.4 Update CLAUDE.md

In the "Common Layer" section, replace the `gh` entry:

```
- **gh** — removed from containers (host-only tool, issue #91); a shim
  prints an error if invoked
- **git** — read-write/remote operations blocked inside containers via
  wrapper (issue #91); read-only operations allowed
```

### 2.5 Delete `docker/common/github-cli.dockerfile`

This fragment is no longer included by any template. Remove it.

---

## Sequencing

1. **Phase 1 first** (standard-tooling): host-side guard provides immediate
   protection with zero risk of breaking existing workflows. Effective on
   next standard-tooling release. No Docker image rebuild needed.
2. **Phase 2 second** (vergil-docker): container-side wrappers
   require image rebuild and publish. Effective when downstream repos pull
   updated images.

The two phases are independent — neither blocks the other.

---

## Edge Case Matrix

<!-- markdownlint-disable MD013 -->

| Scenario | Host guard | Container wrapper | Result |
|----------|-----------|-------------------|--------|
| `st-docker-run -- gh issue create` | Blocks | N/A | **Blocked** |
| `st-docker-run -- /usr/bin/gh pr list` | Blocks (extracts basename) | N/A | **Blocked** |
| `st-docker-run -- git push` | Blocks (mutating subcmd) | N/A | **Blocked** |
| `st-docker-run -- git log` | Passes (read-only) | Passes | **Works** |
| `st-docker-run -- bash -c "gh pr list"` | Passes (sees `bash`) | gh shim blocks | **Blocked** |
| `st-docker-run -- bash -c "git push"` | Passes (sees `bash`) | git wrapper blocks | **Blocked** |
| `st-docker-run -- bash -c "git log"` | Passes | git wrapper passes | **Works** |
| `st-docker-run -- st-validate` | Passes | Not triggered | **Works** |
| `git-cliff` inside container | N/A | git wrapper passes (read-only) | **Works** |
| `validate_local_common_container` (uses git) | N/A | git wrapper passes (read-only) | **Works** |
| `uv pip install ... @ git+https://...` (build time) | N/A | Wrapper not yet installed (later layer) | **Works** |
| `uv sync` / `pip install` from git URL (runtime) | N/A | git wrapper blocks `clone` | **Blocked** |

<!-- markdownlint-enable MD013 -->

**Note on runtime git clones:** If `uv sync` or `pip install` from a git
URL runs at container startup (not build time), the wrapper blocks `clone`.
This is correct — dependency installation from git URLs at runtime is a
host-side concern. Container startup should use pre-built wheels or the
lockfile, not live git clones.

---

## Verification

### Phase 1 (standard-tooling)

1. `uv run pytest tests/ -v` — all existing + new tests pass
2. `st-docker-run -- gh issue list` → error: "host-only tool"
3. `st-docker-run -- git push` → error: "host-only operation"
4. `st-docker-run -- git log --oneline` → works normally
5. `st-docker-run -- uv run pytest tests/` → works normally

### Phase 2 (vergil-docker)

1. `docker/generate.sh && hadolint docker/*/Dockerfile` — lint clean
2. `shellcheck docker/common/git-wrapper.sh` — lint clean
3. Build one image locally:
   `docker/generate.sh base && docker build -t dev-base:test docker/base/`
4. `docker run --rm dev-base:test gh --version` → error, exit 1
5. `docker run --rm dev-base:test git --version` → works (read-only)
6. `docker run --rm dev-base:test git log --oneline -5` → works
7. `docker run --rm dev-base:test git push` → error, exit 1
8. `docker run --rm dev-base:test git commit -m test` → error, exit 1
9. `shellcheck docker/build.sh docker/generate.sh` — lint clean
