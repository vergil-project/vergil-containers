# vergil-containers

Docker dev container images for the
[vergil-tooling](https://github.com/vergil-project/vergil-tooling)
ecosystem. Each image provides a language runtime plus shared tooling
used by CI and local container-based development across all managed
repositories.

## Table of Contents

- [Available Images](#available-images)
- [Usage](#usage)
  - [Base image](#base-image)
- [Common Tooling](#common-tooling)
- [Build System](#build-system)
- [Publishing](#publishing)
- [Migration Note](#migration-note)

## Available Images

All images are published to GitHub Container Registry at
`ghcr.io/vergil-project/{prefix}-{image}:{version}`, with the `dev-` prefix
from `develop` and the `prod-` prefix from `main`: a language image is
`dev-{language}:{version}`, a package toolchain image
`dev-pkg-{distro}:{version}`.

<!-- BEGIN generated: versions -->
| Image            | Language   | Versions               | Base                                    |
| ---------------- | ---------- | ---------------------- | --------------------------------------- |
| `dev-python`     | python     | 3.15, 3.14, 3.13, 3.12 | `base:latest`                           |
| `dev-go`         | go         | 1.27, 1.26             | `base:latest`                           |
| `dev-rust`       | rust       | 1.93, 1.92             | `base:latest`                           |
| `dev-cpp-clang`  | cpp        | 20, 19                 | `base:latest`                           |
| `dev-cpp-gcc`    | cpp        | 14                     | `base:latest`                           |
| `dev-ts-node`    | typescript | 24, 22                 | `base:latest`                           |
| `dev-pkg-ubuntu` | —          | 26.04, 24.04           | `ubuntu:<v>`                            |
| `dev-pkg-rhel`   | —          | 10, 9                  | `registry.access.redhat.com/ubi<v>/ubi` |
| `dev-base`       | —          | latest                 | `pkg-ubuntu:24.04`                      |
<!-- END generated: versions -->

The table is generated from
[`docker/versions/manifest.yml`](docker/versions/manifest.yml), the single
source of every language version this repo builds. Each language's versions
follow its upstream support window; see
[Language version lifecycle](https://vergil-project.github.io/vergil-containers/languages/lifecycle/).

The `pkg-ubuntu` and `pkg-rhel` rows are the package toolchain images:
the upstream image plus the OS prerequisites, uv, nFPM and a toolchain
marker, without the common tooling. vergil-tooling's package jobs build and
install-test in their `prod-` images. See
[Package toolchain images](https://vergil-project.github.io/vergil-containers/images/#package-toolchain-images).

## Usage

Pull a pre-built image:

```bash
docker pull ghcr.io/vergil-project/dev-python:3.14
```

Or build all images locally:

```bash
docker/build.sh            # every image, parents first
docker/build.sh python     # one family, after its parent images
```

`build.sh` auto-detects the container runtime — it prefers `nerdctl`
(Lima + containerd) and falls back to `docker`. Set
`VRG_CONTAINER_RUNTIME` to force a specific one. Set `VRG_APT_MIRROR`
to an http Ubuntu mirror for your architecture (an `ubuntu-ports` one on
arm64) to have apt try it before the images' default mirror list. The single-image
commands below work with either `nerdctl build` or `docker build`.

Build a single image by hand with its matrix entry's build arguments from
`docker/versions/matrix.json`, and `PARENT_IMAGE` for an image built on a
parent. `dev-python` is built on `dev-base` and takes its Python pin as
build arguments, so build its parent first:

```bash
docker/build.sh base
docker/generate.sh python
docker build --build-arg PARENT_IMAGE=dev-base:latest \
  --build-arg PYTHON_VERSION=3.14 --build-arg TOOLCHAIN_VERSION=<pin> \
  --build-arg PBS_RELEASE=<pin> --build-arg TOOLCHAIN_SHA256_AMD64=<pin> \
  --build-arg TOOLCHAIN_SHA256_ARM64=<pin> \
  -t dev-python:3.14 docker/python/
```

### Base image

The `dev-base` image includes all common tooling plus MkDocs Material
and mike for documentation. It is the fallback image used by
`vrg-container-run` when no language is detected, and is shared across all
repos for documentation builds.

It is built `FROM` `pkg-ubuntu:24.04` and takes its core runtimes' versions
as build arguments from `docker/versions/matrix.json`, so build it with
`build.sh`, which builds the parent first (or pulls it with
`--pull-parents`):

```bash
docker/build.sh base
```

Use via the `vrg-container-docs` wrapper in vergil-tooling:

```bash
vrg-container-docs serve   # Live-reloading preview at http://localhost:8000
vrg-container-docs build   # Build static site (validation)
```

`vrg-container-docs` uses the published `prod-base` image by default; pass
`--prefix dev` to use `dev-base` instead.

**Python repos**: When `pyproject.toml` is detected, the wrapper runs
`uv sync --group docs` before mkdocs so that mkdocstrings and other
Python-specific plugins are available.

**Environment variables**:

| Variable            | Default                                       | Description                              |
| ------------------- | --------------------------------------------- | ---------------------------------------- |
| `DOCKER_DOCS_IMAGE` | `ghcr.io/vergil-project/{prefix}-base:latest` | Override the image (ignores `--prefix`)  |
| `MKDOCS_CONFIG`     | `docs/site/mkdocs.yml`                        | Path to mkdocs config                    |
| `DOCS_PORT`         | `8000`                                        | Host port for serve                      |

## Common Tooling

Every language image includes:

- **Node.js** (via NodeSource apt repo) — runtime for markdownlint-cli
- **markdownlint-cli**, **yamllint**, **ansible-lint** — linters
- **ShellCheck**, **shfmt** — shell lint/format
- **actionlint** — GitHub Actions linting
- **git-cliff** — changelog generation
- **hadolint** — Dockerfile linting
- **scorecard**, **trivy** — supply-chain / vulnerability scanning
- **GitHub CLI** (gh) via official apt repo
- **uv** — Python package manager
- **nfpm**, **rpm** — build and inspect `.deb`/`.rpm` packages
- **pandoc** — convert Markdown to `.docx`/HTML
- **jq**, git, curl, **openssh-client** (SSH for git remote operations)

Tool versions are deliberately not listed here, because a hand-copied list
goes stale. Most tools float on their leading edge; the few that are pinned,
and why, are recorded in [`docker/pins/pins.yml`](docker/pins/pins.yml), and
the generated [`docker/pins/CATALOG.md`](docker/pins/CATALOG.md) shows every
pinned version currently in the Dockerfiles. See
[Tool Version Management](https://vergil-project.github.io/vergil-containers/operations/version-management/).

All images are published as multi-architecture manifests supporting
both **amd64** and **arm64**.

The `dev-base` image includes the full common layer plus documentation
tooling (MkDocs Material, mike, semgrep). It is the fallback image for
repos with no detected language.

## Build System

Images are built from `Dockerfile.template` files using a fragment
inclusion system. Shared tooling installations are maintained once in
`docker/common/` and included via `# @include` directives. `generate.sh`
expands templates into final Dockerfiles before each build.

See [Architecture](https://vergil-project.github.io/vergil-containers/architecture/)
for details.

## Publishing

Images are built for both amd64 and arm64, each on its own native runner
(no emulation), scanned with Trivy on both platforms, attested with SLSA
build provenance, and published to GHCR on push to `develop` (`dev-`
images) or `main` (`prod-` images) via the reusable `cd-docker-publish.yml`
workflow. The publish builds every entry of the generated matrix,
`docker/versions/matrix.json`, and `ops.yml` rebuilds both prefixes nightly
without the cache.
Manual rebuilds can be triggered via `workflow_dispatch` in the Actions
tab.

Pull requests publish nothing. Their `images` CI job (`ci-images.yml`)
builds and scans only the images the change reaches, and its
`images / evidence` gate is a required check. See
[Architecture](https://vergil-project.github.io/vergil-containers/architecture/#pull-request-builds).

Image URLs use the user namespace (`ghcr.io/vergil-project/...`), not a
repo-specific namespace, so paths remain stable across repo migrations.

### GHCR access prerequisites

The workflow authenticates with `GITHUB_TOKEN` (`packages: write`). No
PAT or additional secret is needed. Each GHCR package must grant this
repository write access because the packages were originally created by
the `vergil-tooling` repository:

1. Go to the package settings page on GHCR for each package.
2. Under **Manage Actions access**, click **Add Repository**.
3. Select `vergil-containers` and set the role to **Write**.

This applies to every image in the generated
[Available Images](#available-images) table, under both prefixes: each
`dev-<image>` package and its `prod-<image>` counterpart. That table is
generated from [`docker/versions/manifest.yml`](docker/versions/manifest.yml),
the same source as the publish matrix, so it always lists every published image.

## Migration Note

These images were originally maintained in the
[vergil-tooling](https://github.com/vergil-project/vergil-tooling)
repository under `docker/`. They were split into this dedicated
repository to provide an independent release lifecycle and clearer
separation of concerns.
