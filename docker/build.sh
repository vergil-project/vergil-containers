#!/usr/bin/env bash
# Managed by vergil-containers — DO NOT EDIT in downstream repos.
# Canonical source: https://github.com/vergil-project/vergil-containers
# build.sh — build all dev container images with default version tags.
#
# Each image is defined by a Dockerfile.template that may contain
# "# @include common/<fragment>.dockerfile" lines.  generate.sh
# expands these includes to produce the final Dockerfile before
# each build.
#
# After a successful build, dangling images are pruned and build cache is
# pruned runtime-aware: docker prunes cache older than 30 days, nerdctl
# prunes dangling cache only (nerdctl builder prune has no --filter).
# Tagged images and volumes are never touched.
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"

# Select the container runtime: prefer nerdctl (OSS, Lima + containerd),
# fall back to docker.  VRG_CONTAINER_RUNTIME overrides auto-detection.
runtime="${VRG_CONTAINER_RUNTIME:-}"
if [ -z "$runtime" ]; then
  if command -v nerdctl >/dev/null 2>&1; then
    runtime=nerdctl
  elif command -v docker >/dev/null 2>&1; then
    runtime=docker
  else
    echo "ERROR: no container runtime found (need nerdctl or docker)" >&2
    exit 1
  fi
fi

# Validate the resolved runtime (covers the override and auto-detect paths)
# so a typo'd or uninstalled runtime fails here with a clear message instead
# of later as a raw "command not found".
if ! command -v "$runtime" >/dev/null 2>&1; then
  echo "ERROR: container runtime '$runtime' not found on PATH (set VRG_CONTAINER_RUNTIME to nerdctl or docker, or leave it unset to auto-detect)" >&2
  exit 1
fi

# nerdctl build needs a reachable containerd/buildkit backend.  Probe it up
# front so a missing backend is an actionable error, not a cryptic mid-build
# failure.
if [ "$runtime" = "nerdctl" ] && ! nerdctl info >/dev/null 2>&1; then
  echo "ERROR: nerdctl cannot reach its containerd/buildkit backend. Ensure the Lima VM is running and provisions buildkitd (see the vergil-vm Lima template). To use Docker instead, set VRG_CONTAINER_RUNTIME=docker." >&2
  exit 1
fi

build() {
  local lang="$1" version_arg="$2" version_val="$3"
  "${script_dir}/generate.sh" "$lang"
  echo "Building dev-${lang}:${version_val} ..."
  "$runtime" build \
    --build-arg "${version_arg}=${version_val}" \
    -t "dev-${lang}:${version_val}" \
    "${script_dir}/${lang}"
}

build python PYTHON_VERSION 3.12
build python PYTHON_VERSION 3.13
build python PYTHON_VERSION 3.14
build ruby   RUBY_VERSION   3.2
build ruby   RUBY_VERSION   3.3
build ruby   RUBY_VERSION   3.4
build java   JDK_VERSION    17
build java   JDK_VERSION    21
build go     GO_VERSION     1.25
build go     GO_VERSION     1.26
build rust   RUST_VERSION   1.92
build rust   RUST_VERSION   1.93

# C++ Clang family (prebuilt-only majors; see docker/cpp-clang/README.md).
# CLANG_VERSION is the compiler-major matrix axis.
build cpp-clang CLANG_VERSION 20
build cpp-clang CLANG_VERSION 19

# C++ GCC family (prebuilt-only majors; see docker/cpp-gcc/README.md).
# GCC_VERSION is the compiler-major matrix axis.
build cpp-gcc GCC_VERSION 14
build cpp-gcc GCC_VERSION 13

# TypeScript (Node.js) family (prebuilt-only majors; see docker/ts-node/README.md).
# NODE_MAJOR is the runtime-major matrix axis. node-24 is the primary (T1);
# node-22 is the second image (T2). Both reuse the same Dockerfile.template via
# the NODE_MAJOR build-arg.
build ts-node NODE_MAJOR 24
build ts-node NODE_MAJOR 22

# Build-time smoke check: a trivial CMake + Conan 2 project compiles, links, and
# runs under each C++ image (spec vergil-project/.github#207 T1/T2). The shared
# smoke check also confirms the analysis toolset is present in each image.
"${script_dir}/cpp/smoke-test.sh" "dev-cpp-clang:20" "$runtime"
"${script_dir}/cpp/smoke-test.sh" "dev-cpp-clang:19" "$runtime"
"${script_dir}/cpp/smoke-test.sh" "dev-cpp-gcc:14" "$runtime"
"${script_dir}/cpp/smoke-test.sh" "dev-cpp-gcc:13" "$runtime"

# Build-time smoke check: a trivial package.json + tsconfig.json project installs
# (npm ci), typechecks (tsc --noEmit), and runs one vitest test under each ts-node
# image (epic vergil-project/.github#284 T1/T2). The smoke check also confirms the
# shared analysis toolset is present in each image.
"${script_dir}/ts-node/smoke-test.sh" "dev-ts-node:24" "$runtime"
"${script_dir}/ts-node/smoke-test.sh" "dev-ts-node:22" "$runtime"

"${script_dir}/generate.sh" base
echo "Building dev-base:latest ..."
"$runtime" build -t "dev-base:latest" "${script_dir}/base"

echo "All images built successfully."

echo "Pruning dangling images and stale build cache ..."
"$runtime" image prune -f
if [ "$runtime" = "docker" ]; then
  docker builder prune -af --filter 'until=720h'
else
  # nerdctl builder prune has no --filter; prune dangling cache only to
  # preserve reusable layers across builds.
  "$runtime" builder prune -f
fi
