# --- Shared TypeScript analysis toolset (runtime-agnostic) -------------------
# The runtime-agnostic analysis layer every TypeScript image carries, regardless
# of which Node major it ships (epic vergil-project/.github#284 §3.1, §4). It is
# the "shared base layer" of plan T1 ("Dockerfile.base"), expressed in this
# repo's established @include-fragment idiom rather than a separate FROM-chained
# base image (language images here never FROM one another — they compose
# fragments; see docker/cpp-clang/README.md for the same reconciliation in the
# C++ epic). Every TypeScript image (the node-24 primary and the node-22 second
# image added in T2) includes this fragment.
#
# Requires Node + npm already on PATH: the image's Dockerfile.template installs
# the matrix-versioned Node runtime BEFORE this fragment is composed in.
#
# Pinning: these tools follow the repo-wide floating doctrine (epic
# vergil-project/.github#155). They install via `npm install -g` with no version,
# so they resolve the leading edge and float cleanly — exactly like the
# uv-installed conan/gcovr in common/cpp-analysis.dockerfile. None is an exact
# x.y.z pin, so this fragment carries no docker/pins/pins.yml entry, and the
# hadolint DL3016 npm-pin rule is repo-ignored by the same policy (.hadolint.yaml).
#
# Toolset (spec §4):
#   typescript          -> tsc (the single canonical typechecker)
#   eslint              -> the ESLint engine
#   typescript-eslint   -> type-aware lint (parser + plugin meta package; library)
#   prettier            -> formatter
#   vitest              -> test runner
#   @vitest/coverage-v8 -> V8 coverage provider (library, drives `vitest --coverage`)
#   license-checker     -> dependency license enumeration
RUN npm install -g \
      typescript \
      eslint \
      typescript-eslint \
      prettier \
      vitest \
      @vitest/coverage-v8 \
      license-checker && \
    npm cache clean --force
