# Release Workflow and Image Naming

The repository uses a staged release process with separate dev and prod
image prefixes, a thin CI orchestration layer, and nightly rebuilds for
CVE freshness. This page documents the design rationale.

**Implemented:** May 2026 |
**Issues:** [#152](https://github.com/vergil-project/vergil-docker/issues/152),
[#139](https://github.com/vergil-project/vergil-docker/issues/139),
[#65](https://github.com/vergil-project/vergil-docker/issues/65)

## Problem

All images were published under the `dev-` prefix with mutable tags
that updated on every develop merge. There was no distinction between
staging and production images, no changelog generation, and no scheduled
rebuilds to catch upstream CVEs between merges.

## Image Naming Convention

| Prefix | Source branch | Built by | Purpose |
|--------|-------------|----------|---------|
| `dev-{lang}:{ver}` | develop | `cd.yml` (develop push) + `ops.yml` (nightly) | Staging and validation of image changes |
| `prod-{lang}:{ver}` | main | `cd.yml` (main push, after release) | Production use by all consumers |

All images use the `ghcr.io/vergil-project/` namespace, including
`dev-base`/`prod-base`.

`prod-` images are the default everywhere. `dev-` images are used
temporarily to validate changes to the images themselves, typically by
pointing a single consumer at `dev-` while debugging a broken workflow.

## Key Decisions

### Nightly rebuilds target dev-images only

The `ops.yml` workflow runs daily at 06:15 UTC and rebuilds all `dev-`
images. `prod-` images are built exclusively by the CD release workflow
on main merges.

**Why?** Nightly rebuilds ensure development images stay current with
upstream security patches (base image updates, apt package refreshes)
without waiting for a code change. `prod-` images intentionally lag —
they represent a known-good, released state. The nightly `dev-` rebuild
surfaces CVE issues early via GitHub Actions failure notifications; if
Trivy finds new vulnerabilities, the build fails and the team triages
(see [Trivy CVE Triage](../../operations/trivy-triage.md)).

### cd.yml as thin orchestration shim

`cd.yml` is a thin shim that calls three reusable workflows:

- **`cd-docs.yml`** — documentation deployment (all pushes)
- **`cd-release.yml`** — changelog, tag, version-bump PR (main push only)
- **`cd-docker-publish.yml`** — image build, scan, and publish

The docker-publish job depends on the release job:

```yaml
if: always() && (needs.release.result == 'success' || needs.release.result == 'skipped')
```

This ensures docker-publish runs after a successful release (main) or
when release is skipped (develop), but does **not** run if the release
job fails. The `image-prefix` input is derived from the branch:

```yaml
image-prefix: ${{ github.ref == 'refs/heads/main' && 'prod' || 'dev' }}
```

**Why a shim?** Keeping the orchestration logic in one file makes the
build flow readable at a glance. The reusable workflows contain the
complexity; `cd.yml` contains the policy (when to build what).

### Reusable publish workflow with image-prefix input

`cd-docker-publish.yml` is a `workflow_call` workflow that accepts a
single required input: `image-prefix` (either `dev` or `prod`). All
image names, candidate tags, cache tags, and attestation subjects are
parameterized by this input.

**Why reusable?** The same build, scan, attest, promote pipeline applies
to both `dev-` and `prod-` images. The only difference is the prefix
and when the workflow is triggered. Duplicating the pipeline would mean
maintaining two copies of the Trivy scanning, attestation, and
promotion logic.

### No custom failure notification

Nightly rebuild failures use built-in GitHub Actions email notifications.
No custom issue-creation, Slack integration, or auto-recovery is
implemented.

**Why?** The failure rate is low (typically new upstream CVEs that need
triage, not infrastructure issues), and the team monitors GitHub
notifications. Custom notification infrastructure would add complexity
without proportional value at current scale.

## Consumer Integration

Images are consumed via `vrg-docker-run` and `vrg-docker-test` in
[vergil-tooling](https://github.com/vergil-project/vergil-tooling).
The image prefix defaults to `prod-` and can be overridden per-repo
in `vergil.toml`:

```toml
[docker]
image-prefix = "dev"   # default: "prod"
```

This allows a single consuming repo to temporarily use `dev-` images
for validating in-progress image changes without affecting the rest of
the fleet.

## Migration Sequence

The original migration order was load-bearing — consumers could not
reference `prod-` images before they existed:

1. Land `cd-docker-publish.yml` and updated `cd.yml` on develop
2. Land `ops.yml` with nightly rebuild
3. Merge develop to main (first release creates `prod-` images)
4. Configure GHCR package access for each new `prod-` package
5. Update `vrg-docker-run` to default to `prod-` prefix
6. Fleet-wide sweep of all consuming repos to replace `dev-` references
