# --- Shared TypeScript analysis toolset (runtime-agnostic) -------------------
# The runtime-agnostic image tools every TypeScript image carries, regardless
# of which Node major it ships (epic vergil-project/.github#284 §3.1, §4). It is
# the "shared base layer" of plan T1 ("Dockerfile.base"), expressed in this
# repo's established @include-fragment idiom rather than a separate FROM-chained
# base image (language images here never FROM one another — they compose
# fragments; see docker/cpp-clang/README.md for the same reconciliation in the
# C++ epic). Every TypeScript image (node-24, node-22, ...) includes this
# fragment.
#
# Requires Node + npm already on PATH: the image's Dockerfile.template installs
# the matrix-versioned Node runtime BEFORE this fragment is composed in.
#
# What the image owns follows vergil-tooling's tool-ownership guideline
# (https://github.com/vergil-project/vergil-tooling/blob/develop/docs/site/docs/standards/development/tool-ownership.md,
# epic vergil-project/.github#1174 §6.3). A repository declares a tool when its
# code or tests import it, it builds the artifact the repository ships, or a
# tool the repository declares requires it. So the image carries only:
#   prettier -> formatter (the ecosystem's reason to install it locally is
#               team consistency, which the shared image meets)
# and NOT typescript, eslint, typescript-eslint, vitest or @vitest/coverage-v8:
# each TypeScript repo declares those as devDependencies, at the majors
# vergil-tooling accepts, and Vergil's gates run them from the repo's
# node_modules/.bin, never from a global install.
#
# Pinning: prettier follows the repo-wide floating doctrine (epic
# vergil-project/.github#155). It installs via `npm install -g` with no
# version, so it resolves the leading edge and floats cleanly — exactly like
# the uv-installed conan/gcovr in common/cpp-analysis.dockerfile. It is not an
# exact x.y.z pin, so this fragment carries no docker/pins/pins.yml entry, and
# the hadolint DL3016 npm-pin rule is repo-ignored by the same policy
# (.hadolint.yaml).
RUN npm install -g \
      prettier && \
    npm cache clean --force
