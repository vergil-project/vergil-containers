# Images

Every image shares a common tooling layer and adds language-specific
runtimes and tools. Images are published as multi-architecture manifests
(amd64 + arm64) to `ghcr.io/vergil-project/dev-<language>:<version>`.

!!! info "Tool versions are managed, not hand-listed here"
    This page is the **inventory** — what each image includes. It deliberately
    does not assert specific tool versions: most tools float on their leading
    edge, a handful of binary tools are auto-bumped weekly, and only a few are
    pinned with a written justification. The always-current version-of-record is
    the generated catalog,
    [`docker/pins/CATALOG.md`](https://github.com/vergil-project/vergil-containers/blob/develop/docker/pins/CATALOG.md).
    For how versions are chosen and managed, see
    [Tool Version Management](../operations/version-management.md).

## Common Layer

All language images include:

| Tool             | Purpose                        |
| ---------------- | ------------------------------ |
| Node.js 22       | Runtime for markdownlint-cli   |
| markdownlint-cli | Markdown linting               |
| gh (GitHub CLI)  | GitHub API and workflows       |
| shellcheck       | Shell script linting           |
| shfmt            | Shell script formatting        |
| actionlint       | GitHub Actions linting         |
| git-cliff        | Changelog generation           |
| hadolint         | Dockerfile linting             |
| uv               | Python package manager         |
| yamllint         | YAML linting                   |
| ansible-lint     | Ansible playbook/role linting  |
| nfpm             | Build `.deb`/`.rpm` packages   |
| pandoc           | Convert Markdown to docx/HTML  |
| git              | Repository operations          |
| openssh-client   | SSH for git remote operations  |
| curl             | HTTP requests                  |

The `dev-base` image includes the full common layer plus documentation
tooling (MkDocs Material, mike, semgrep) and OpenTofu for in-sandbox
OpenTofu module validation. It is the fallback image for repos with no
detected language.

Non-Python images install Python, yamllint, ansible-lint, and uv via the
`python-support` fragment. Python-based images (`dev-python`, `dev-base`)
install them directly via pip.

## Python

**Base**: `python:<version>-slim`
**Versions**: 3.12, 3.13, 3.14

| Tool         | Purpose                        |
| ------------ | ------------------------------ |
| uv           | Python package manager         |
| pytest-xdist | Parallel pytest execution      |

`pytest-xdist` is installed into the image's system Python so the shared
vergil-tooling validation gate's Python TEST command can fan the suite across
cores (`-n auto --dist worksteal`) fleet-wide without every consuming repo
declaring it as a dev dependency. Consuming repos get parallel test execution
by default — when `pytest-xdist` resolves (as it does in this image) and their
`[test].parallel` setting is on (the default).

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

| Tool             | Purpose               |
| ---------------- | --------------------- |
| golangci-lint    | Go linter aggregator  |
| govulncheck      | Vulnerability scanner |
| go-licenses      | License checker       |
| gocyclo          | Cyclomatic complexity |
| goimports        | Import formatter      |
| go-test-coverage | Coverage thresholds   |

`go-test-coverage` is version-pinned per Go version (a live Tenet-6 example — it
is held because newer releases require a newer Go than the `1.25` image ships).
See its entry in [the catalog](https://github.com/vergil-project/vergil-containers/blob/develop/docker/pins/CATALOG.md).

## Java

**Base**: `eclipse-temurin:<version>-jdk`
**Versions**: 17, 21

Java images rely on the consuming repository's Maven wrapper (`mvnw`) to
bootstrap Maven at container startup. No additional Java-specific tools
are pre-installed.

## Rust

**Base**: `rust:<version>-slim`
**Versions**: 1.92, 1.93

| Tool           | Source           | Purpose                     |
| -------------- | ---------------- | --------------------------- |
| clippy         | rustup component | Rust linter                 |
| rustfmt        | rustup component | Code formatter              |
| llvm-tools     | rustup component | Coverage instrumentation    |
| cargo-deny     | cargo            | Dependency security checker |
| cargo-llvm-cov | cargo            | Code coverage               |

## Base

**Base**: `python:3.14-slim`
**Version**: latest

The base image includes the full common layer (all tools listed above)
plus documentation tooling. It is the fallback image used by
`vrg-container-run` when no language is detected.

| Tool            | Purpose                    |
| --------------- | -------------------------- |
| MkDocs Material | Documentation site builder |
| mike            | Versioned doc deployment   |
| semgrep         | Static analysis            |
| pyyaml          | YAML parsing (MkDocs dep)  |
| OpenTofu        | OpenTofu module validation |
