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
# vergil-project/.github#155). All but `typescript` install via `npm install -g`
# with no version, so they resolve the leading edge and float cleanly — exactly
# like the uv-installed conan/gcovr in common/cpp-analysis.dockerfile.
#
# `typescript` carries a MAJOR-LINE constraint (`typescript@5`) rather than a bare
# float. For v1 the epic standardizes on the stable TypeScript 5.x line so the
# strictness contract (T4), its docs (T8), and the end-to-end validation (T10)
# all target the same compiler; an unconstrained `typescript` now resolves to the
# 7.0.2 native (Go) port line ("tsgo"), whose adoption is a deferral-ledger item
# for the follow-on brainstorm (#286), not a v1 foundation (issue #531). `@5`
# tracks the leading edge WITHIN the 5.x major, so it stays a floating,
# language-major choice — not an exact x.y.z reproducibility pin. It also keeps
# typescript-eslint's type-aware rules on the classic compiler API they target.
#
# None of these is an exact x.y.z pin (a major-only constraint like `@5` is
# deliberately NOT captured by docker/pins/extract_pins.py, same class as the
# NODE_MAJOR matrix arg), so this fragment carries no docker/pins/pins.yml entry,
# and the hadolint DL3016 npm-pin rule is repo-ignored by the same policy
# (.hadolint.yaml).
#
# Toolset (spec §4):
#   typescript          -> tsc (the single canonical typechecker; pinned to 5.x)
#   eslint              -> the ESLint engine
#   typescript-eslint   -> type-aware lint (parser + plugin meta package; library)
#   prettier            -> formatter
#   vitest              -> test runner
#   @vitest/coverage-v8 -> V8 coverage provider (library, drives `vitest --coverage`)
#   license-checker     -> dependency license enumeration
RUN npm install -g \
      typescript@5 \
      eslint \
      typescript-eslint \
      prettier \
      vitest \
      @vitest/coverage-v8 \
      license-checker && \
    npm cache clean --force
