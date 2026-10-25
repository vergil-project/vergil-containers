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

## Versions

Every image and the language versions it is published for.
The table is generated from `docker/versions/manifest.yml` by
`docker/versions/generate.py`; edit the manifest, not the table.

<!-- BEGIN generated: versions -->
| Image           | Language   | Versions               | Base                      |
| --------------- | ---------- | ---------------------- | ------------------------- |
| `dev-python`    | python     | 3.15, 3.14, 3.13, 3.12 | `python:<v>-slim`         |
| `dev-java`      | java       | 21, 17                 | `eclipse-temurin:<v>-jdk` |
| `dev-go`        | go         | 1.27, 1.26             | `golang:<v>`              |
| `dev-rust`      | rust       | 1.93, 1.92             | `rust:<v>-slim`           |
| `dev-cpp-clang` | cpp        | 20, 19                 | `debian:trixie-slim`      |
| `dev-cpp-gcc`   | cpp        | 14                     | `debian:trixie-slim`      |
| `dev-ts-node`   | typescript | 24, 22                 | `debian:trixie-slim`      |
| `dev-base`      | —          | latest                 | `python:3.14-slim`        |
<!-- END generated: versions -->

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
| rpm              | Inspect `.rpm`, `rpm.vercmp`   |
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

## Go

**Base**: `golang:<version>`

| Tool             | Purpose               |
| ---------------- | --------------------- |
| golangci-lint    | Go linter aggregator  |
| govulncheck      | Vulnerability scanner |
| go-licenses      | License checker       |
| gocyclo          | Cyclomatic complexity |
| goimports        | Import formatter      |
| go-test-coverage | Coverage thresholds   |

`go-test-coverage` is version-pinned per Go version (a live Tenet-6 example — it
is held because newer releases require a newer Go than the `1.26` image ships,
and the image builds with `GOTOOLCHAIN=local`).
See its entry in [the catalog](https://github.com/vergil-project/vergil-containers/blob/develop/docker/pins/CATALOG.md).

Go `1.25` was retired in
[#606](https://github.com/vergil-project/vergil-containers/issues/606): it is
out of upstream support and its standard library carries HIGH CVEs that no Go
1.25 release will fix. Already-published
`dev-go:1.25` tags remain in GHCR but are no longer rebuilt. Follow-up:
[vergil-project/.github#403](https://github.com/vergil-project/.github/issues/403).

## Java

**Base**: `eclipse-temurin:<version>-jdk`

Java images rely on the consuming repository's Maven wrapper (`mvnw`) to
bootstrap Maven at container startup. No additional Java-specific tools
are pre-installed.

## Rust

**Base**: `rust:<version>-slim`

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
