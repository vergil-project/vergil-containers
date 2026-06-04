# OSS Container Runtime for Local Builds — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `docker/build.sh` prefer `nerdctl` (Lima + containerd) over the
Docker client, with `docker` as an optional fallback, so no paid/proprietary
client is required to build images locally.

**Architecture:** A small inline runtime-detection block at the top of
`docker/build.sh` resolves a `runtime` variable (override → nerdctl → docker),
validates it exists, and probes the buildkit backend when nerdctl is selected.
Every hard-coded `docker` invocation becomes `"$runtime"`; the builder-cache
prune is made runtime-aware because `nerdctl builder prune` has no `--filter`.
Docs are softened from "Docker required" to "any OCI runtime, nerdctl
preferred". No shared helper, no renaming.

**Tech Stack:** Bash, nerdctl/containerd (Lima), Docker (fallback). Validation
via `vrg-container-run -- vrg-validate` (shellcheck, shfmt, markdownlint).

**Spec:** `docs/specs/2026-06-02-oss-runtime-build-design.md`

---

## Repo-specific conventions (read before starting)

- **Work from the worktree** `.worktrees/issue-322-oss-runtime-build/` on
  branch `feature/322-oss-runtime-build`. Use absolute paths or `cd` into it.
- **Git:** use `vrg-git` (not `git`). **Commits:** use `vrg-commit`, never
  `git commit`. Signature:
  `vrg-commit --type <type> --scope <scope> --message <subject> --body <body>`.
  It builds the `type(scope): subject` conventional-commit line for you — pass
  the subject *without* the `type(scope):` prefix.
- **Validation:** the ONLY validation command is
  `vrg-container-run -- vrg-validate` (run from inside the worktree). Do not
  invoke shellcheck/shfmt/markdownlint directly. If shfmt or markdownlint
  reports a formatting diff, hand-edit to match what the diff shows (you
  cannot run the auto-fixers standalone).
- **Prose wrapping:** `README.md` and `CLAUDE.md` wrap prose at ~68 chars —
  match the surrounding lines when inserting text.
- End every commit body with the trailer:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

- **Modify:** `docker/build.sh` — runtime detection + validation + buildkit
  precondition; swap `docker` → `"$runtime"`; runtime-aware builder prune;
  header-comment update. (One file, one responsibility: build the image
  matrix locally.)
- **Modify:** `CLAUDE.md` — soften the "Docker is the only prerequisite"
  design principle and the local-build example.
- **Modify:** `README.md` — soften "Docker-first" language and note runtime
  auto-detection near the build examples.

No new files. No tests directory exists for `build.sh`; verification is
shellcheck (via `vrg-validate`) plus concrete behavioral commands shown in
each task.

---

## Task 1: Make `docker/build.sh` runtime-agnostic

**Files:**
- Modify: `docker/build.sh`

The current script (HEAD) hard-codes `docker` in four places and has a header
comment describing prune behavior. This task transforms the whole file in one
coherent, still-working commit (no broken intermediate states).

- [ ] **Step 1: Insert the runtime-detection + validation + buildkit
  precondition block.**

In `docker/build.sh`, the lines immediately after `set -euo pipefail` are:

```bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"

build() {
```

Insert the new block between the `script_dir=...` line and the blank line
before `build() {`, so it becomes:

```bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"

# Select the container runtime: prefer nerdctl (OSS, Lima + containerd),
# fall back to docker.  VRG_CONTAINER_RUNTIME overrides auto-detection.
runtime="${VRG_CONTAINER_RUNTIME:-}"
if [ -z "$runtime" ]; then
  if command -v nerdctl >/dev/null 2>&1; then
    runtime=nerdctl
  elif command -v docker >/dev/null 2>&1; then
    runtime=docker
  else
    echo "ERROR: no container runtime found (need nerdctl or docker)" >&2
    exit 1
  fi
fi

# Validate the resolved runtime (covers the override and auto-detect paths)
# so a typo'd or uninstalled runtime fails here with a clear message instead
# of later as a raw "command not found".
if ! command -v "$runtime" >/dev/null 2>&1; then
  echo "ERROR: container runtime '$runtime' not found on PATH (set VRG_CONTAINER_RUNTIME to nerdctl or docker, or leave it unset to auto-detect)" >&2
  exit 1
fi

# nerdctl build needs a reachable containerd/buildkit backend.  Probe it up
# front so a missing backend is an actionable error, not a cryptic mid-build
# failure.
if [ "$runtime" = "nerdctl" ] && ! nerdctl info >/dev/null 2>&1; then
  echo "ERROR: nerdctl cannot reach its containerd/buildkit backend. Ensure the Lima VM is running and provisions buildkitd (see the vergil-vm Lima template). To use Docker instead, set VRG_CONTAINER_RUNTIME=docker." >&2
  exit 1
fi

build() {
```

