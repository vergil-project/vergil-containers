# Add OpenSSF Scorecard CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the OpenSSF Scorecard CLI to dev base images via a new `docker/common/security-tools.dockerfile` fragment.

**Architecture:** New fragment follows the same direct-tarball-download pattern as `validation-tools.dockerfile`. The base image template includes it via `# @include`. TARGETARCH maps 1:1 to scorecard's artifact naming (no arch translation needed).

**Tech Stack:** Dockerfile, bash (generate.sh), hadolint

---

### Task 1: Create `docker/common/security-tools.dockerfile`

**Files:**
- Create: `docker/common/security-tools.dockerfile`

- [ ] **Step 1: Create the fragment**

```dockerfile
# --- Security tools -----------------------------------------------------------
ARG TARGETARCH
ARG SCORECARD_VERSION=5.5.0

RUN curl -fsSL "https://github.com/ossf/scorecard/releases/download/v${SCORECARD_VERSION}/scorecard_${SCORECARD_VERSION}_linux_${TARGETARCH}.tar.gz" \
      | tar -xz -C /usr/local/bin/ scorecard
```

- [ ] **Step 2: Commit**

```bash
git add docker/common/security-tools.dockerfile
git commit -m "feat(docker): add security-tools fragment with scorecard 5.5.0

Closes #234"
```

---

### Task 2: Include the fragment in the base image template

**Files:**
- Modify: `docker/base/Dockerfile.template:18` (after the `validation-tools` include)

- [ ] **Step 1: Add the include directive**

Insert after line 18 (`# @include common/validation-tools.dockerfile`):

```dockerfile
# @include common/security-tools.dockerfile
```

The relevant section of the template should now read:

```dockerfile
# @include common/validation-tools.dockerfile
# @include common/security-tools.dockerfile
```

- [ ] **Step 2: Run `generate.sh` and lint**

```bash
docker/generate.sh base
hadolint docker/base/Dockerfile
```

Expected: hadolint passes with no warnings.

- [ ] **Step 3: Commit**

```bash
git add docker/base/Dockerfile.template
git commit -m "feat(docker): include security-tools in dev-base template"
```

---

### Task 3: Update CLAUDE.md Common Layer inventory

**Files:**
- Modify: `CLAUDE.md:186` (after the hadolint entry in the Common Layer list)

- [ ] **Step 1: Add scorecard to the tool list**

Insert after the `- **hadolint** (\`2.14.0\`)` line:

```markdown
- **scorecard** (`5.5.0`)
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add scorecard to Common Layer inventory in CLAUDE.md"
```

---

### Task 4: Build and verify

- [ ] **Step 1: Build the base image locally**

```bash
docker/generate.sh base
docker build --build-arg TARGETARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/') -t dev-base:test docker/base/
```

Expected: build completes successfully.

- [ ] **Step 2: Verify the binary exists and runs**

```bash
docker run --rm dev-base:test scorecard version
```

Expected: outputs scorecard version string containing `5.5.0`.

- [ ] **Step 3: Check image size impact**

```bash
docker images dev-base:test --format "{{.Size}}"
```

Note the size for the PR description (expected ~15-20 MB increase from the scorecard binary layer).

---

## Verification Summary

| Check | Command | Expected |
|-------|---------|----------|
| Fragment lint | `hadolint docker/base/Dockerfile` | No warnings |
| Binary present | `docker run --rm dev-base:test which scorecard` | `/usr/local/bin/scorecard` |
| Version correct | `docker run --rm dev-base:test scorecard version` | Contains `5.5.0` |
| Generate idempotent | `docker/generate.sh base && git diff` | No unexpected changes |
