# Multi-Arch (ARM64) Dev Container Images — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish multi-arch (`linux/amd64` + `linux/arm64`) dev container images so Apple Silicon Macs run natively without emulation warnings.

**Architecture:** Parameterize binary tool downloads in `validation-tools.dockerfile` using Docker buildx's `TARGETARCH` injection. Restructure the CI workflow to use `docker/build-push-action` with multi-platform builds, a candidate-tag staging flow with dual-platform Trivy scanning, attestation before promotion, and registry-based layer caching.

**Tech Stack:** Docker buildx, `docker/build-push-action`, `docker/setup-qemu-action`, `docker/setup-buildx-action`, GHCR, Trivy, GitHub Actions attestations.

**Issue:** [#111](https://github.com/vergil-project/vergil-docker/issues/111)
**Design spec:** [`docs/specs/2026-05-03-multi-arch-images-design.md`](../../specs/2026-05-03-multi-arch-images-design.md)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `docker/common/validation-tools.dockerfile` | Rewrite | Architecture-aware binary downloads for all 5 tools |
| `.github/workflows/docker-publish.yml` | Rewrite | Multi-arch build, scan, attest, promote workflow |

No other files are created or modified. `docker/build.sh` and `docker/generate.sh` remain unchanged — local builds stay single-platform (native arch).

---

## Task 1: Validate Prerequisites

Before writing code, confirm the two prerequisite conditions from the design spec.

**Files:** None modified — validation only.

- [ ] **Step 1: Verify ARM64 binary tool download URLs**

Confirm each tool's arm64 artifact exists at the expected URL by checking HTTP 200 responses:

```bash
curl -sI -o /dev/null -w "%{http_code}" "https://github.com/koalaman/shellcheck/releases/download/v0.11.0/shellcheck-v0.11.0.linux.aarch64.tar.xz"
# Expected: 302 (GitHub redirect to release asset)

curl -sI -o /dev/null -w "%{http_code}" "https://github.com/mvdan/sh/releases/download/v3.12.0/shfmt_v3.12.0_linux_arm64"
# Expected: 302

curl -sI -o /dev/null -w "%{http_code}" "https://github.com/rhysd/actionlint/releases/download/v1.7.11/actionlint_1.7.11_linux_arm64.tar.gz"
# Expected: 302

curl -sI -o /dev/null -w "%{http_code}" "https://github.com/orhun/git-cliff/releases/download/v2.8.0/git-cliff-2.8.0-aarch64-unknown-linux-gnu.tar.gz"
# Expected: 302

curl -sI -o /dev/null -w "%{http_code}" "https://github.com/hadolint/hadolint/releases/download/v2.14.0/hadolint-linux-arm64"
# Expected: 302
```

If any return 404, stop and investigate the correct naming for that tool's arm64 release artifact. Update the architecture mapping table in the design spec if needed.

- [ ] **Step 2: Validate semgrep ARM64 compilation**

```bash
docker run --rm --platform linux/arm64 python:3.14-slim bash -c \
  "apt-get update && apt-get install -y --no-install-recommends build-essential curl && \
   pip install --no-cache-dir uv && \
   uv tool install semgrep && \
   echo 'SUCCESS: semgrep installed on arm64'"
```

Expected output: `SUCCESS: semgrep installed on arm64`

If this fails, file a follow-up issue for a conditional install path in `docker/base/Dockerfile.template` and note it as a known limitation — the base image will be amd64-only until resolved. The other images (python, java, go, ruby, rust) can still proceed with multi-arch.

- [ ] **Step 3: Document results**

Record the validated URLs and semgrep result in the issue comment for traceability. If any URL needed correction, update the design spec's architecture mapping table.

---

## Task 2: Rewrite `validation-tools.dockerfile` with Architecture Mapping

**Files:**
- Modify: `docker/common/validation-tools.dockerfile` (full rewrite)

- [ ] **Step 1: Write the new validation-tools.dockerfile**

Replace the entire contents of `docker/common/validation-tools.dockerfile` with:

```dockerfile
# --- Binary tools (no apt packages available) --------------------------------
# Architecture mapping: Docker buildx injects TARGETARCH (amd64 or arm64).
# Each tool uses different naming conventions for its release artifacts.
ARG TARGETARCH

ARG SHELLCHECK_VERSION=0.11.0
ARG SHFMT_VERSION=3.12.0
ARG ACTIONLINT_VERSION=1.7.11
ARG GIT_CLIFF_VERSION=2.8.0
ARG HADOLINT_VERSION=2.14.0

RUN case "${TARGETARCH}" in \
      amd64) \
        SC_ARCH="x86_64" ; \
        SHFMT_ARCH="amd64" ; \
        AL_ARCH="amd64" ; \
        GC_ARCH="x86_64-unknown-linux-gnu" ; \
        HL_ARCH="linux-x86_64" ;; \
      arm64) \
        SC_ARCH="aarch64" ; \
        SHFMT_ARCH="arm64" ; \
        AL_ARCH="arm64" ; \
        GC_ARCH="aarch64-unknown-linux-gnu" ; \
        HL_ARCH="linux-arm64" ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.${SC_ARCH}.tar.xz" \
      | tar -xJ --strip-components=1 -C /usr/local/bin/ "shellcheck-v${SHELLCHECK_VERSION}/shellcheck" && \
    curl -fsSL "https://github.com/mvdan/sh/releases/download/v${SHFMT_VERSION}/shfmt_v${SHFMT_VERSION}_linux_${SHFMT_ARCH}" \
      -o /usr/local/bin/shfmt && chmod +x /usr/local/bin/shfmt && \
    curl -fsSL "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_${AL_ARCH}.tar.gz" \
      | tar -xz -C /usr/local/bin/ actionlint && \
    curl -fsSL "https://github.com/orhun/git-cliff/releases/download/v${GIT_CLIFF_VERSION}/git-cliff-${GIT_CLIFF_VERSION}-${GC_ARCH}.tar.gz" \
      | tar -xz --strip-components=1 -C /usr/local/bin/ "git-cliff-${GIT_CLIFF_VERSION}/git-cliff" && \
    curl -fsSL "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-${HL_ARCH}" \
      -o /usr/local/bin/hadolint && chmod +x /usr/local/bin/hadolint
```

- [ ] **Step 2: Verify the Dockerfile generates and lints correctly**

```bash
docker/generate.sh python
hadolint docker/python/Dockerfile
```

Expected: No lint errors. If hadolint flags shell quoting in the case block, verify whether it's a false positive (hadolint does not always handle multi-line case blocks perfectly).

- [ ] **Step 3: Build locally to confirm the native-arch path works**

```bash
docker build --build-arg PYTHON_VERSION=3.14 -t test-multiarch:python docker/python/
docker run --rm test-multiarch:python shellcheck --version
docker run --rm test-multiarch:python shfmt --version
docker run --rm test-multiarch:python actionlint --version
docker run --rm test-multiarch:python git-cliff --version
docker run --rm test-multiarch:python hadolint --version
```

Expected: All 5 tools report their versions. This confirms the case block works for the host's native arch (likely `arm64` on Apple Silicon, `amd64` on Intel).

- [ ] **Step 4: Commit**

```bash
git add docker/common/validation-tools.dockerfile
git commit -m "feat(images): parameterize binary tool downloads by TARGETARCH

Rewrite validation-tools.dockerfile to use a case block that maps
Docker buildx's TARGETARCH (amd64/arm64) to each tool's release
artifact naming convention. All 5 binary tools (shellcheck, shfmt,
actionlint, git-cliff, hadolint) are consolidated into a single RUN
layer.

Part of #111."
```

---

## Task 3: Rewrite CI Workflow — Job Structure and Matrix

This task restructures the `build-scan-push` and `publish-base` jobs to use buildx with multi-platform builds. The workflow is large, so we split the rewrite across Tasks 3–5.

**Files:**
- Modify: `.github/workflows/docker-publish.yml` (full rewrite of `build-scan-push` and `publish-base` jobs)

- [ ] **Step 1: Rewrite the `build-scan-push` job**

Replace the `build-scan-push` job in `.github/workflows/docker-publish.yml` with:

```yaml
  build-scan-push:
    name: "publish: dev-${{ matrix.language }}:${{ matrix.version }}"
    needs: [hadolint]
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        include:
          - language: ruby
            version: "3.2"
            build-arg: RUBY_VERSION
          - language: ruby
            version: "3.3"
            build-arg: RUBY_VERSION
          - language: ruby
            version: "3.4"
            build-arg: RUBY_VERSION
          - language: python
            version: "3.12"
            build-arg: PYTHON_VERSION
          - language: python
            version: "3.13"
            build-arg: PYTHON_VERSION
          - language: python
            version: "3.14"
            build-arg: PYTHON_VERSION
          - language: java
            version: "17"
            build-arg: JDK_VERSION
          - language: java
            version: "21"
            build-arg: JDK_VERSION
          - language: go
            version: "1.25"
            build-arg: GO_VERSION
          - language: go
            version: "1.26"
            build-arg: GO_VERSION
          - language: rust
            version: "1.92"
            build-arg: RUST_VERSION
          - language: rust
            version: "1.93"
            build-arg: RUST_VERSION

    env:
      IMAGE: "ghcr.io/wphillipmoore/dev-${{ matrix.language }}:${{ matrix.version }}"
      CANDIDATE: "ghcr.io/wphillipmoore/dev-${{ matrix.language }}:${{ matrix.version }}-candidate"
      CACHE_TAG: "ghcr.io/wphillipmoore/dev-${{ matrix.language }}:cache-${{ matrix.version }}"

    steps:
      - name: Checkout code
        uses: actions/checkout@v6

      - name: Generate Dockerfile from template
        run: docker/generate.sh ${{ matrix.language }}

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.repository_owner }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push candidate
        uses: docker/build-push-action@v6
        with:
          context: "docker/${{ matrix.language }}"
          platforms: linux/amd64,linux/arm64
          build-args: "${{ matrix.build-arg }}=${{ matrix.version }}"
          tags: ${{ env.CANDIDATE }}
          cache-from: type=registry,ref=${{ env.CACHE_TAG }}
          cache-to: type=registry,ref=${{ env.CACHE_TAG }},mode=max
          push: true

      - name: Trivy scan (amd64)
        uses: wphillipmoore/standard-actions/actions/security/trivy@v1.4
        with:
          scan-type: image
          scan-ref: ${{ env.CANDIDATE }}
          exit-code: "1"
          sarif-category: "trivy-image-${{ matrix.language }}-${{ matrix.version }}-amd64"
          trivyignores: .trivyignore

      - name: Trivy scan (arm64)
        shell: bash
        env:
          TRIVY_IMAGE: aquasec/trivy:0.70.0
        run: |
          TRIVYIGNORE_ARGS=""
          if [ -f .trivyignore ]; then
            TRIVYIGNORE_ARGS="--ignorefile .trivyignore"
          fi
          docker run --rm \
            -v "$GITHUB_WORKSPACE:/workspace" \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -w /workspace \
            --entrypoint sh \
            "$TRIVY_IMAGE" \
            -c "
              set -e
              trivy image \
                --scanners vuln \
                --severity CRITICAL,HIGH \
                --platform linux/arm64 \
                --exit-code 0 \
                --format json \
                --output /tmp/trivy-raw.json \
                $TRIVYIGNORE_ARGS \
                \"${{ env.CANDIDATE }}\"
              trivy convert \
                --severity CRITICAL,HIGH \
                --format table \
                --exit-code 0 \
                /tmp/trivy-raw.json
              trivy convert \
                --severity CRITICAL,HIGH \
                --format sarif \
                --exit-code 1 \
                --output /workspace/trivy-arm64.sarif \
                /tmp/trivy-raw.json
            "

      - name: Upload SARIF (arm64)
        if: always()
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: trivy-arm64.sarif
          category: "trivy-image-${{ matrix.language }}-${{ matrix.version }}-arm64"

      - name: Get candidate digest
        id: digest
        run: |
          DIGEST=$(docker buildx imagetools inspect "$CANDIDATE" --format '{{.Manifest.Digest}}')
          echo "digest=$DIGEST" >> "$GITHUB_OUTPUT"

      - name: Attest build provenance
        uses: actions/attest-build-provenance@v4
        with:
          subject-name: "ghcr.io/wphillipmoore/dev-${{ matrix.language }}"
          subject-digest: ${{ steps.digest.outputs.digest }}

      - name: Promote to final tag
        run: |
          docker buildx imagetools create \
            --tag "$IMAGE" \
            "$CANDIDATE"

      - name: Verify digest preservation
        run: |
          FINAL_DIGEST=$(docker buildx imagetools inspect "$IMAGE" --format '{{.Manifest.Digest}}')
          if [ "$FINAL_DIGEST" != "${{ steps.digest.outputs.digest }}" ]; then
            echo "ERROR: Digest mismatch after promotion!" >&2
            echo "  Candidate: ${{ steps.digest.outputs.digest }}" >&2
            echo "  Final:     $FINAL_DIGEST" >&2
            exit 1
          fi

      - name: Delete candidate tag
        if: always()
        run: |
          gh api --method DELETE \
            "/user/packages/container/dev-${{ matrix.language }}/versions" \
            -q ".[] | select(.metadata.container.tags[] == \"${{ matrix.version }}-candidate\") | .id" \
            2>/dev/null | while read -r VERSION_ID; do
              gh api --method DELETE \
                "/user/packages/container/dev-${{ matrix.language }}/versions/${VERSION_ID}" \
                2>/dev/null || true
            done
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 2: Verify YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docker-publish.yml'))"
```

Expected: No output (valid YAML).

- [ ] **Step 3: Lint the workflow with actionlint**

```bash
actionlint .github/workflows/docker-publish.yml
```

Expected: No errors. Fix any issues flagged.

---

## Task 4: Rewrite CI Workflow — `publish-base` Job

**Files:**
- Modify: `.github/workflows/docker-publish.yml` (replace `publish-base` job)

- [ ] **Step 1: Replace the `publish-base` job**

Replace the `publish-base` job with:

```yaml
  publish-base:
    name: "publish: dev-base:latest"
    needs: [hadolint]
    runs-on: ubuntu-latest
    env:
      IMAGE: ghcr.io/wphillipmoore/dev-base:latest
      CANDIDATE: ghcr.io/wphillipmoore/dev-base:latest-candidate
      CACHE_TAG: ghcr.io/wphillipmoore/dev-base:cache-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v6

      - name: Generate Dockerfile from template
        run: docker/generate.sh base

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.repository_owner }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push candidate
        uses: docker/build-push-action@v6
        with:
          context: docker/base
          platforms: linux/amd64,linux/arm64
          tags: ${{ env.CANDIDATE }}
          cache-from: type=registry,ref=${{ env.CACHE_TAG }}
          cache-to: type=registry,ref=${{ env.CACHE_TAG }},mode=max
          push: true

      - name: Trivy scan (amd64)
        uses: wphillipmoore/standard-actions/actions/security/trivy@v1.4
        with:
          scan-type: image
          scan-ref: ${{ env.CANDIDATE }}
          exit-code: "1"
          sarif-category: trivy-image-base-amd64
          trivyignores: .trivyignore

      - name: Trivy scan (arm64)
        shell: bash
        env:
          TRIVY_IMAGE: aquasec/trivy:0.70.0
        run: |
          TRIVYIGNORE_ARGS=""
          if [ -f .trivyignore ]; then
            TRIVYIGNORE_ARGS="--ignorefile .trivyignore"
          fi
          docker run --rm \
            -v "$GITHUB_WORKSPACE:/workspace" \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -w /workspace \
            --entrypoint sh \
            "$TRIVY_IMAGE" \
            -c "
              set -e
              trivy image \
                --scanners vuln \
                --severity CRITICAL,HIGH \
                --platform linux/arm64 \
                --exit-code 0 \
                --format json \
                --output /tmp/trivy-raw.json \
                $TRIVYIGNORE_ARGS \
                \"${{ env.CANDIDATE }}\"
              trivy convert \
                --severity CRITICAL,HIGH \
                --format table \
                --exit-code 0 \
                /tmp/trivy-raw.json
              trivy convert \
                --severity CRITICAL,HIGH \
                --format sarif \
                --exit-code 1 \
                --output /workspace/trivy-arm64.sarif \
                /tmp/trivy-raw.json
            "

      - name: Upload SARIF (arm64)
        if: always()
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: trivy-arm64.sarif
          category: trivy-image-base-arm64

      - name: Get candidate digest
        id: digest
        run: |
          DIGEST=$(docker buildx imagetools inspect "$CANDIDATE" --format '{{.Manifest.Digest}}')
          echo "digest=$DIGEST" >> "$GITHUB_OUTPUT"

      - name: Attest build provenance
        uses: actions/attest-build-provenance@v4
        with:
          subject-name: ghcr.io/wphillipmoore/dev-base
          subject-digest: ${{ steps.digest.outputs.digest }}

      - name: Promote to final tag
        run: |
          docker buildx imagetools create \
            --tag "$IMAGE" \
            "$CANDIDATE"

      - name: Verify digest preservation
        run: |
          FINAL_DIGEST=$(docker buildx imagetools inspect "$IMAGE" --format '{{.Manifest.Digest}}')
          if [ "$FINAL_DIGEST" != "${{ steps.digest.outputs.digest }}" ]; then
            echo "ERROR: Digest mismatch after promotion!" >&2
            echo "  Candidate: ${{ steps.digest.outputs.digest }}" >&2
            echo "  Final:     $FINAL_DIGEST" >&2
            exit 1
          fi

      - name: Delete candidate tag
        if: always()
        run: |
          gh api --method DELETE \
            "/user/packages/container/dev-base/versions" \
            -q '.[] | select(.metadata.container.tags[] == "latest-candidate") | .id' \
            2>/dev/null | while read -r VERSION_ID; do
              gh api --method DELETE \
                "/user/packages/container/dev-base/versions/${VERSION_ID}" \
                2>/dev/null || true
            done
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 2: Verify YAML syntax and lint**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docker-publish.yml'))"
actionlint .github/workflows/docker-publish.yml
```

Expected: No errors from either command.

- [ ] **Step 3: Commit the workflow changes**

```bash
git add .github/workflows/docker-publish.yml
git commit -m "feat(ci): restructure docker-publish for multi-arch builds

Switch to docker/build-push-action with multi-platform support
(linux/amd64 + linux/arm64). Add QEMU setup for cross-platform
emulation on amd64 runners. Implement candidate-tag staging flow:
build → scan both platforms → attest → promote → verify → cleanup.
Use registry-based layer caching to mitigate build time increase.

Part of #111."
```

---

## Task 5: Validate Candidate Cleanup Logic

The candidate tag cleanup step uses the GitHub API to delete package versions. This logic is non-trivial and worth verifying against the actual API shape.

**Files:** None modified — verification only.

- [ ] **Step 1: Verify the GitHub Packages API for tag deletion**

The delete-candidate step needs to:
1. List package versions for the container
2. Find the version with the candidate tag
3. Delete that version

Check the actual API response shape:

```bash
gh api "/user/packages/container/dev-python/versions" --jq '.[0] | keys'
```

This confirms whether `.metadata.container.tags` is the correct path. If the API structure differs, update the cleanup step accordingly.

- [ ] **Step 2: Update cleanup step if API shape differs**

If Step 1 reveals the API uses a different path (e.g., separate list then delete calls, or a different query structure), update both cleanup steps in the workflow to match the actual API.

The pattern that typically works for GHCR package version deletion:

```bash
# List versions, find by tag, delete
VERSION_ID=$(gh api "/user/packages/container/dev-python/versions" \
  --jq '.[] | select(.metadata.container.tags[] == "3.14-candidate") | .id')
gh api --method DELETE "/user/packages/container/dev-python/versions/${VERSION_ID}"
```

- [ ] **Step 3: Commit if changes were needed**

```bash
git add .github/workflows/docker-publish.yml
git commit -m "fix(ci): correct candidate cleanup API call

Update the delete-candidate-tag step to match the actual GitHub
Packages API response structure.

Part of #111."
```

Skip this commit if no changes were needed.

---

## Task 6: End-to-End Local Validation

**Files:** None modified — testing only.

- [ ] **Step 1: Test multi-arch build locally with buildx**

Confirm the Dockerfile works for both platforms by building with buildx:

```bash
docker buildx create --use --name multiarch-test 2>/dev/null || docker buildx use multiarch-test
docker/generate.sh python
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --build-arg PYTHON_VERSION=3.14 \
  docker/python/
```

Expected: Build completes for both platforms. The `--load` flag cannot be used with multi-platform (images go to buildx cache only), so no local image is created — but both builds completing confirms the Dockerfile is valid for both architectures.

- [ ] **Step 2: Build and test arm64 image specifically**

```bash
docker buildx build \
  --platform linux/arm64 \
  --build-arg PYTHON_VERSION=3.14 \
  --load \
  -t test-arm64:python \
  docker/python/
docker run --rm test-arm64:python shellcheck --version
docker run --rm test-arm64:python shfmt --version
docker run --rm test-arm64:python actionlint --version
docker run --rm test-arm64:python git-cliff --version
docker run --rm test-arm64:python hadolint --version
```

Expected: All 5 tools report their versions. On Apple Silicon, this runs natively. On Intel, this runs under QEMU emulation.

- [ ] **Step 3: Build and test amd64 image specifically**

```bash
docker buildx build \
  --platform linux/amd64 \
  --build-arg PYTHON_VERSION=3.14 \
  --load \
  -t test-amd64:python \
  docker/python/
docker run --rm test-amd64:python shellcheck --version
docker run --rm test-amd64:python shfmt --version
docker run --rm test-amd64:python actionlint --version
docker run --rm test-amd64:python git-cliff --version
docker run --rm test-amd64:python hadolint --version
```

Expected: All 5 tools report their versions. On Apple Silicon, this runs under Rosetta/QEMU. On Intel, this runs natively.

- [ ] **Step 4: Test the base image multi-arch build**

```bash
docker/generate.sh base
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  docker/base/
```

Expected: Builds for both platforms. The semgrep compilation step (which uses `build-essential`) completes on arm64 — this is the prerequisite validated in Task 1 Step 2.

- [ ] **Step 5: Clean up buildx builder**

```bash
docker buildx rm multiarch-test 2>/dev/null || true
```

---

## Task 7: Verify Existing CI Validation Still Passes

**Files:** None modified — validation only.

- [ ] **Step 1: Run generate + hadolint for all images**

```bash
docker/generate.sh
hadolint docker/*/Dockerfile
```

Expected: All Dockerfiles pass linting. The consolidated RUN layer in `validation-tools.dockerfile` should not trigger any new hadolint warnings.

- [ ] **Step 2: Run shellcheck on build scripts**

```bash
shellcheck docker/build.sh docker/generate.sh
```

Expected: No errors. These files are unchanged, but confirm nothing was accidentally broken.

- [ ] **Step 3: Run actionlint on the workflow**

```bash
actionlint .github/workflows/docker-publish.yml
```

Expected: No errors. This is the final actionlint pass after all workflow changes.

- [ ] **Step 4: Run markdownlint**

```bash
markdownlint .
```

Expected: No errors (no markdown files were modified, but confirm clean slate).

---

## Task 8: Final Commit and PR Preparation

**Files:** None modified — git operations only.

- [ ] **Step 1: Review all changes**

```bash
git log --oneline develop..HEAD
git diff develop --stat
```

Expected: 2 commits (one for the Dockerfile, one for the workflow — possibly a third if the cleanup API needed fixing). Only 2 files changed: `docker/common/validation-tools.dockerfile` and `.github/workflows/docker-publish.yml`.

- [ ] **Step 2: Push branch and create PR**

```bash
git push -u origin feature/111-multi-arch-images
```

Create the PR with:
- Title: `feat(images): publish multi-arch (amd64 + arm64) dev container images`
- Body referencing issue #111 with `Closes #111`
- Summary of what changed: Dockerfile arch-aware case block + workflow restructure for multi-platform builds
- Test plan: the local buildx validation from Task 6

---

## Notes for the Implementing Agent

1. **The `hadolint` job in CI is unchanged.** It runs on an amd64 runner and downloads the x86_64 hadolint binary directly (not via the Dockerfile). This is correct — the linting job doesn't need multi-arch support.

2. **`docker/build.sh` is unchanged.** Local builds use `docker build` (not buildx) and build for the host's native architecture only. This is by design for fast local iteration.

3. **The `CANDIDATE` tag changes semantics.** In the current workflow, `CANDIDATE` is a local-only Docker tag that never touches the registry. In the new workflow, `CANDIDATE` is pushed to GHCR (needed because multi-platform images can't be `--load`ed locally). The cleanup step deletes it after promotion.

4. **Trivy scanning changes.** Previously Trivy scanned a local image. Now it scans a registry image (the candidate). The amd64 scan uses the standard-actions composite (which defaults to the runner's native platform). The arm64 scan calls Trivy directly because the composite action (`wphillipmoore/standard-actions/actions/security/trivy@v1.4`) has no `platform` input — the direct invocation passes `--platform linux/arm64` to `trivy image`. Both scans upload SARIF with distinct categories.

5. **The candidate cleanup step is best-effort.** If it fails (permissions, API changes, race conditions), the workflow still succeeds — the `if: always()` means it runs regardless, but its failure is non-fatal because it's the last step. A stale candidate tag is equivalent to the final tag (if promotion succeeded) or a failed-scan image (if promotion didn't happen).
