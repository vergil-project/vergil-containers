# Vergil Containers

Docker dev container images for the
[vergil-tooling](https://github.com/vergil-project/vergil-tooling)
ecosystem.

## Overview

This repository maintains language-specific dev container images published
as multi-architecture manifests (amd64 + arm64) to GitHub Container
Registry (GHCR). Each image bundles the language runtime, package manager,
and a common tooling layer so that CI pipelines and local development
share the same environment.

## Images

All images are published to
`ghcr.io/vergil-project/dev-<language>:<version>`.

<!-- BEGIN generated: versions -->
| Image            | Language   | Versions               | Base                                    |
| ---------------- | ---------- | ---------------------- | --------------------------------------- |
| `dev-python`     | python     | 3.15, 3.14, 3.13, 3.12 | `base:latest`                           |
| `dev-go`         | go         | 1.27, 1.26             | `base:latest`                           |
| `dev-rust`       | rust       | 1.93, 1.92             | `base:latest`                           |
| `dev-cpp-clang`  | cpp        | 20, 19                 | `debian:trixie-slim`                    |
| `dev-cpp-gcc`    | cpp        | 14                     | `debian:trixie-slim`                    |
| `dev-ts-node`    | typescript | 24, 22                 | `debian:trixie-slim`                    |
| `dev-pkg-ubuntu` | —          | 26.04, 24.04           | `ubuntu:<v>`                            |
| `dev-pkg-rhel`   | —          | 10, 9                  | `registry.access.redhat.com/ubi<v>/ubi` |
| `dev-base`       | —          | latest                 | `pkg-ubuntu:24.04`                      |
<!-- END generated: versions -->

See [Images](images/index.md) for per-language tool details.

## Quick Start

### Pull from GHCR

```bash
docker pull ghcr.io/vergil-project/dev-python:3.14
```

### Build locally

```bash
cd vergil-containers
docker/build.sh
```

This builds all images and tags them as `dev-<language>:<version>`.

## Further Reading

- [Images](images/index.md) — per-language tooling and versions
- [Architecture](architecture/index.md) — build strategy, templating,
  and common layer design
