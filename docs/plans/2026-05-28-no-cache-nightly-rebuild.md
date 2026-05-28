# No-Cache Nightly Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee fresh apt packages by running nightly Docker builds with no cache, while preserving full caching for intraday CD builds.

**Architecture:** Add a `no-cache` boolean input to the reusable `cd-docker-publish.yml` workflow that conditionally disables registry caching. The nightly jobs in `ops.yml` pass `no-cache: true`; CD builds in `cd.yml` omit it (defaults to `false`).

**Tech Stack:** GitHub Actions reusable workflows, Docker buildx, `docker/build-push-action`

**Spec:** `docs/specs/2026-05-28-no-cache-nightly-rebuild-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `.github/workflows/cd-docker-publish.yml` | Modify | Add `no-cache` input; conditional cache params on both build steps |
| `.github/workflows/ops.yml` | Modify | Rename nightly job; add prod nightly job; pass `no-cache: true` |

---

### Task 1: Add `no-cache` input to `cd-docker-publish.yml`

**Files:**
- Modify: `.github/workflows/cd-docker-publish.yml:4-9`

- [ ] **Step 1: Add the `no-cache` input to `workflow_call`**

In `.github/workflows/cd-docker-publish.yml`, add the `no-cache` input after the existing `image-prefix` input. The current block (lines 4–9):

```yaml
on:
  workflow_call:
    inputs:
      image-prefix:
        description: "Image name prefix (dev or prod)"
        type: string
        required: true
```

Change to:

```yaml
on:
  workflow_call:
    inputs:
      image-prefix:
        description: "Image name prefix (dev or prod)"
        type: string
        required: true
      no-cache:
        description: "Skip registry cache (for nightly fresh rebuilds)"
        type: boolean
        required: false
        default: false
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/cd-docker-publish.yml
git commit -m "ci(cd): add no-cache input to cd-docker-publish (#304)"
```

---

### Task 2: Make cache parameters conditional in `build-scan-push` job

**Files:**
- Modify: `.github/workflows/cd-docker-publish.yml:115-116`

- [ ] **Step 1: Replace cache lines in the `build-scan-push` build step**

In the `Build and push candidate` step of the `build-scan-push` job, the current cache lines (lines 115–116):

```yaml
          cache-from: type=registry,ref=${{ env.CACHE_TAG }}
          cache-to: type=registry,ref=${{ env.CACHE_TAG }},mode=max
```

Change to:

```yaml
          cache-from: ${{ inputs.no-cache && '' || format('type=registry,ref={0}', env.CACHE_TAG) }}
          cache-to: ${{ inputs.no-cache && '' || format('type=registry,ref={0},mode=max', env.CACHE_TAG) }}
```

When `inputs.no-cache` is `true`, these evaluate to empty string (no caching). When `false`, they produce the original values.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/cd-docker-publish.yml
git commit -m "ci(cd): conditional cache in build-scan-push job (#304)"
```

---

### Task 3: Make cache parameters conditional in `publish-base` job

**Files:**
- Modify: `.github/workflows/cd-docker-publish.yml:248-249`

- [ ] **Step 1: Replace cache lines in the `publish-base` build step**

In the `Build and push candidate` step of the `publish-base` job, the current cache lines (lines 248–249):

```yaml
          cache-from: type=registry,ref=${{ env.CACHE_TAG }}
          cache-to: type=registry,ref=${{ env.CACHE_TAG }},mode=max
```

Change to:

```yaml
          cache-from: ${{ inputs.no-cache && '' || format('type=registry,ref={0}', env.CACHE_TAG) }}
          cache-to: ${{ inputs.no-cache && '' || format('type=registry,ref={0},mode=max', env.CACHE_TAG) }}
```

Identical pattern to Task 2 — both build steps must be updated.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/cd-docker-publish.yml
git commit -m "ci(cd): conditional cache in publish-base job (#304)"
```

---

### Task 4: Update nightly rebuilds in `ops.yml`

**Files:**
- Modify: `.github/workflows/ops.yml:26-35`

- [ ] **Step 1: Rename `nightly-rebuild` to `nightly-rebuild-dev` and pass `no-cache: true`**

The current `nightly-rebuild` job (lines 26–35):

```yaml
  nightly-rebuild:
    uses: ./.github/workflows/cd-docker-publish.yml
    with:
      image-prefix: dev
    permissions:
      packages: write
      contents: read
      security-events: write
      attestations: write
      id-token: write
```

Replace with:

```yaml
  nightly-rebuild-dev:
    uses: ./.github/workflows/cd-docker-publish.yml
    with:
      image-prefix: dev
      no-cache: true
    permissions:
      packages: write
      contents: read
      security-events: write
      attestations: write
      id-token: write
```

- [ ] **Step 2: Add `nightly-rebuild-prod` job after `nightly-rebuild-dev`**

Add immediately after the `nightly-rebuild-dev` job block:

```yaml
  nightly-rebuild-prod:
    uses: ./.github/workflows/cd-docker-publish.yml
    with:
      image-prefix: prod
      no-cache: true
    permissions:
      packages: write
      contents: read
      security-events: write
      attestations: write
      id-token: write
```

The two nightly jobs have no dependency on each other and run in parallel.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ops.yml
git commit -m "ci(ops): nightly no-cache rebuilds for dev and prod (#304)"
```

---

### Task 5: Validate

- [ ] **Step 1: Run validation**

```bash
vrg-container-run -- vrg-validate
```

Expected: all checks pass (actionlint, yamllint, shellcheck, markdownlint, hadolint).

If actionlint reports issues with the conditional expressions, the `format()` function and `&&`/`||` short-circuit expressions are valid GitHub Actions expression syntax — investigate whether the issue is a false positive or a real syntax problem.

- [ ] **Step 2: Fix any issues and commit**

If validation finds problems, fix them and commit:

```bash
git add -A
git commit -m "fix(cd): address validation findings (#304)"
```

If validation passes clean, skip this step.
