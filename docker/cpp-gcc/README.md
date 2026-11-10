# C++ GCC dev/prod images

GCC-family C++ dev container images for the Vergil ecosystem, built for
epic [vergil-project/.github#207](https://github.com/vergil-project/.github/issues/207)
task T2 (issue vergil-project/vergil-containers#468), and moved onto `base`
(Ubuntu 24.04, noble) by epic
[vergil-project/.github#649](https://github.com/vergil-project/.github/issues/649)
(issue vergil-project/vergil-containers#785).

## Toolchain discovery — pinned GCC majors

The spec's hard rule (§3.5) is **prebuilt stable binaries only — never built
from source**. The concrete majors are whatever is cleanly available prebuilt.

The image is built on `base`, whose root is `ubuntu:24.04` (noble), and GCC
comes from noble's own archive: GCC ships in the base distro, so there is no
separate upstream channel to add (unlike Clang's `apt.llvm.org`). Discovery was
run against noble by the epic's spike (vergil-project/.github#982,
`epics/649-ubuntu-base-platform/spike.md`, item 1) and rechecked on
2026-11-10 against Launchpad's published sources for noble:

| Major | Source (prebuilt) | Version observed | Decision |
| ----- | ----------------- | ---------------- | -------- |
| **15** | — | not published for noble | **not available** |
| **14** | noble-updates and noble-security (`gcc-14`, `g++-14`) | 14.2.0-4ubuntu2~24.04.1 | **pinned** |

noble's release pocket holds only `gcc-14` 14-20240412-0ubuntu1, a pre-release
snapshot; apt prefers the released 14.2.0 from `noble-updates`, which
`ubuntu:24.04` enables. The Ubuntu Toolchain PPA carries a newer 14.3.0, but
noble's own released 14.2.0 meets the rule without a third-party channel, so
the PPA is not used. The image installs the versioned `g++-14`: noble's
unversioned `g++` is 13, and would bring libstdc++ 13.

GCC 13 was built as a secondary major until upstream stopped maintaining the
13 release series (13.5 was its last release); it was then dropped (epic
vergil-project/.github#407), leaving **GCC 14** as the only pinned major.

Add `gcc-15` to the matrix **only once noble publishes it as a released,
prebuilt binary** (§3.5); the lifecycle adapter reports it as blocked until
then. The version axis lives in `docker/versions/manifest.yml` (the `cpp-gcc`
family); the publish matrix, which `docker/build.sh` reads, is generated from
it.

Note the compiler-agnostic `clang-format` / `clang-tidy` analysis tools (from
`common/cpp-analysis.dockerfile`) still track Clang's channel and run the
`[once]` LINT/AUDIT stages on the primary **Clang** image (spec §3.6, §4);
`clang-tidy` reads GCC-generated `compile_commands.json` fine. The GCC image
carries the full analysis toolset too, verified by the smoke check.

## Structure

- **`docker/cpp-gcc/Dockerfile.template`** — the GCC image. `FROM
  ${PARENT_IMAGE}` (`base`, named in the manifest), adds
  `common/cpp-analysis.dockerfile`, then installs the `GCC_VERSION` compiler
  and sets `CC=gcc` / `CXX=g++` with libstdc++ (GCC's native standard
  library). Everything else (the shared validation tools, the core runtimes)
  comes from `base`.
- **`docker/cpp-gcc/checks.sh`** — the template's last `RUN`: base's
  invariants and all three of its defaults (cpp-gcc changes none of `python3`,
  `node` or `pip`), then the compiler (a released `gcc-<v>`/`g++-<v>`, the
  unversioned names, libstdc++ `<v>`), `clang-format-<t>`/`clang-tidy-<t>` at
  `CLANG_TOOLS_VERSION`, and noble's cmake 3.28.3 and cppcheck 2.13.0.
- **`common/cpp-analysis.dockerfile`** — the shared, compiler-agnostic analysis
  toolset every C++ image carries (`clang-format`, `clang-tidy`, the unversioned
  `run-clang-tidy` LINT driver, `cppcheck`, `gcovr`, CMake, Conan 2), shared
  with the Clang family.
- **`docker/cpp/smoke/`** + **`docker/cpp/smoke-test.sh`** — the trivial
  CMake + Conan 2 project used as the build-time smoke check, shared across the
  clang and gcc families.

Images are named `dev-cpp-gcc:<v>` / `prod-cpp-gcc:<v>`, following the
established `{prefix}-{language}:{version}` convention where the `{language}`
token is `cpp-gcc` (the directory name == the image name).

## Building and smoke-testing locally

```bash
docker/build.sh cpp-gcc
```

`docker/build.sh` builds the image's parents first (`pkg-ubuntu:24.04`, then
`base`), then every pinned major, and runs the smoke check for each. With
`--pull-parents` it pulls the published parents instead.
