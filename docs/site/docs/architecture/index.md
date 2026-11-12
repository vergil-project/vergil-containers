# Architecture

## Build Strategy

All images are built from Dockerfile templates using a two-stage process:

1. `generate.sh` expands `Dockerfile.template` files by replacing
   `# @include` directives with the contents of shared fragments from
   `docker/common/`.
2. `build.sh` calls `generate.sh` then runs `docker build` for every
   entry of the publish matrix, `docker/versions/matrix.json`, in the
   publish's tier order, so a parent image is built before the images built
   `FROM` it (see [Publishing](#publishing)). `build.sh <family>` builds one
   family and its parents (`--pull-parents` pulls them instead). The matrix,
   like the Dockerfile `ARG` defaults, is generated from
   `docker/versions/manifest.yml` by `docker/versions/generate.py` (see
   [Language version lifecycle](../languages/lifecycle.md)).

```text
docker/
├── build.sh                    # Builds all images
├── generate.sh                 # Expands templates into Dockerfiles
├── common/                     # Shared fragments (<name>.dockerfile)
├── pkg-ubuntu/Dockerfile.template
├── pkg-rhel/Dockerfile.template
├── base/Dockerfile.template
├── python/Dockerfile.template
├── go/Dockerfile.template
├── rust/Dockerfile.template
├── cpp-clang/Dockerfile.template
├── cpp-gcc/Dockerfile.template
├── ts-node/Dockerfile.template
└── versions/
    ├── manifest.yml            # The single source of language versions
    ├── generate.py             # Writes every derived version list
    ├── matrix.json             # The generated publish matrix (CD and nightly)
    ├── includes.py             # Each image's input files, for PR selection
    ├── selection.py            # The images a pull request's change reaches
    ├── pr_jobs.py              # Groups the selected images into PR build jobs
    └── lifecycle/              # The nightly lifecycle check and adapters
```

### Templating

Each `Dockerfile.template` contains standard Dockerfile instructions plus
`# @include common/<fragment>.dockerfile` directives. `generate.sh`
replaces each directive with the full contents of the referenced fragment,
producing a final `Dockerfile` in the same directory. Includes may nest: a
fragment may include another fragment, and `generate.sh` caps the depth so
that an include cycle is an error.

This eliminates duplication — shared tool installations (GitHub CLI,
markdownlint, validation tools) are maintained once in `docker/common/`.
Since epic vergil-project/.github#649 the shared tool fragments are included
by `base` alone, and every language image gets them by being built `FROM` it.
The package toolchain images and some language images include fragments of
their own, as [Common Tooling Layer](#common-tooling-layer) lists.

### Version management

Most tools are unpinned and resolve their latest release at build time.
Each tool held at a version carries a justification in
`docker/pins/pins.yml`, and the binary-download tools among them are bumped
to the leading edge by the daily `upstream-refresh` job. See
[Tool Version Management](../operations/version-management.md) for the
pinning model.

## Common Tooling Layer

`dev-base` includes the following shared fragments, and every language image
carries them because it is built `FROM` `dev-base`:

- **`path-defaults.dockerfile`** — Sets PATH for `uv tool install`
  entry points across GitHub Actions and local contexts.
- **`github-cli.dockerfile`** — GitHub CLI via the official apt repo.
- **`validation-tools.dockerfile`** — Architecture-aware binary
  installs of shellcheck, shfmt, actionlint, git-cliff, and hadolint.
  Uses `TARGETARCH` (injected by Docker Buildx) to select the correct
  binary for amd64 or arm64.
- **`security-tools.dockerfile`** — Security analysis tools installed
  from binary releases: scorecard (OpenSSF) and trivy.
- **`rpm.dockerfile`** — The distro's `rpm`, the peer of `dpkg`, for
  inspecting `.rpm` packages and comparing versions (`rpm.vercmp`).
- **`pandoc.dockerfile`** — pandoc for Markdown to `.docx`/HTML
  conversion (no TeX; PDF output is opt-in).

uv and nFPM (`uv.dockerfile`, `nfpm.dockerfile`) are included by the package
toolchain images, and `dev-base` takes them from its parent.

A language image adds only its family's own toolchain. `dev-python`,
`dev-go` and `dev-rust` include no fragment. The two C++ families include
`cpp-analysis.dockerfile`, and `dev-ts-node` includes
`typescript-analysis.dockerfile`. `dev-python` adds the family Python, a
pinned python-build-standalone build at `/opt/python/<version>`, and
`dev-ts-node` adds the family Node, a pinned nodejs.org tarball at
`/opt/node/<major>`.

The `dev-base` image is built `FROM` the package toolchain image
`pkg-ubuntu:24.04` (epic vergil-project/.github#649), from which it takes uv
and nFPM. It includes the common fragments plus documentation tooling (MkDocs
Material, mike, semgrep) and OpenTofu (`opentofu.dockerfile`) for in-sandbox
`tofu fmt -check` / `tofu validate` of OpenTofu modules. It is the fallback
image for repos with no detected language. Its own tools run on core runtimes
installed side by side under `/opt/vergil/`, from four fragments only it
includes:

- **`vergil-apt.dockerfile`** — The vergil apt repository, set up only after
  the signing key's primary fingerprint matches the pinned one.
- **`core-python.dockerfile`** — The core Python, `vergil-python<core>` at
  `/opt/vergil/python/<core>/`; `/usr/local/bin/python3` links to it and
  promises the standard library only.
- **`core-node.dockerfile`** — The core Node, the pinned nodejs.org tarball
  at `/opt/vergil/node/<core-major>/`, and markdownlint-cli on it. No
  `node`, `npm` or `npx` is on `PATH`; `markdownlint` is a wrapper that
  runs the core Node by path.
- **`core-tools.dockerfile`** — yamllint, ansible-lint, semgrep and MkDocs
  (with mkdocs-material and mike) as uv tools on the core Python.
  `semgrep` and `pysemgrep` are wrappers that lower the stack hard limit
  before running the tool, so that `semgrep-core` does not crash on Python
  3.15 ([vergil-containers#825](https://github.com/vergil-project/vergil-containers/issues/825));
  they go once semgrep fixes its stack-limit code upstream
  ([vergil-containers#826](https://github.com/vergil-project/vergil-containers/issues/826)).

The core series come from the manifest's `core:` section. Nothing in
`dev-base` is pip-installed. Its last build step runs
`docker/base/checks.sh`: the checks every image built on it keeps
(`checks-invariants.sh`) and its defaults (`checks-defaults.sh`), both left
in the image at `/usr/local/lib/vergil/checks/` for its children to rerun.

## Design Principles

**Thin images** — Each image provides the language runtime, package
manager, and common tooling layer. Project-specific dependencies (from
lockfiles like `Gemfile.lock`, `uv.lock`, `go.sum`) are installed at
container startup by the consuming repository's test script.

**No repo-specific logic** — Images are general-purpose dev containers.
Any repository using the supported language can use them.

**No duplication** — Shared tooling is maintained in common fragments.
Adding a tool to all images means editing one fragment file.

**No host requirements** — A single OCI container runtime is the only
prerequisite for local development (nerdctl/Lima preferred, Docker
supported).

## Multi-Architecture Support

All images are published as multi-architecture manifests supporting
**amd64** and **arm64**. Binary tool downloads in `validation-tools.dockerfile`
use `TARGETARCH` (injected by Docker Buildx) to select the correct
platform artifact.

Local builds via `docker/build.sh` build for the host's native
architecture only (for speed). The CI pipeline builds each platform
natively, amd64 on `ubuntu-24.04` and arm64 on `ubuntu-24.04-arm`, and
stitches the two into one multi-arch manifest. Nothing is emulated.

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
  changelog, git tag, and GitHub release, and rebuilt nightly from `main`
  via `ops.yml`.

The publish pipeline for each image of `docker/versions/matrix.json`
(`base` included):

1. Builds each platform on its own native runner, amd64 on `ubuntu-24.04`
   and arm64 on `ubuntu-24.04-arm`, and pushes each build by digest,
   untagged. A failed push is retried, up to three attempts in all, after a
   jittered back-off; GHCR sporadically refuses these pushes with
   `denied: permission_denied: write_package`.
2. Stitches the two digests into a multi-arch candidate tag with
   `docker buildx imagetools create`
3. Scans each platform independently with Trivy (SARIF upload; see
   [Trivy Scanning](trivy-scanning.md))
4. Attests build provenance (SLSA via GitHub attestations)
5. Promotes the candidate to the final tag via `docker buildx imagetools create`
6. Verifies digest preservation between candidate and final

Steps 2 to 6 run in one `publish` job per image, once its tier's `build`
jobs (below) have finished. An image whose build failed on either platform is not stitched or
promoted, and its previous tags stay published.

The pipeline runs in **tiers**. An image may be built `FROM` another image of
this repository, its *parent*, named by a `parent:` entry in
`docker/versions/manifest.yml`. Each image's depth in that tree (0 for an
image on an upstream base, at most 2) is its tier. Every tier-0 image runs the
steps above, then the tier-1 images run them, built `FROM` their parent's
promoted digest from the same run, and then tier 2. An image whose parent
failed fails its own build with an error naming the parent, and its previous
tags stay published. Today `base` is the one tier-1 image, built on
`pkg-ubuntu:24.04`, and no image is in tier 2.

Each image's `--build-arg`s come from its `build-args` map in the generated
`docker/versions/matrix.json` (a family's or toolchain's version argument
and its toolchain pins; for `base`, its core runtimes), and a child also gets
`PARENT_IMAGE`, its parent by digest.

Images that are not languages, such as the package toolchain images, are
listed in the manifest's `toolchains:` section. They are built, published and
cleaned up like the language images, and any entry may name one as its
parent, but they never appear in `window.json` or the version lifecycle.

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
release, and opens a version-bump PR back to `develop`. The release job
also collects the CI-evidence bundle and runs an enforcing completeness
gate: it hard-fails on incomplete or failed evidence, which blocks the
downstream docker-publish job. The docker publish job runs after the
release completes.

### Nightly rebuilds

The `ops.yml` workflow runs every morning (UTC; the `schedule` trigger in
`.github/workflows/ops.yml` holds the exact time) and rebuilds every image
with the registry cache disabled (`no-cache: true`):

- `nightly-rebuild-dev` rebuilds all `dev-` images from `develop`.
- `nightly-rebuild-prod` rebuilds all `prod-` images from `main`, so they
  pick up upstream fixes without moving past the released source. It calls
  `main`'s copy of `cd-docker-publish.yml` (`@main`), not `develop`'s, so the
  publish steps and the files they run (such as `scripts/bin/trivy-gate`)
  always come from the same release as the Dockerfiles they build. A
  workflow change on `develop` reaches the prod nightly only when it is
  released.

This keeps both image sets current with upstream security patches (base
image updates, apt package refreshes) without waiting for a code change to
trigger a build. To trigger a rebuild manually, run the CD workflow from the
Actions tab (**Actions > CD > Run workflow**).

### Pull request builds

Pull requests never publish. `ci.yml` calls `ci-images.yml`, which builds and
scans only the images the change reaches. `docker/versions/selection.py` maps
the changed paths and the `matrix.json` diff to those images, using each
image's input files from `docker/versions/includes.py`. Selecting a parent
also selects every image built `FROM` it. A change to the Trivy configuration
or to the build-and-scan pipeline itself selects every image, and so does an
unclassified path under `docker/` (with a warning). A docs-only change selects
none. Each selected image is built natively on both architectures, without
emulation, and is never pushed to GHCR. A parent reaches the images built
`FROM` it through a registry local to the job.

The required check is the one aggregating gate, `images / evidence`. It is
required by vergil-tooling's generated `CI gates` ruleset because
`vergil.toml` sets `[ci].images = true`. See
[Trivy Scanning](trivy-scanning.md#pull-requests-the-image-scan-of-changed-images)
for the scans and the evidence it uploads.

### Authentication

The workflow authenticates with `GITHUB_TOKEN` using `packages: write`
permission. No personal access token or additional secret is needed.

### GHCR package access grants

Each `dev-*` and `prod-*` package on GHCR must explicitly grant this
repository write access. The packages were originally created by the
`vergil-tooling` repository, so that repo has implicit write access.
This repo does not, unless manually configured.

Per-package setup (one-time, for every image in the generated
[version table](../images/index.md#versions), under both prefixes: each
`dev-<image>` package and its `prod-<image>` counterpart). That table is
generated from `docker/versions/manifest.yml`, the same source as the
publish matrix, so it always lists every published image; do not hand-copy
the list here:

1. Navigate to the package settings page on GHCR.
2. Under **Manage Actions access**, click **Add Repository**.
3. Select `vergil-containers`.
4. Set role to **Write**.

## Consumption

Images are consumed via `vrg-container-run` in
[vergil-tooling](https://github.com/vergil-project/vergil-tooling).
It auto-detects the project language, selects the matching image (falling
back to the base image when no language is detected) and runs the given
command inside it; a repo's validation runs as
`vrg-container-run -- vrg-validate`. The image prefix defaults to `prod-`;
`--prefix dev` selects the `dev-` image. Consuming repos can override the image with the `DOCKER_DEV_IMAGE`
environment variable.
