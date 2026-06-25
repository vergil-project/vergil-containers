# Architecture

## Build Strategy

All images are built from Dockerfile templates using a two-stage process:

1. `generate.sh` expands `Dockerfile.template` files by replacing
   `# @include` directives with the contents of shared fragments from
   `docker/common/`.
2. `build.sh` calls `generate.sh` then runs `docker build` for every
   language and version combination.

```text
docker/
├── build.sh                    # Builds all images
├── generate.sh                 # Expands templates into Dockerfiles
├── common/
│   ├── github-cli.dockerfile
│   ├── node-markdownlint.dockerfile
│   ├── path-defaults.dockerfile
│   ├── python-support.dockerfile
│   ├── security-tools.dockerfile
│   └── validation-tools.dockerfile
├── base/Dockerfile.template
├── python/Dockerfile.template
├── ruby/Dockerfile.template
├── go/Dockerfile.template
├── java/Dockerfile.template
└── rust/Dockerfile.template
```

### Templating

Each `Dockerfile.template` contains standard Dockerfile instructions plus
`# @include common/<fragment>.dockerfile` directives. `generate.sh`
replaces each directive with the full contents of the referenced fragment,
producing a final `Dockerfile` in the same directory.

This eliminates duplication — shared tool installations (GitHub CLI,
Node.js, markdownlint, validation tools) are maintained once in
`docker/common/` and included by every template that needs them.

### Version management

All shared tool versions are pinned via `ARG` directives in the common
fragments. A version bump is a one-line change in one file, applied to
all images automatically at build time.

## Common Tooling Layer

Every language image includes the following shared fragments:

- **`path-defaults.dockerfile`** — Sets PATH for `uv tool install`
  entry points across GitHub Actions and local contexts.
- **`node-markdownlint.dockerfile`** — Node.js via NodeSource apt repo
  and markdownlint-cli via npm.
- **`github-cli.dockerfile`** — GitHub CLI via the official apt repo.
- **`validation-tools.dockerfile`** — Architecture-aware binary
  installs of shellcheck, shfmt, actionlint, git-cliff, and hadolint.
  Uses `TARGETARCH` (injected by Docker Buildx) to select the correct
  binary for amd64 or arm64.
- **`security-tools.dockerfile`** — Security analysis tools installed
  from binary releases. Currently includes scorecard (OpenSSF).
- **`python-support.dockerfile`** — Minimal Python plus yamllint and
  uv, used by non-Python images.

Python-based images (`dev-python`, `dev-base`) install yamllint and uv
directly via pip rather than the `python-support` fragment.

The `dev-base` image includes all common fragments plus documentation
tooling (MkDocs Material, mike, semgrep). It is the fallback image for
repos with no detected language.

## Design Principles

**Thin images** — Each image provides the language runtime, package
manager, and common tooling layer. Project-specific dependencies (from
lockfiles like `Gemfile.lock`, `uv.lock`, `go.sum`) are installed at
container startup by the consuming repository's test script.

**No repo-specific logic** — Images are general-purpose dev containers.
Any repository using the supported language can use them.

**No duplication** — Shared tooling is maintained in common fragments.
Adding a tool to all images means editing one fragment file.

## Multi-Architecture Support

All images are published as multi-architecture manifests supporting
**amd64** and **arm64**. Binary tool downloads in `validation-tools.dockerfile`
use `TARGETARCH` (injected by Docker Buildx) to select the correct
platform artifact.

Local builds via `docker/build.sh` build for the host's native
architecture only (for speed). The CI pipeline builds both platforms
using QEMU emulation on the GitHub Actions runner.

## Download Integrity

Binary tools installed from GitHub releases are verified against
checksums published by the upstream project. Each verified download
follows a three-step pattern: download the artifact to a temporary
location, verify it against the upstream checksums file, then
extract and install. The build fails immediately if a checksum does
not match.

| Tool | Verification | Algorithm |
| --- | --- | --- |
| actionlint | Consolidated checksums file | SHA-256 |
| git-cliff | Per-artifact sidecar file | SHA-512 |
| hadolint | Per-artifact sidecar file | SHA-256 |
| scorecard | Consolidated checksums file | SHA-256 |
| shellcheck | None (upstream does not publish checksums) | — |
| shfmt | None (upstream does not publish checksums) | — |

This protects against corrupted downloads, CDN integrity failures,
and partial compromise of release artifacts. It does not protect
against an attacker who compromises both the artifact and its
checksums file simultaneously — that threat is addressed at a
different layer (SLSA build provenance attestation on the published
images).

Tools whose upstream projects do not publish checksums are installed
without verification. If a project begins publishing checksums in the
future, verification will be added at that time.

## Publishing

Images are published as multi-arch manifests to GitHub Container Registry
via the reusable `cd-docker-publish.yml` workflow, parameterized by an
`image-prefix` input that determines the naming convention:

- **`dev-` images** (`ghcr.io/vergil-project/dev-{language}:{version}`) —
  built on every push to `develop` and rebuilt nightly via `ops.yml` to
  pick up base-image security patches.
- **`prod-` images** (`ghcr.io/vergil-project/prod-{language}:{version}`) —
  built on push to `main`, after the release workflow generates a
  changelog, git tag, and GitHub release.

The publish pipeline for each prefix:

1. Builds a candidate tag for both platforms (amd64 + arm64)
2. Scans each platform independently with Trivy (SARIF upload)
3. Attests build provenance (SLSA via GitHub attestations)
4. Promotes the candidate to the final tag via `docker buildx imagetools create`
5. Verifies digest preservation between candidate and final

### Image namespace

Image URLs use the **user namespace** (`ghcr.io/vergil-project/...`), not
a repo-specific namespace. This means image paths are stable across
repository migrations — they do not change when the publishing repository
changes.

Image naming: `ghcr.io/vergil-project/{prefix}-{language}:{version}` where
`{prefix}` is `dev` or `prod`.

### Release workflow

Pushes to `main` trigger the `cd-release.yml` reusable workflow, which
generates a changelog (via git-cliff), creates a git tag and GitHub
release, and opens a version-bump PR back to `develop`. The docker
publish job runs after the release completes.

### Nightly rebuilds

The `ops.yml` workflow runs daily at 06:15 UTC and rebuilds all `dev-`
images. This ensures development images stay current with upstream
security patches without waiting for a code change to trigger a build.

### Authentication

The workflow authenticates with `GITHUB_TOKEN` using `packages: write`
permission. No personal access token or additional secret is needed.

### GHCR package access grants

Each `dev-*` and `prod-*` package on GHCR must explicitly grant this
repository write access. The packages were originally created by the
`vergil-tooling` repository, so that repo has implicit write access.
This repo does not, unless manually configured.

Per-package setup (one-time, for each of `dev-base`, `dev-python`,
`dev-java`, `dev-go`, `dev-ruby`, `dev-rust`, and the corresponding
`prod-` packages):

1. Navigate to the package settings page on GHCR.
2. Under **Manage Actions access**, click **Add Repository**.
3. Select `vergil-containers`.
4. Set role to **Write**.

## Consumption

Images are consumed via `vrg-docker-run` and `vrg-docker-test` in
[vergil-tooling](https://github.com/vergil-project/vergil-tooling).
`vrg-docker-run` runs arbitrary commands inside the matching container;
`vrg-docker-test` auto-detects the project language and runs the test
suite. Consuming repos can override the image with the `DOCKER_DEV_IMAGE`
environment variable.
