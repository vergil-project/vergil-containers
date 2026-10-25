# Trivy Scanning

This repository runs Trivy in two different places, and they scan two
different things. Pull requests get a **filesystem scan** of the source tree.
Publishing gets an **image scan** of every built image on both platforms.
Each scan uploads SARIF to GitHub code scanning under its own category. The
two sets of categories never meet on the same branch, so every pull request
shows a "configurations not found" warning. That warning is expected and
harmless.

For triaging a publish that Trivy blocked, see
[Trivy CVE Triage](../operations/trivy-triage.md).

## What runs where

| Context | Workflow | Scan | What it scans | SARIF category |
|---------|----------|------|---------------|----------------|
| Pull request | `ci.yml` → `ci-security.yml` (vergil-actions), job `security / trivy` | `trivy fs` | The checked-out source tree | `trivy-fs` |
| Push to `develop` | `cd.yml` → `cd-docker-publish.yml` (`image-prefix: dev`) | `trivy image` | Each `dev-*` candidate image, amd64 and arm64 | `trivy-image-<language>-<version>-<arch>` and `trivy-image-base-<arch>` |
| Push to `main` | `cd.yml` → release, then `cd-docker-publish.yml` (`image-prefix: prod`) | `trivy image` | Each `prod-*` candidate image, amd64 and arm64 | same as above |
| Nightly (`ops.yml`) | `nightly-rebuild-dev` and `nightly-rebuild-prod` → `cd-docker-publish.yml` (`no-cache: true`) | `trivy image` | Fresh rebuilds of every `dev-*` and `prod-*` image | same as above |

### Pull requests: the filesystem scan

`ci.yml` calls the shared `ci-security.yml` reusable workflow from
`vergil-project/vergil-actions`. Its `trivy` job runs the shared
`actions/shared/security/trivy` action with `scan-type: fs`. That action
scans the source tree for vulnerable dependencies, reporting `CRITICAL` and
`HIGH` findings. With no `sarif-category` given, it uploads under the
default category `trivy-fs`. It also keeps the full, unfiltered SARIF as the
`ci-evidence-security-part-trivy` artifact, which feeds the
`security / evidence` gate.

This scan only checks the files in the repository. No image has been built
at this point, so the pull request cannot scan any image.

### Publishing: the image scans

`cd-docker-publish.yml` builds every image in `docker/versions/matrix.json`,
plus `base`, and pushes each one as a `-candidate` tag. It then scans each
candidate once per platform:

- **amd64** goes through the shared `trivy` action with `scan-type: image`
  and `sarif-category: trivy-image-<language>-<version>-amd64`.
- **arm64** runs Trivy directly in a pinned `aquasec/trivy` container with
  `--platform linux/arm64`. Its SARIF is uploaded under
  `trivy-image-<language>-<version>-arm64`.

`base` uses `trivy-image-base-amd64` and `trivy-image-base-arm64`.

Each scan step uses `continue-on-error`, so both platforms always get
scanned. A later "Fail if vulnerabilities found" step then fails the job if
either scan found an unsuppressed `CRITICAL` or `HIGH` vulnerability. A
failed job never promotes its candidate to the final tag. Both image scans
run from the repository root, so `trivy.yaml` (with `ignore-unfixed` and the
`linux-libc-dev` ignore policy) and `.trivyignore` apply to both of them.

The publish workflow does not run on pull requests. `ci.yml` does not call
it, and `cd.yml` runs only on pushes to `develop` and `main`. So the
`trivy-image-*` categories only ever appear on the long-lived branches.

## The "configurations not found" warning

GitHub code scanning finds "new alerts" on a pull request by comparing each
SARIF category on the PR branch with the same category on the base branch.
`develop` holds analyses for every `trivy-image-*` category, uploaded by the
publish and nightly runs. A PR branch only ever gets `trivy-fs`. GitHub sees
that all of those image categories are missing from the PR and posts a
warning on the PR's **Trivy** code-scanning check:

> **Warning**: Code scanning cannot determine the alerts introduced by this
> pull request, because N configurations present on `refs/heads/develop`
> were not found

**This is expected and harmless.** The images do not exist until after the
merge, so a PR cannot produce those categories. The `trivy-fs` comparison
still works normally, and the image scans still gate every publish. The
**Trivy** code-scanning check finishes as *neutral* (`vrg-gh pr checks`
shows it as "skipping"), which does not block a merge. The scan's actual
result is the `security / trivy` job, which feeds `security / evidence`.

The warning still appears today. On PR #694 (October 2026) it listed 42
missing configurations: amd64 and arm64 categories for `base` and for every
current matrix image, plus some stale ones (see below).

### Stale categories from retired versions

A code-scanning category stays on `develop` until someone deletes it. When a
language version, or a whole language, leaves the matrix, nothing uploads
new results under its categories. Its last analysis stays on the branch, so
it keeps showing up in the warning. The PR #694 list still included
`trivy-image-ruby-3.2/3.3/3.4-*` (Ruby images are retired),
`trivy-image-go-1.25-*` and `trivy-image-cpp-gcc-13-*`.

These leftovers do no harm beyond making the list longer. To remove them,
delete the stale analyses from the repository's code scanning (the GitHub
REST API endpoint `DELETE /repos/{owner}/{repo}/code-scanning/analyses/{analysis_id}`).
This needs a token with `security_events` write access, so a maintainer has
to do it.

### Categories are shared between `dev` and `prod`

The image categories leave out the image prefix. So the `dev-python:3.14`
scan and the `prod-python:3.14` scan both upload under
`trivy-image-python-3.14-<arch>`. The SARIF upload records each result
against the ref of the workflow run that uploaded it. A scheduled run
always runs on the default branch (`develop`). That means the
`nightly-rebuild-prod` results are filed under `refs/heads/develop`, even
though they come from a `main` checkout. Within a ref, the most recent
upload for a category replaces the one before it. For any category, the
code-scanning view on `develop` shows whichever image was scanned last,
`dev` or `prod`. This affects only what the code-scanning UI shows. The
publish gate is decided separately for every image, in the job that builds
it.