(The two `echo` messages are intentionally single-line to avoid shfmt
line-continuation reformatting.)

- [ ] **Step 2: Swap `docker build` in the `build()` function.**

Inside `build()`, change:

```bash
  docker build \
    --build-arg "${version_arg}=${version_val}" \
    -t "dev-${lang}:${version_val}" \
    "${script_dir}/${lang}"
```

to:

```bash
  "$runtime" build \
    --build-arg "${version_arg}=${version_val}" \
    -t "dev-${lang}:${version_val}" \
    "${script_dir}/${lang}"
```

- [ ] **Step 3: Swap `docker build` for the base image.**

Change:

```bash
echo "Building dev-base:latest ..."
docker build -t "dev-base:latest" "${script_dir}/base"
```

to:

```bash
echo "Building dev-base:latest ..."
"$runtime" build -t "dev-base:latest" "${script_dir}/base"
```

- [ ] **Step 4: Make the prune step runtime-aware.**

Change the final two lines:

```bash
docker image prune -f
docker builder prune -af --filter 'until=720h'
```

to:

```bash
"$runtime" image prune -f
if [ "$runtime" = "docker" ]; then
  docker builder prune -af --filter 'until=720h'
else
  # nerdctl builder prune has no --filter; prune dangling cache only to
  # preserve reusable layers across builds.
  "$runtime" builder prune -f
fi
```

- [ ] **Step 5: Update the header comment to match the new prune behavior.**

Near the top of the file, change:

```bash
# After a successful build, dangling images and stale build cache
# (>30 days) are pruned to prevent local disk bloat.  Tagged images
# and volumes are never touched.
```

to:

```bash
# After a successful build, dangling images are pruned and build cache is
# pruned runtime-aware: docker prunes cache older than 30 days, nerdctl
# prunes dangling cache only (nerdctl builder prune has no --filter).
# Tagged images and volumes are never touched.
```

- [ ] **Step 6: Validate.**

Run (from inside the worktree):

```bash
vrg-container-run -- vrg-validate
```

Expected: PASS. shellcheck and shfmt report no issues on `docker/build.sh`.
If shfmt reports a diff, hand-edit `build.sh` to match the shown formatting
(do not run shfmt directly), then re-run.

- [ ] **Step 7: Behavioral check — bad override fails loudly and early.**

This exercises the Step 1 validation guard. It must exit before any build:

```bash
VRG_CONTAINER_RUNTIME=definitely-not-a-runtime docker/build.sh; echo "exit=$?"
```

Expected: prints
`ERROR: container runtime 'definitely-not-a-runtime' not found on PATH ...`
to stderr and `exit=1`. No "Building ..." lines appear.

- [ ] **Step 8: Behavioral check — buildkit precondition does not false-trip.**

Confirm the healthy backend passes the probe:

```bash
nerdctl info >/dev/null 2>&1; echo "nerdctl_info_exit=$?"
```

Expected: `nerdctl_info_exit=0` (so the precondition block will not block a
real build in this environment).

- [ ] **Step 9: Behavioral check — buildkit failure path fires the
  remediation message.**

Exercise the negative branch without disturbing the real daemon: put a stub
`nerdctl` (that fails like an unreachable backend) first on `PATH` for a
single run.

```bash
tmpdir="$(mktemp -d)"
printf '#!/usr/bin/env bash\nexit 1\n' >"$tmpdir/nerdctl"
chmod +x "$tmpdir/nerdctl"
PATH="$tmpdir:$PATH" VRG_CONTAINER_RUNTIME=nerdctl docker/build.sh; echo "exit=$?"
rm -rf "$tmpdir"
```

Expected: prints
`ERROR: nerdctl cannot reach its containerd/buildkit backend. ...` to stderr
and `exit=1`, with no "Building ..." lines. The stub forces `nerdctl info` to
fail, hitting the precondition branch; the real backend is untouched.

- [ ] **Step 10: Commit.**

