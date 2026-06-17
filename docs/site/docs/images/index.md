# Images

Every image shares a common tooling layer and adds language-specific
runtimes and tools. Images are published as multi-architecture manifests
(amd64 + arm64) to `ghcr.io/vergil-project/dev-<language>:<version>`.

## Common Layer

All language images include:

| Tool             | Version | Purpose                        |
| ---------------- | ------- | ------------------------------ |
| Node.js          | 22      | Runtime for markdownlint-cli   |
| markdownlint-cli | 0.47.0  | Markdown linting               |
| gh (GitHub CLI)  | latest  | GitHub API and workflows       |
| shellcheck       | 0.11.0  | Shell script linting           |
| shfmt            | 3.12.0  | Shell script formatting        |
| actionlint       | 1.7.11  | GitHub Actions linting         |
| git-cliff        | 2.8.0   | Changelog generation           |
| hadolint         | 2.14.0  | Dockerfile linting             |
| uv               | 0.7.12  | Python package manager         |
| yamllint         | 1.38.0  | YAML linting                   |
| ansible-lint     | 26.4.0  | Ansible playbook/role linting  |
| git              | latest  | Repository operations          |
| openssh-client   | latest  | SSH for git remote operations  |
| curl             | latest  | HTTP requests                  |

The `dev-base` image includes the full common layer plus documentation
tooling (MkDocs Material, mike, semgrep). It is the fallback image for
repos with no detected language.

Non-Python images install Python, yamllint, ansible-lint, and uv via the
`python-support` fragment. Python-based images (`dev-python`, `dev-base`)
install them directly via pip.

## Python

**Base**: `python:<version>-slim`
**Versions**: 3.12, 3.13, 3.14

| Tool | Version | Purpose                |
| ---- | ------- | ---------------------- |
| uv   | 0.7.12  | Python package manager |

## Ruby

**Base**: `ruby:<version>-slim`
**Versions**: 3.2, 3.3, 3.4

| Tool           | Source     | Purpose                 |
| -------------- | ---------- | ----------------------- |
| bundler        | system gem | Ruby dependency manager |
| license_finder | gem        | License auditing        |

## Go

**Base**: `golang:<version>`
**Versions**: 1.25, 1.26

| Tool             | Version | Purpose               |
| ---------------- | ------- | --------------------- |
| golangci-lint    | 2.10.1  | Go linter aggregator  |
| govulncheck      | 1.1.4   | Vulnerability scanner |
| go-licenses      | 2.0.1   | License checker       |
| gocyclo          | 0.6.0   | Cyclomatic complexity |
| goimports        | 0.42.0  | Import formatter      |
| go-test-coverage | 2.18.3  | Coverage thresholds   |

## Java

**Base**: `eclipse-temurin:<version>-jdk`
**Versions**: 17, 21

Java images rely on the consuming repository's Maven wrapper (`mvnw`) to
bootstrap Maven at container startup. No additional Java-specific tools
are pre-installed.

## Rust

**Base**: `rust:<version>-slim`
**Versions**: 1.92, 1.93

| Tool           | Version          | Purpose                     |
| -------------- | ---------------- | --------------------------- |
| clippy         | rustup component | Rust linter                 |
| rustfmt        | rustup component | Code formatter              |
| llvm-tools     | rustup component | Coverage instrumentation    |
| cargo-deny     | 0.19.0           | Dependency security checker |
| cargo-llvm-cov | 0.6.16           | Code coverage               |

## Base

**Base**: `python:3.14-slim`
**Version**: latest

The base image includes the full common layer (all tools listed above)
plus documentation tooling. It is the fallback image used by
`vrg-docker-run` when no language is detected.

| Tool            | Version | Purpose                    |
| --------------- | ------- | -------------------------- |
| MkDocs Material | 9.6.12  | Documentation site builder |
| mike            | 2.1.3   | Versioned doc deployment   |
| semgrep         | latest  | Static analysis            |
| pyyaml          | 6.0.3   | YAML parsing (MkDocs dep)  |
