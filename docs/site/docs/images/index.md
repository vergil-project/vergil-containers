# Images

The images come in two kinds. The **language images** (Python, Go, Rust,
C++, TypeScript / Node.js) and `base` share a common tooling layer and add
language-specific runtimes and tools; they are published to
`ghcr.io/vergil-project/dev-<language>:<version>` (and `dev-base:latest`).
The **package toolchain images**, `pkg-ubuntu` and `pkg-rhel`, carry no
common layer: they are the minimal images that package jobs build and
install-test in, published to `ghcr.io/vergil-project/dev-pkg-<distro>:<version>`
(see [Package toolchain images](#package-toolchain-images)). Every image is
published as a multi-architecture manifest (amd64 + arm64), with a `dev-`
prefix from `develop` and a `prod-` prefix from `main`.

!!! info "Tool versions are managed, not hand-listed here"
    This page is the **inventory** — what each image includes. It deliberately
    does not assert specific tool versions: most tools float on their leading
    edge, a handful of binary tools are auto-bumped daily, and only a few are
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

## Common Layer

All language images include the tools below. The package toolchain images
do not: see [Package toolchain images](#package-toolchain-images) for what
they carry.

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

An image built on `dev-base` (its base is `base:latest` in the table above)
takes Python, yamllint, ansible-lint, and uv from it: see [Python](#python) and
[Go](#go). The images still built on an upstream image install them via the
`python-support` fragment.
`dev-base` is different: see [Base](#base).

## Python

**Base**: `dev-base` (`base:latest`)

The family Python is the python-build-standalone install-only build of the
series, unpacked at `/opt/python/<version>`. Its release, version and each
architecture's SHA-256 are pinned in `docker/pins/toolchains.yml`, and the
build checks the download against the hash. `python3`, `python`,
`python<version>`, `pip` and `pip3` in `/usr/local/bin` link into it, so
`python3` is the series. It is a plain system interpreter, not a uv-managed
one, so uv finds it with `UV_PYTHON_PREFERENCE=only-system`. base's own tools
keep running on the core Python under `/opt/vergil/python/`.

| Tool | Purpose                       |
| ---- | ----------------------------- |
| pip  | The series' bundled pip       |

Nothing is pip-installed into the family Python, and its bundled pip is never
upgraded in place: a fix comes with a newer pin of the series.

`pytest-xdist` is no longer in the image. A consuming repo that wants
parallel tests declares it in its dev dependencies. Without it the shared
vergil-tooling validation gate runs the suite serially.

## Go

**Base**: `dev-base`, plus the go.dev release of the series at
`/usr/local/go`. The release and its SHA-256 for each architecture are pinned
in
[`docker/pins/toolchains.yml`](https://github.com/vergil-project/vergil-containers/blob/develop/docker/pins/toolchains.yml),
and the daily upstream refresh moves the pin to the newest patch of the
series. The image keeps the environment the `golang` images set
(`GOPATH=/go`, `GOTOOLCHAIN=local`, `/go/bin` and `/usr/local/go/bin` on
`PATH`) and their C toolchain for cgo (`gcc`, `g++`, `libc6-dev`, `make`,
`pkg-config`).

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

## Rust

**Base**: `base:latest`

The series' exact Rust release, pinned in `docker/pins/toolchains.yml`, is
installed with a pinned `rustup-init` (its SHA-256 checked per architecture)
on rustup's minimal profile, under `/usr/local/rustup` and `/usr/local/cargo`
as in the `rust:<version>-slim` images it replaces. `gcc`, `libc6-dev` and
`pkg-config` come from Ubuntu as the C linker.

| Tool           | Source           | Purpose                     |
| -------------- | ---------------- | --------------------------- |
| gcc            | Ubuntu apt       | C linker for rustc          |
| clippy         | rustup component | Rust linter                 |
| rustfmt        | rustup component | Code formatter              |
| llvm-tools     | rustup component | Coverage instrumentation    |
| cargo-deny     | cargo            | Dependency security checker |
| cargo-llvm-cov | cargo            | Code coverage               |

## Base

**Base**: `pkg-ubuntu:24.04` (Ubuntu 24.04, with uv and nFPM)
**Version**: latest

The base image includes the full common layer (all tools listed above)
plus documentation tooling. It is the fallback image used by
`vrg-container-run` when no language is detected.

| Tool            | Purpose                    |
| --------------- | -------------------------- |
| MkDocs Material | Documentation site builder |
| mike            | Versioned doc deployment   |
| semgrep         | Static analysis            |
| OpenTofu        | OpenTofu module validation |

Its own tools run on core runtimes installed side by side under
`/opt/vergil/`, whose series come from the version manifest's `core:`
section (epic vergil-project/.github#649):

- **Core Python**: `vergil-python<core>` from the vergil apt repository, at
  `/opt/vergil/python/<core>/`. yamllint, ansible-lint, semgrep and MkDocs
  (with mkdocs-material and mike) are uv tools on it, each in its own
  environment. `/usr/local/bin/python3` links to it and promises the
  standard library only: nothing is pip-installed into it, and there is no
  `pip` on `PATH`. A script that needs a third-party package declares it
  inline (PEP 723) and runs with `uv run`.
  `semgrep` and `pysemgrep` are wrappers that run the tool's entry points
  with the stack hard limit lowered to 2929688 KiB when it is unlimited or
  larger. semgrep sets `semgrep-core`'s stack limit to a third of the hard
  limit, and on Python 3.15 an unlimited hard limit gives a finite limit of
  about 5 EiB that crashes `semgrep-core`
  ([vergil-containers#825](https://github.com/vergil-project/vergil-containers/issues/825)).
  The wrappers go once semgrep fixes this upstream
  ([vergil-containers#826](https://github.com/vergil-project/vergil-containers/issues/826)).
- **Core Node**: the pinned nodejs.org release of the core major, at
  `/opt/vergil/node/<core-major>/`, which runs markdownlint-cli. There is no
  `node`, `npm` or `npx` on `PATH`; `markdownlint` is a wrapper that runs
  the core Node by path.

## Package toolchain images

**Images**: `pkg-ubuntu` (Ubuntu 26.04, 24.04) and `pkg-rhel` (RHEL 10, 9)
**Bases**: `ubuntu:<version>` and `registry.access.redhat.com/ubi<version>/ubi`

These are the images vergil's package jobs run in (epic
vergil-project/.github#607). vergil-tooling's package build and install-test
cells run in the published `prod-pkg-ubuntu:<version>` and
`prod-pkg-rhel:<version>` images (since vergil-tooling v2.1.297), one per
package target. vergil-actions' `actions/package/setup` requires them: since
vergil-actions v2.1.62 it installs no toolchain of its own and fails the job
in any other image. Baking the toolchain into a nightly-rebuilt image means
no package job downloads it at run time.

Each image is the upstream image plus only what a package job needs, and
nothing else: no common layer, no vergil-tooling.

| Content | `pkg-ubuntu` | `pkg-rhel` |
| ------- | ------------ | ---------- |
| OS upgrade | `apt-get upgrade` at build time | `dnf upgrade` at build time |
| OS prerequisites | `ca-certificates`, `curl`, `git`, `tar`, `gzip`, `gnupg` | `ca-certificates`, `curl`, `gpg`, `git`, `tar`, `gzip` |
| uv | pinned release, in `/usr/local/bin` (with `uvx`) | same |
| nFPM | pinned release, in `/usr/local/bin` | same |
| apt configuration | fail-fast config on every architecture; mirror list on amd64 | — |
| Toolchain marker | `/etc/vergil/package-toolchain` | same |
| Python | none | only the distro's `python3`, which dnf runs on |

Notes on the rows:

- **OS upgrade**: the packages are upgraded when the image is built, and
  the images are rebuilt nightly, so a package job starts on a current OS.
  Package lists and the dnf cache are not kept: they would go stale between
  rebuilds, so a job that needs them runs its own `apt-get update`.
- **OS prerequisites on `pkg-rhel`**: UBI ships `curl-minimal`, which
  conflicts with the full `curl` package, so the image asks dnf for
  `/usr/bin/curl` and `/usr/bin/gpg` by path and accepts whichever package
  provides them.
- **uv and nFPM**: both are pinned and checksum-verified, and the daily
  upstream refresh floats their pins; see
  [the catalog](https://github.com/vergil-project/vergil-containers/blob/develop/docker/pins/CATALOG.md).
  The package setup action installs vergil-tooling with uv, under a Python
  that uv fetches itself.
- **apt configuration (`pkg-ubuntu`)**: on amd64 and arm64,
  `/etc/apt/apt.conf.d/80-vergil-fast-fail` sets 3 retries with no retry
  delay, 20 s timeouts and a 60 s dpkg lock wait, so a stalled mirror fails
  fast instead of hanging the job, and `APT::Update::Error-Mode "any"`, so
  `apt-get update` fails when no mirror serves an index instead of warning
  and leaving the job to fail later on a missing package. The Ubuntu
  sources are rewritten to `mirror+file:/etc/apt/apt-mirrors.txt`, so apt
  fails over down a list that starts with Canonical's hosts and ends with
  mirrors outside `ubuntu.com`, so a DNS failure of that zone does not
  stop the build. On amd64 the list is the in-region Azure mirror,
  `archive.ubuntu.com` and `security.ubuntu.com`, then
  `mirrors.edge.kernel.org` and `mirrors.dotsrc.org`; on arm64 it is
  `ports.ubuntu.com`, then `mirrors.dotsrc.org` and `mirrors.mit.edu`
  (their `ubuntu-ports` archives). apt checks every index against the
  archive's signed `InRelease`, so a third-party mirror cannot alter a
  package. For a local build,
  `VRG_APT_MIRROR=http://<mirror>/ubuntu/ docker/build.sh` (an
  `ubuntu-ports` URI on arm64) puts a nearer mirror first; CI and publish
  never set it. vergil-tooling passes the retry, timeout and lock options
  on each apt command line it runs; in `pkg-ubuntu` its apt calls also
  read the error mode from this file.
- **Toolchain marker**: `/etc/vergil/package-toolchain` has one
  `<tool> <version>` line for each of `uv`, `nfpm`, `curl`, `git`, `gpg`,
  `tar` and `gzip`, each version read from `<tool> --version` when the image
  is built. `actions/package/setup` checks the image against it before
  anything else: a missing marker, a required tool it leaves out, or a
  listed tool missing or at another version fails the job.
- **Python**: `pkg-ubuntu` has no `python3` at all. `pkg-rhel` keeps UBI's
  own `/usr/bin/python3`, because dnf runs on it, and adds no other Python.

Each template's build-time checks fail the build if any of this is missing,
so no published image can lack it.

`pkg-ubuntu:24.04` is also the parent of [`base`](#base), which takes uv and
nFPM from it. `base` removes the toolchain marker, because it is not a
package toolchain image.