```bash
vrg-git add docker/build.sh
vrg-commit --type feat --scope build \
  --message "prefer nerdctl over docker in build.sh, docker fallback (#322)" \
  --body "Add inline runtime detection to docker/build.sh: VRG_CONTAINER_RUNTIME override, else nerdctl, else docker, else fail. Validate the resolved runtime so an uninstalled/typo'd override fails with a clear message. Probe the nerdctl buildkit backend up front with a remediation message. Swap all docker invocations for the detected runtime and make the builder-cache prune runtime-aware (nerdctl builder prune has no --filter). Update the header comment to match.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Soften the documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Update the CLAUDE.md design principle.**

In `CLAUDE.md`, under `### Design Principles`, change:

```markdown
- **No host requirements** — Docker is the only prerequisite for
  local development
```

to:

```markdown
- **No host requirements** — a single OCI container runtime is the only
  prerequisite for local development (nerdctl/Lima preferred, Docker
  supported)
```

- [ ] **Step 2: Note runtime auto-detection in the CLAUDE.md build section.**

In `CLAUDE.md`, under `### Building Images Locally`, the text between the two
code blocks reads:

```markdown
docker/build.sh                 # Build all images for every version in the matrix
```

Immediately after that fenced block (before the line
`Individual images can be built with:`), insert this paragraph:

```markdown
`build.sh` auto-detects the runtime — it prefers `nerdctl` (Lima +
containerd) and falls back to `docker`. Set `VRG_CONTAINER_RUNTIME` to
force one. The single-image command below works with either `nerdctl
build` or `docker build`.
```

- [ ] **Step 3: Soften README "Docker-first" language.**

In `README.md`, line 6 currently reads:

```markdown
used by CI and local Docker-first development across all managed
```

Change to:

```markdown
used by CI and local container-based development across all managed
```

- [ ] **Step 4: Note runtime auto-detection in the README build section.**

In `README.md`, the "build all images locally" block is:

```markdown
Or build all images locally:

```bash
docker/build.sh
```

Build a single image:
```

Insert a paragraph between the `docker/build.sh` fenced block and
`Build a single image:` so it becomes:

```markdown
Or build all images locally:

```bash
docker/build.sh
```

`build.sh` auto-detects the container runtime — it prefers `nerdctl`
(Lima + containerd) and falls back to `docker`. Set
`VRG_CONTAINER_RUNTIME` to force a specific one. The single-image
commands below work with either `nerdctl build` or `docker build`.

Build a single image:
```

- [ ] **Step 5: Validate.**

```bash
vrg-container-run -- vrg-validate
```

Expected: PASS. markdownlint reports no issues on `README.md` / `CLAUDE.md`.
If markdownlint flags line length or list formatting, re-wrap the inserted
prose to ~68 chars to match the surrounding lines, then re-run.

- [ ] **Step 6: Commit.**

```bash
vrg-git add CLAUDE.md README.md
vrg-commit --type docs --scope build \
  --message "describe OSS runtime preference for local builds (#322)" \
  --body "Soften the 'Docker is the only prerequisite' design principle to 'a single OCI runtime (nerdctl/Lima preferred, Docker supported)', and note that build.sh auto-detects the runtime (nerdctl, falling back to docker) in the CLAUDE.md and README build sections.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Round-trip acceptance — build under nerdctl and confirm usable

**Files:** none (verification only — no commit).

This proves the namespace continuity called out in the spec: a nerdctl build
must produce an image the run path can actually consume, not merely a
"successful" build. Build a single image rather than the full matrix to keep
it fast.

- [ ] **Step 1: Confirm nerdctl is the runtime that will be selected.**

```bash
command -v nerdctl && echo "nerdctl present"
```

Expected: a path and `nerdctl present` (so `build.sh` auto-selects nerdctl).

- [ ] **Step 2: Generate the Python Dockerfile.**

```bash
docker/generate.sh python
```

Expected: exits 0; `docker/python/Dockerfile` is (re)generated.

- [ ] **Step 3: Build one image with nerdctl (the path `build.sh` takes).**

```bash
nerdctl build --build-arg PYTHON_VERSION=3.14 -t dev-python:3.14 docker/python/
```

Expected: build completes successfully (buildkit runs; final image tagged).

- [ ] **Step 4: Confirm the image is in the store.**

```bash
nerdctl images | grep dev-python
```

Expected: a `dev-python  3.14` row is listed.

- [ ] **Step 5: Confirm the image is consumable (namespace continuity).**

```bash
nerdctl run --rm dev-python:3.14 python --version
```

Expected: prints `Python 3.14.x`. A successful run proves the freshly built
image is usable by the run path, not stranded in a mismatched namespace.

- [ ] **Step 6 (optional): Full-matrix smoke.**

If you want end-to-end coverage of the actual script (slow — builds the whole
matrix), run:

```bash
docker/build.sh
```

Expected: every image builds, `All images built successfully.` prints, and
the runtime-aware prune runs without error.

---

## Task 4: File the `vergil-vm` buildkitd tracking issue

**Files:** none in this repo (cross-repo issue + one spec cross-reference line).

The spec assigns the durable fix — guaranteeing `buildkitd` in the Lima VM —
to `vergil-vm`. This task creates the tracking artifact so the handoff does
not evaporate when this branch merges, then links it back from the spec.

- [ ] **Step 1: Draft the issue body.**

Write `/tmp/vergil-vm-buildkitd.md` with exactly:

```markdown
## Goal

