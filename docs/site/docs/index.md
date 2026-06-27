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

| Language | Versions         | Image        |
| -------- | ---------------- | ------------ |
| Python   | 3.12, 3.13, 3.14 | `dev-python` |
| Ruby     | 3.2, 3.3, 3.4    | `dev-ruby`   |
| Go       | 1.25, 1.26       | `dev-go`     |
| Java     | 17, 21           | `dev-java`   |
| Rust     | 1.92, 1.93       | `dev-rust`   |
| Base     | latest           | `dev-base`   |

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
