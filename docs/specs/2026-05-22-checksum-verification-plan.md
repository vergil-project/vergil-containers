# Checksum Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add SHA-256/SHA-512 checksum verification to binary tool downloads that publish checksums (actionlint, git-cliff, hadolint, scorecard).

**Architecture:** Each verified tool switches from pipe-to-tar or direct download to a three-step pattern: download artifact to `/tmp`, verify against the upstream checksums file, then extract/install. Unverified tools (shellcheck, shfmt) keep their existing patterns unchanged.

**Tech Stack:** Dockerfile `RUN` shell commands, `sha256sum -c`, `sha512sum -c`, `curl`, `grep -F`

**Spec:** `docs/specs/2026-05-22-checksum-verification-design.md`

---

## File Map

- **Modify:** `docker/common/validation-tools.dockerfile` — add checksum verification for actionlint, git-cliff, hadolint (lines 27-36)
- **Modify:** `docker/common/security-tools.dockerfile` — add checksum verification for scorecard (lines 5-6)

No new files. No test files — verification is via hadolint + Docker build.

---

### Task 1: Add checksum verification to validation-tools.dockerfile

**Files:**
- Modify: `docker/common/validation-tools.dockerfile:27-36`

The current file downloads 5 tools in a single `RUN` block. Three tools (actionlint, git-cliff, hadolint) get checksum verification. Two tools (shellcheck, shfmt) stay unchanged.

- [ ] **Step 1: Replace the actionlint download (line 31-32)**

Change the current pipe-to-tar pattern to download-verify-extract.

Current:
```dockerfile
    curl -fsSL "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_${AL_ARCH}.tar.gz" \
      | tar -xz -C /usr/local/bin/ actionlint && \
```

Replace with:
```dockerfile
    AL_TARBALL="actionlint_${ACTIONLINT_VERSION}_linux_${AL_ARCH}.tar.gz" && \
    curl -fsSL "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/${AL_TARBALL}" \
      -o "/tmp/${AL_TARBALL}" && \
    curl -fsSL "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_checksums.txt" \
      | grep -F "${AL_TARBALL}" | (cd /tmp && sha256sum -c) && \
    tar -xzf "/tmp/${AL_TARBALL}" -C /usr/local/bin/ actionlint && \
    rm "/tmp/${AL_TARBALL}" && \
```

- [ ] **Step 2: Replace the git-cliff download (line 33-34)**

Change the current pipe-to-tar pattern to download-verify-extract.

Current:
```dockerfile
    curl -fsSL "https://github.com/orhun/git-cliff/releases/download/v${GIT_CLIFF_VERSION}/git-cliff-${GIT_CLIFF_VERSION}-${GC_ARCH}.tar.gz" \
      | tar -xz --strip-components=1 -C /usr/local/bin/ "git-cliff-${GIT_CLIFF_VERSION}/git-cliff" && \
```

Replace with:
```dockerfile
    GC_TARBALL="git-cliff-${GIT_CLIFF_VERSION}-${GC_ARCH}.tar.gz" && \
    curl -fsSL "https://github.com/orhun/git-cliff/releases/download/v${GIT_CLIFF_VERSION}/${GC_TARBALL}" \
      -o "/tmp/${GC_TARBALL}" && \
    curl -fsSL "https://github.com/orhun/git-cliff/releases/download/v${GIT_CLIFF_VERSION}/${GC_TARBALL}.sha512" \
      | (cd /tmp && sha512sum -c) && \
    tar -xzf "/tmp/${GC_TARBALL}" --strip-components=1 -C /usr/local/bin/ "git-cliff-${GIT_CLIFF_VERSION}/git-cliff" && \
    rm "/tmp/${GC_TARBALL}" && \
```

- [ ] **Step 3: Replace the hadolint download (line 35-36)**

Change the current direct download to download-verify-move.

Current:
```dockerfile
    curl -fsSL "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-${HL_ARCH}" \
      -o /usr/local/bin/hadolint && chmod +x /usr/local/bin/hadolint
```

Replace with:
```dockerfile
    curl -fsSL "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-${HL_ARCH}" \
      -o "/tmp/hadolint-${HL_ARCH}" && \
    curl -fsSL "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-${HL_ARCH}.sha256" \
      | (cd /tmp && sha256sum -c) && \
    mv "/tmp/hadolint-${HL_ARCH}" /usr/local/bin/hadolint && chmod +x /usr/local/bin/hadolint
```