Guarantee `buildkitd` is installed and running in the Lima VM so
`nerdctl build` works out of the box for local image builds.

## Why

vergil-docker's `docker/build.sh` now prefers `nerdctl` over `docker`
(vergil-project/vergil-docker#322). `nerdctl build` requires a reachable
buildkit backend. `build.sh` probes it and fails with a remediation message
if absent, but the durable fix is to provision buildkitd in the VM the
ecosystem uses, so the failure never happens in normal use.

## Acceptance

- The Lima template provisions and starts `buildkitd` (rootless containerd
  worker is acceptable).
- A freshly created VM can run `nerdctl build` with no manual setup.

## Related

- vergil-project/vergil-docker#322
```

- [ ] **Step 2: Create the issue.**

```bash
vrg-gh issue create --repo vergil-project/vergil-vm \
  --title "Guarantee buildkitd in the Lima VM for nerdctl build" \
  --body-file /tmp/vergil-vm-buildkitd.md
```

Expected: prints the new issue URL. Note the issue number — it feeds Step 3.

- [ ] **Step 3: Cross-reference the issue from the spec.**

In `docs/specs/2026-06-02-oss-runtime-build-design.md`, the "Buildkit
precondition" section's handoff paragraph contains the sentence:

```markdown
A tracking issue for that guarantee is filed against `vergil-vm` as part of
this work (see the implementation plan); its link is recorded here once
created.
```

Replace that sentence with the concrete link, using the number from Step 2
(shown here as `<N>`):

```markdown
The durable fix is tracked in vergil-project/vergil-vm#<N>.
```

- [ ] **Step 4: Commit the spec cross-reference.**

```bash
vrg-git add docs/specs/2026-06-02-oss-runtime-build-design.md
vrg-commit --type docs --scope spec \
  --message "link vergil-vm buildkitd tracking issue (#322)" \
  --body "Record the concrete vergil-vm issue that owns guaranteeing buildkitd in the Lima VM, closing the handoff loop from the buildkit precondition.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- Runtime detection + `VRG_CONTAINER_RUNTIME` override → Task 1 Step 1. ✔
- Override validation (resolved-runtime existence check) → Task 1 Step 1 +
  Task 1 Step 7. ✔
- Buildkit precondition + remediation message → Task 1 Step 1 (code), Task 1
  Step 8 (healthy path passes), Task 1 Step 9 (failure path fires the
  remediation message via a stubbed backend). ✔
- `vergil-vm` buildkitd handoff actioned → Task 4 (file the tracking issue +
  cross-reference it from the spec). ✔
- Swap all `docker` invocations → Task 1 Steps 2–4. ✔
- Runtime-aware builder prune (no `--filter` on nerdctl) → Task 1 Step 4. ✔
- Header-comment update → Task 1 Step 5. ✔
- Docs (CLAUDE.md principle + example, README language) → Task 2. ✔
- Validation: shellcheck/shfmt via vrg-validate → Task 1 Step 6, Task 2
  Step 5. ✔
- Validation: nerdctl build round-trip + consumable image → Task 3. ✔
- Validation: `VRG_CONTAINER_RUNTIME=docker` path syntactically intact →
  static review; the docker branch in Steps 1 and 4 is plain unconditional
  code, exercised by shellcheck. ✔

**Placeholder scan:** none — every code/command step shows exact content.

**Type/identifier consistency:** the variable is `runtime` and the override
is `VRG_CONTAINER_RUNTIME` in every task; subcommands (`build`, `image
prune`, `builder prune`) match across the detection, substitution, and prune
steps.
