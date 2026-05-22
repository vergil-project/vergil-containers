# Multi-Architecture Images

All dev container images are published as multi-architecture manifests
supporting **linux/amd64** and **linux/arm64**. This page documents the
design rationale and key trade-offs behind the multi-arch build pipeline.

**Implemented:** May 2026 | **Issue:** [#111](https://github.com/vergil-project/vergil-docker/issues/111)

## Problem

Images were originally published as linux/amd64 only. On Apple Silicon
Macs, Docker ran them under Rosetta/QEMU emulation — functional but
slow, with a warning on every invocation. Since all Vergil contributors
use Apple Silicon hardware, every CI run and local dev session paid the
emulation tax.

## Key Decisions

### Architecture mapping via TARGETARCH case block

Binary tool downloads in `validation-tools.dockerfile` use a single
`TARGETARCH`-driven case block that maps to each tool's platform naming
convention. All five binary tools (shellcheck, shfmt, actionlint,
git-cliff, hadolint) are consolidated into one `RUN` layer.

An unsupported `TARGETARCH` value triggers an explicit build failure
rather than a silent fallback.

**Why not individual download steps?** A single case block avoids
repeating the architecture-mapping logic five times and keeps the
layer count down.

### QEMU emulation in CI

CI builds both platforms on amd64 GitHub Actions runners using QEMU
via `docker/setup-qemu-action`. Native arm64 runners were not available
(or cost-effective) at the time of implementation.

**Trade-off:** arm64 layers build under emulation, which is slower than
native. This is acceptable because registry caching (`mode=max`) means
subsequent builds only rebuild changed layers, and the emulation cost
is paid in CI rather than by every developer.

### Staging-tag scan flow

The pipeline builds a candidate tag, scans both platforms independently
with Trivy, attests build provenance, then promotes the candidate to
the final consumer-facing tag. Unvetted images never appear at the live
tag.

**Why scan both platforms?** arm64 layers can differ from amd64 (different
base image layers, different binary dependencies). A vulnerability
present only in the arm64 layer set would be missed by a single-platform
scan.

### Registry caching over GitHub Actions cache

Layer caching uses `type=registry` (stored as a cache manifest in GHCR)
rather than the GitHub Actions cache.

**Why?** The GHA cache has a 10 GB limit shared across all workflows in
the repository. Multi-arch images with multiple language variants would
exhaust this quickly. Registry cache has no size limit and persists
across workflow runs.

Cache tags follow the pattern `{prefix}-{language}:cache-{version}`.
When a language version is retired from the matrix, its cache tag
remains in GHCR — storage impact is negligible but tags accumulate.
Periodic cleanup is tracked in [#125](https://github.com/vergil-project/vergil-docker/issues/125).

### Attestation before promotion

Build provenance attestation (SLSA) is applied to the candidate
manifest digest *before* promotion to the final tag. The digest is
preserved through `docker buildx imagetools create`, so the attestation
remains valid on the final tag.

**Why not attest after promotion?** Attesting on the candidate closes
the race window where the final tag exists without attestation. If
promotion fails, the candidate is attested but not consumer-visible —
a safe state.

### No candidate tag cleanup

Early designs included an `if: always()` step to delete the candidate
tag after promotion. This was removed because:

- On success, the candidate is identical to the promoted final tag and
  will be overwritten on the next build.
- On failure, the candidate serves as a debugging artifact.
- The `gh api DELETE` call added complexity and occasionally failed,
  turning a successful build into a CI failure.

### Local builds stay single-platform

`docker/build.sh` builds for the host's native architecture only.
Multi-arch builds are slow (QEMU emulation) and unnecessary for local
iteration. The CI pipeline is the authority for multi-arch correctness.

## Failure Modes

| Failure | Effect |
|---------|--------|
| Trivy scan fails (either platform) | Job fails; final tag still points to last good build |
| Attestation fails | Job fails; candidate exists but is not promoted |
| Promotion fails | Job fails; candidate is attested but not consumer-visible |
| Digest mismatch after promotion | Job fails with error; requires manual investigation |

## Architecture Mapping Reference

| Tool | amd64 label | arm64 label |
|------|-------------|-------------|
| shellcheck | `x86_64` | `aarch64` |
| shfmt | `amd64` | `arm64` |
| actionlint | `amd64` | `arm64` |
| git-cliff | `x86_64-unknown-linux-gnu` | `aarch64-unknown-linux-gnu` |
| hadolint | `linux-x86_64` | `linux-arm64` |
