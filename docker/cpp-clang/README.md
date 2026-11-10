# C++ Clang dev/prod images

Clang/LLVM-family C++ dev container images for the Vergil ecosystem, built for
epic [vergil-project/.github#207](https://github.com/vergil-project/.github/issues/207)
task T1 (issue vergil-project/vergil-containers#467).

## Toolchain discovery — pinned Clang majors

The spec's hard rule (§3.5) is **prebuilt stable binaries only — never built
from source** — and the durable requirement is **two recent majors**. The
concrete majors are whatever is cleanly available prebuilt.

Discovery was first run against `debian:trixie-slim`. Since epic
[vergil-project/.github#649](https://github.com/vergil-project/.github/issues/649)
the image is built on `base` (Ubuntu 24.04), and its spike installed both
majors from the official LLVM apt channel (`apt.llvm.org`) for noble:

| Major | Source (prebuilt) | Version observed | Decision |
| ----- | ----------------- | ---------------- | -------- |
| **20** | `apt.llvm.org` `llvm-toolchain-noble-20` | 20.1.8 | **pinned (primary)** |
| **19** | `apt.llvm.org` `llvm-toolchain-noble-19` | 19.1.7 | **pinned (secondary)** |

Both majors — plus the matching `clang-tidy`, `clang-format`, `lld`, `llvm`
(for `llvm-cov`), and the `libclang-rt` sanitizer runtime — install cleanly as
prebuilt packages, so the **target pins (19 and 20) qualify** and the
`18`/`19` fallback in §3.5/§11 is not needed.

**Clang 20 is the primary major** — the compiler-agnostic `clang-format` /
`clang-tidy` (in `common/cpp-analysis.dockerfile`) track it, and the `[once]`
LINT/AUDIT stages run on it (spec §3.6, §4).

If a future major is wanted, advance the matrix **only once it is available as
a prebuilt stable binary** on this channel (§3.5). The version axis lives in
`docker/versions/manifest.yml` (the `cpp-clang` family); the publish matrix,
which `docker/build.sh` reads, is generated from it.

## Structure (matches this repo's existing image idiom)

- **`docker/cpp-clang/Dockerfile.template`** — the Clang image. `FROM
  ${PARENT_IMAGE}`, which is `base` (the manifest's `parent:`), so every common
  tool comes from `base`. It installs `g++-14` for GCC 14's libstdc++ (noble's
  unversioned `g++` is 13, and Clang would then select libstdc++ 13), composes
  `common/cpp-analysis.dockerfile`, then installs the `CLANG_VERSION` compiler
  + sanitizer runtime and sets `CC=clang` / `CXX=clang++` with libstdc++ as the
  standard library.
- **`docker/cpp-clang/checks.sh`** — the build-time checks, the template's last
  `RUN`: `base`'s invariants and all three of its defaults, the Clang series,
  the GCC 14 libstdc++ selection, the `clang-format`/`clang-tidy` major, and
  noble's cmake (3.28.3) and cppcheck (2.13.0).
- **`common/cpp-analysis.dockerfile`** — the shared, compiler-agnostic analysis
  toolset every C++ image carries (`clang-format`, `clang-tidy`, the unversioned
  `run-clang-tidy` LINT driver, `cppcheck`, `gcovr`, CMake, Conan 2). This is
  plan T1's "shared base layer", expressed as an `@include` fragment so that
  both C++ families, each built on `base`, carry the same layer. The GCC family
  (T2) includes the same fragment.
- **`docker/cpp/smoke/`** + **`docker/cpp/smoke-test.sh`** — the trivial
  CMake + Conan 2 project used as the build-time smoke check (shared across the
  clang and gcc families).

Images are named `dev-cpp-clang:<v>` / `prod-cpp-clang:<v>`, following the
established `{prefix}-{language}:{version}` convention where the `{language}`
token is `cpp-clang` (the directory name == the image name).

## Building and smoke-testing locally

```bash
docker/build.sh cpp-clang                 # builds pkg-ubuntu and base first
docker/build.sh --pull-parents cpp-clang  # or pulls them from GHCR
```

`docker/build.sh` builds both pinned majors on their parent (`dev-base:latest`)
and runs the smoke check for each.
