# Multi-Arch (ARM64) Dev Container Images

**Issue:** [#111](https://github.com/vergil-project/vergil-docker/issues/111)
**Date:** 2026-05-03
**Status:** Approved

## Problem

Dev container images are published as `linux/amd64` only. On Apple Silicon
Macs, Docker runs them under Rosetta/QEMU emulation — functional but slow,
with a warning on every invocation.

## Solution

Publish multi-arch images (`linux/amd64` + `linux/arm64`) so images run
natively on both Intel and Apple Silicon hosts.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Arch mapping in Dockerfile | Case block with helper variables | Scales to a 3rd platform with one added arm |
| CI build mechanism | `docker/build-push-action` | Declarative, built-in cache integration, handles multi-platform manifests |
| Cross-platform emulation | QEMU via `docker/setup-qemu-action` | Required for arm64 builds on amd64 GitHub runners |
| Security scanning | Staging tag → scan both platforms → promote | Unvetted images never appear at the live tag; arm64 layers scanned too |
| Attestation timing | Before promotion, on candidate digest | Closes race window where final tag exists without attestation; digest preserved through `imagetools create` re-tag |
| Layer caching | Registry cache (`type=registry`) | No 10 GB GHA cache limit; persistent across runs |
| Candidate cleanup | `if: always()` | Registry stays tidy regardless of scan outcome |
| Local `build.sh` | Unchanged (single-platform, native arch) | Fast local iteration; CI handles multi-arch |

## Scope

### Changed

1. **`docker/common/validation-tools.dockerfile`** — rewrite with
   `TARGETARCH`-driven case block for all 5 binary tools.
2. **`.github/workflows/docker-publish.yml`** — restructure to use buildx,
   `docker/build-push-action`, staging-tag scan flow, and registry caching.

### Unchanged

- `docker/generate.sh` — template expansion is architecture-agnostic.
- `docker/build.sh` — stays single-platform for local dev speed.
- `docker/common/github-cli.dockerfile` — already uses `dpkg --print-architecture`.
- `docker/common/node-markdownlint.dockerfile` — NodeSource apt handles multi-arch.
- `docker/common/python-support.dockerfile` — pip/uv packages are arch-independent.
- `docker/base/Dockerfile.template` — semgrep install via `uv tool install` uses
  source compilation with `build-essential`; **must be validated on arm64 before
  implementation** (see prerequisites below).
- Language-specific Dockerfile templates — base images are already multi-arch.
- Version matrix — unchanged.
- Image naming/GHCR paths — unchanged; consumers pull the same tags.
- `hadolint` lint job in CI — runs on ubuntu (amd64), keeps its x86_64 binary.

## Prerequisites

Before implementation, validate the following:

1. **Semgrep ARM64 compilation.** Run `uv tool install semgrep` in an
   `arm64` container (e.g., `docker run --platform linux/arm64 python:3.14-slim`)
   to confirm the native extension compiles. If it fails, the base image
   Dockerfile will need a conditional or alternative install path.

2. **Binary tool download URLs.** Verify the exact arm64 artifact names
   for all 5 tools against their GitHub release pages. The table below
   contains expected names — confirm each before coding the case block.

## Architecture Mapping

Buildx injects `TARGETARCH` (`amd64` or `arm64`) automatically. A case block
at the top of the validation-tools fragment maps to each tool's naming
convention:

| Tool | `amd64` label | `arm64` label |
|------|---------------|---------------|
| shellcheck | `x86_64` | `aarch64` |
| shfmt | `amd64` | `arm64` |
| actionlint | `amd64` | `arm64` |
| git-cliff | `x86_64-unknown-linux-gnu` | `aarch64-unknown-linux-gnu` |
| hadolint | `linux-x86_64` | `linux-arm64` |

> **Verified 2026-05-03** against each tool's GitHub release artifacts.

All 5 downloads are consolidated into a single `RUN` layer to avoid
repeating the case block. An unsupported `TARGETARCH` value triggers an
explicit error and build failure.

## CI Workflow Structure

### Per-matrix-entry job (`build-scan-push`)

```
1. Checkout
2. Generate Dockerfile from template
3. Set up QEMU                     (docker/setup-qemu-action)
4. Set up Docker Buildx            (docker/setup-buildx-action)
5. Log in to GHCR
6. Build and push candidate        (docker/build-push-action)
     platforms: linux/amd64,linux/arm64
     tags: ghcr.io/.../dev-{lang}:{version}-candidate
     cache-from: type=registry,ref=ghcr.io/.../dev-{lang}:cache-{version}
     cache-to:   type=registry,ref=ghcr.io/.../dev-{lang}:cache-{version},mode=max
     push: true
7. Trivy scan (amd64)              (scan registry candidate; default platform)
8. Trivy scan (arm64)              (scan registry candidate; --platform linux/arm64)
9. Attest build provenance         (on candidate manifest digest)
10. Promote to final tag           (docker buildx imagetools create --tag)
11. Verify digest preservation     (confirm final tag digest matches candidate)
12. Delete candidate tag           (if: always(); gh api DELETE)
```

### Tag conventions

- **Candidate:** `dev-{language}:{version}-candidate` — ephemeral, deleted
  after promotion.
- **Cache:** `dev-{language}:cache-{version}` — persistent registry cache
  for both platform layers.
- **Final:** `dev-{language}:{version}` — the consumer-facing tag, unchanged.

### `publish-base` job

Same flow with `dev-base:latest-candidate` → `dev-base:latest`.

## Failure Modes

| Failure | Effect |
|---------|--------|
| Trivy scan fails (either platform) | Job fails; candidate stays briefly (cleanup attempts deletion); final tag still points to last good build |
| Attestation fails | Job fails; candidate exists but is not promoted — final tag unchanged |
| Promote fails | Job fails; candidate is attested but not promoted; final tag unchanged |
| Digest mismatch after promotion | Job fails with error; attestation was on candidate digest which no longer matches final — investigate manually |
| Cleanup fails | Non-fatal; candidate is identical to promoted final if promotion succeeded, or a failed scan image that will be overwritten next run |

## Storage and Build Time Impact

- GHCR storage roughly doubles (two platform layers per image).
- Build time increases for each platform but is mitigated by registry
  caching (`mode=max` caches all intermediate layers).
- First build after enabling multi-arch will be slow (cold cache); subsequent
  builds benefit from cached layers for both platforms.

## Known Limitations

- **Stale cache tags.** When a language version is retired from the matrix,
  its `cache-{version}` tag remains in GHCR. Storage impact is negligible but
  tags accumulate over time. Tracked in issue #125 for a periodic audit.
