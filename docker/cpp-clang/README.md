# C++ Clang dev/prod images

Clang/LLVM-family C++ dev container images for the Vergil ecosystem, built for
epic [vergil-project/.github#207](https://github.com/vergil-project/.github/issues/207)
task T1 (issue vergil-project/vergil-containers#467).

## Toolchain discovery — pinned Clang majors

The spec's hard rule (§3.5) is **prebuilt stable binaries only — never built
from source** — and the durable requirement is **two recent majors**. The
concrete majors are whatever is cleanly available prebuilt.

Discovery was run empirically against `debian:trixie-slim` (the Debian release
underlying the other images in this repo) plus the official LLVM apt channel
(`apt.llvm.org`):

| Major | Source (prebuilt) | Version observed | Decision |
| ----- | ----------------- | ---------------- | -------- |
| **20** | `apt.llvm.org` `llvm-toolchain-trixie-20` | 20.1.8 | **pinned (primary)** |
| **19** | `apt.llvm.org` `llvm-toolchain-trixie-19` (also Debian trixie main, 19.1.7) | 19.1.x | **pinned (secondary)** |

Both majors — plus the matching `clang-tidy`, `clang-format`, `lld`, `llvm`
(for `llvm-cov`), and the `libclang-rt` sanitizer runtime — install cleanly as
prebuilt packages, so the **target pins (19 and 20) qualify** and the
`18`/`19` fallback in §3.5/§11 is not needed.

**Clang 20 is the primary major** — the compiler-agnostic `clang-format` /
`clang-tidy` (in `common/cpp-analysis.dockerfile`) track it, and the `[once]`
LINT/AUDIT stages run on it (spec §3.6, §4).

If a future major is wanted, advance the matrix **only once it is available as
a prebuilt stable binary** on this channel (§3.5). The version axis lives in
`docker/build.sh` (the `cpp-clang` build lines) and the publish matrix.

## Structure (matches this repo's existing image idiom)

- **`docker/cpp-clang/Dockerfile.template`** — the Clang image. `FROM
  debian:trixie-slim`, composes the shared validation fragments (the same set
  the `rust` image uses) plus `common/cpp-analysis.dockerfile`, then installs
  the `CLANG_VERSION` compiler + sanitizer runtime and sets `CC=clang` /
  `CXX=clang++` with libstdc++ as the standard library.
- **`common/cpp-analysis.dockerfile`** — the shared, compiler-agnostic analysis
  toolset every C++ image carries (`clang-format`, `clang-tidy`, the unversioned
  `run-clang-tidy` LINT driver, `cppcheck`, `gcovr`, CMake, Conan 2). This is
  plan T1's "shared base layer", expressed as
  an `@include` fragment because language images in this repo compose fragments
  rather than `FROM`-chaining a locally-built base image. The future GCC family
  (T2) includes the same fragment.
- **`docker/cpp/smoke/`** + **`docker/cpp/smoke-test.sh`** — the trivial
  CMake + Conan 2 project used as the build-time smoke check (shared across the
  clang and gcc families).

Images are named `dev-cpp-clang:<v>` / `prod-cpp-clang:<v>`, following the
established `{prefix}-{language}:{version}` convention where the `{language}`
token is `cpp-clang` (the directory name == the image name).

## Building and smoke-testing locally

```bash
docker/generate.sh cpp-clang
nerdctl build --build-arg CLANG_VERSION=20 -t dev-cpp-clang:20 docker/cpp-clang
docker/cpp/smoke-test.sh dev-cpp-clang:20
```

`docker/build.sh` builds both pinned majors and runs the smoke check for each.
