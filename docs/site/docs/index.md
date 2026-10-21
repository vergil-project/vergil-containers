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
| Image           | Language   | Versions         | Base                      |
| --------------- | ---------- | ---------------- | ------------------------- |
| `dev-python`    | python     | 3.14, 3.13, 3.12 | `python:<v>-slim`         |
| `dev-ruby`      | ruby       | 3.4, 3.3, 3.2    | `ruby:<v>-slim`           |
| `dev-java`      | java       | 21, 17           | `eclipse-temurin:<v>-jdk` |
| `dev-go`        | go         | 1.26             | `golang:<v>`              |
| `dev-rust`      | rust       | 1.93, 1.92       | `rust:<v>-slim`           |
| `dev-cpp-clang` | cpp        | 20, 19           | `debian:trixie-slim`      |
| `dev-cpp-gcc`   | cpp        | 14, 13           | `debian:trixie-slim`      |
| `dev-ts-node`   | typescript | 24, 22           | `debian:trixie-slim`      |
| `dev-base`      | —          | latest           | `python:3.14-slim`        |
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