Note: this is the last command in the `RUN` block — no trailing `&& \`.

- [ ] **Step 4: Verify the complete file**

Read the complete file and verify:
- shellcheck and shfmt lines are unchanged
- actionlint, git-cliff, hadolint each follow the download-verify-extract/move pattern
- All `&&` line continuations are correct (no missing, no trailing)
- The `case` block and architecture variables are untouched

---

### Task 2: Add checksum verification to security-tools.dockerfile

**Files:**
- Modify: `docker/common/security-tools.dockerfile:5-6`

- [ ] **Step 1: Replace the scorecard download**

Current:
```dockerfile
RUN curl -fsSL "https://github.com/ossf/scorecard/releases/download/v${SCORECARD_VERSION}/scorecard_${SCORECARD_VERSION}_linux_${TARGETARCH}.tar.gz" \
      | tar -xz -C /usr/local/bin/ scorecard
```

Replace with:
```dockerfile
RUN SC_TARBALL="scorecard_${SCORECARD_VERSION}_linux_${TARGETARCH}.tar.gz" && \
    curl -fsSL "https://github.com/ossf/scorecard/releases/download/v${SCORECARD_VERSION}/${SC_TARBALL}" \
      -o "/tmp/${SC_TARBALL}" && \
    curl -fsSL "https://github.com/ossf/scorecard/releases/download/v${SCORECARD_VERSION}/scorecard_checksums.txt" \
      | grep -F "${SC_TARBALL}" | (cd /tmp && sha256sum -c) && \
    tar -xzf "/tmp/${SC_TARBALL}" -C /usr/local/bin/ scorecard && \
    rm "/tmp/${SC_TARBALL}"
```

---

### Task 3: Validate with hadolint

- [ ] **Step 1: Run generate.sh to expand templates**

Run from the worktree root:
```bash
cd /Users/pmoore/dev/projects/vergil-project/vergil-docker/.worktrees/issue-235-checksum-verification && docker/generate.sh
```

Expected: exits 0, no output (success is silent).

- [ ] **Step 2: Run hadolint on generated Dockerfiles**

```bash
cd /Users/pmoore/dev/projects/vergil-project/vergil-docker/.worktrees/issue-235-checksum-verification && hadolint docker/*/Dockerfile
```

Expected: exits 0 with no warnings. If hadolint flags new issues in the checksum verification lines (e.g., DL3059 for multiple consecutive `RUN` — should not apply here since we're modifying within existing `RUN` blocks), address them before proceeding.

---

### Task 4: Build a test image

- [ ] **Step 1: Build the base image to verify checksum verification works**

Build `dev-base` for the local architecture only (fastest validation):
```bash
cd /Users/pmoore/dev/projects/vergil-project/vergil-docker/.worktrees/issue-235-checksum-verification && docker build -t dev-base:checksum-test docker/base/
```

Expected: build succeeds. The checksum verification lines will print verification output like `actionlint_1.7.12_linux_amd64.tar.gz: OK` during the build. If a checksum fails, the build will fail with `FILENAME: FAILED` and a non-zero exit.

- [ ] **Step 2: Verify tools are installed**

```bash
docker run --rm dev-base:checksum-test sh -c 'actionlint --version && git-cliff --version && hadolint --version && scorecard version'
```

Expected: each tool prints its version. This confirms the download-verify-extract flow produces working binaries.

- [ ] **Step 3: Clean up test image**

```bash
docker rmi dev-base:checksum-test
```

---

### Task 5: Commit

- [ ] **Step 1: Stage and commit**

```bash
cd /Users/pmoore/dev/projects/vergil-project/vergil-docker/.worktrees/issue-235-checksum-verification && \
vrg-git add docker/common/validation-tools.dockerfile docker/common/security-tools.dockerfile && \
vrg-commit -m "feat(docker): add checksum verification to binary tool downloads

Verify actionlint, hadolint, and scorecard downloads against published
SHA-256 checksums. Verify git-cliff against its published SHA-512
checksum. shellcheck and shfmt are unchanged (no upstream checksums
published).

Closes #235"
```
