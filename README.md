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
`ghcr.io/vergil-project/dev-{language}:{version}`.

| Image        | Versions         | Base                      |
| ------------ | ---------------- | ------------------------- |
| `dev-ruby`   | 3.2, 3.3, 3.4    | `ruby:<v>-slim`           |
| `dev-python` | 3.12, 3.13, 3.14 | `python:<v>-slim`         |
| `dev-java`   | 17, 21           | `eclipse-temurin:<v>-jdk` |
| `dev-go`     | 1.25, 1.26       | `golang:<v>`              |
| `dev-rust`   | 1.92, 1.93       | `rust:<v>-slim`           |
| `dev-base`   | latest           | `python:3.14-slim` (base) |

## Usage

Pull a pre-built image:

```bash
docker pull ghcr.io/vergil-project/dev-python:3.14
```

Or build all images locally:

```bash
docker/build.sh
```

`build.sh` auto-detects the container runtime — it prefers `nerdctl`
(Lima + containerd) and falls back to `docker`. Set
`VRG_CONTAINER_RUNTIME` to force a specific one. The single-image
commands below work with either `nerdctl build` or `docker build`.

Build a single image:

```bash
docker/generate.sh python
docker build --build-arg PYTHON_VERSION=3.14 \
  -t dev-python:3.14 docker/python/
```

### Base image

The `dev-base` image includes all common tooling plus MkDocs Material
and mike for documentation. It is the fallback image used by
`vrg-docker-run` when no language is detected, and is shared across all
repos for documentation builds.

Build locally:

```bash
docker/generate.sh base
docker build -t dev-base:latest docker/base/
```

Use via the `docker-docs` wrapper in vergil-tooling:

```bash
docker-docs serve   # Live-reloading preview at http://localhost:8000
docker-docs build   # Build static site (validation)
```

**Python repos**: When `pyproject.toml` is detected, the wrapper runs
`uv sync --group docs` before mkdocs so that mkdocstrings and other
Python-specific plugins are available.

**Environment variables**:

| Variable             | Default                | Description           |
| -------------------- | ---------------------- | --------------------- |
| `DOCKER_DOCS_IMAGE`  | `dev-base:latest`      | Override Docker image |
| `MKDOCS_CONFIG`      | `docs/site/mkdocs.yml` | Path to mkdocs config |
| `DOCS_PORT`          | `8000`                 | Host port for serve   |

## Common Tooling

Every language image includes:

- **Node.js** 22 (via NodeSource apt repo)
- **markdownlint-cli** 0.47.0
- **GitHub CLI** (gh) via official apt repo
- **ShellCheck** 0.11.0
- **shfmt** 3.12.0
- **actionlint** 1.7.11
- **git-cliff** 2.8.0
- **hadolint** 2.14.0
- **uv** 0.7.12
- **yamllint** 1.38.0
- **openssh-client** (SSH for git remote operations)

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

Images are built for both amd64 and arm64, scanned with Trivy on both
platforms, attested with SLSA build provenance, and published to GHCR
on push to `develop` or `main` via the `docker-publish.yml` workflow.
Manual rebuilds can be triggered via `workflow_dispatch` in the Actions
tab.

Image URLs use the user namespace (`ghcr.io/vergil-project/...`), not a
repo-specific namespace, so paths remain stable across repo migrations.

### GHCR access prerequisites

The workflow authenticates with `GITHUB_TOKEN` (`packages: write`). No
PAT or additional secret is needed. Each GHCR package must grant this
repository write access because the packages were originally created by
the `vergil-tooling` repository:

1. Go to the package settings page on GHCR for each `dev-*` package.
2. Under **Manage Actions access**, click **Add Repository**.
3. Select `vergil-containers` and set the role to **Write**.

This applies to: `dev-python`, `dev-java`, `dev-go`, `dev-ruby`,
`dev-rust`, `dev-base`.

## Migration Note

These images were originally maintained in the
[vergil-tooling](https://github.com/vergil-project/vergil-tooling)
repository under `docker/`. They were split into this dedicated
repository to provide an independent release lifecycle and clearer
separation of concerns.
