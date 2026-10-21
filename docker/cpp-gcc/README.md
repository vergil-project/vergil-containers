# C++ GCC dev/prod images

GCC-family C++ dev container images for the Vergil ecosystem, built for
epic [vergil-project/.github#207](https://github.com/vergil-project/.github/issues/207)
task T2 (issue vergil-project/vergil-containers#468).

## Toolchain discovery — pinned GCC majors

The spec's hard rule (§3.5) is **prebuilt stable binaries only — never built
from source**. The concrete majors are whatever is cleanly available prebuilt.

Discovery was run empirically against `debian:trixie-slim` (the Debian release
underlying every other image in this repo, and the base T1 chose for the Clang
family), using Debian's own apt channel — GCC ships in the base distro, so
there is no separate upstream channel to add (unlike Clang's `apt.llvm.org`):

| Major | Source (prebuilt) | Version observed | Decision |
| ----- | ----------------- | ---------------- | -------- |
| **15** | — | not packaged in `debian:trixie-slim` (apt Candidate: none) | **not available** |
| **14** | Debian trixie main (`g++-14`, `gcc-14`) | 14.2.0-19 | **pinned** |
| **13** | Debian trixie main (`g++-13`, `gcc-13`) | 13.3.0-16 | **dropped** — past upstream support |

Only majors 12, 13, and 14 are packaged in trixie main, and `gcc-15` is not
cleanly prebuilt for `debian:trixie-slim`. GCC 13 was built as a secondary
major until upstream stopped maintaining the 13 release series (13.5 was its
last release); it was then dropped (epic vergil-project/.github#407), leaving
**GCC 14** as the only pinned major.

Adding a backports or third-party channel to reach `gcc-15` would violate both
"clean prebuilt from the base image's channels" and this repo's convention that
every image builds from `debian:trixie-slim` main only, so it is deliberately
not done.

Add `gcc-15` to the matrix **only once it is available as a prebuilt stable
binary** on the base image's channel (§3.5). The version axis lives in
`docker/versions/manifest.yml` (the `cpp-gcc` family); `docker/build.sh` and
the publish matrix are generated from it.

Note the compiler-agnostic `clang-format` / `clang-tidy` analysis tools (from
`common/cpp-analysis.dockerfile`) still track Clang's channel and run the
`[once]` LINT/AUDIT stages on the primary **Clang** image (spec §3.6, §4);
`clang-tidy` reads GCC-generated `compile_commands.json` fine. The GCC image
carries the full analysis toolset too, verified by the smoke check.

## Structure (matches the T1 Clang family exactly)

- **`docker/cpp-gcc/Dockerfile.template`** — the GCC image. `FROM
  debian:trixie-slim`, composes the same shared validation fragments as the
  Clang image plus `common/cpp-analysis.dockerfile`, then installs the
  `GCC_VERSION` compiler and sets `CC=gcc` / `CXX=g++` with libstdc++ (GCC's
  native standard library).
- **`common/cpp-analysis.dockerfile`** — the shared, compiler-agnostic analysis
  toolset every C++ image carries (`clang-format`, `clang-tidy`, the unversioned
  `run-clang-tidy` LINT driver, `cppcheck`, `gcovr`, CMake, Conan 2). Reused
  verbatim from T1 — **not** duplicated for
  GCC; the GCC template `@include`s the same fragment the Clang template does.
- **`docker/cpp/smoke/`** + **`docker/cpp/smoke-test.sh`** — the trivial
  CMake + Conan 2 project used as the build-time smoke check, shared across the
  clang and gcc families.

Images are named `dev-cpp-gcc:<v>` / `prod-cpp-gcc:<v>`, following the
established `{prefix}-{language}:{version}` convention where the `{language}`
token is `cpp-gcc` (the directory name == the image name).

## Building and smoke-testing locally

```bash
docker/generate.sh cpp-gcc
nerdctl build --build-arg GCC_VERSION=14 -t dev-cpp-gcc:14 docker/cpp-gcc
docker/cpp/smoke-test.sh dev-cpp-gcc:14
```

`docker/build.sh` builds every pinned major and runs the smoke check for each.
