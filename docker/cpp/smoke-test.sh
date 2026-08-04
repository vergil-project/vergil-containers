#!/usr/bin/env bash
# Managed by vergil-containers — DO NOT EDIT in downstream repos.
# Canonical source: https://github.com/vergil-project/vergil-containers
# smoke-test.sh — run the trivial CMake + Conan 2 smoke check against a built
# C++ image (spec vergil-project/.github#207 T1: "compiles, links, and runs
# under each Clang image"). Shared by the clang and gcc families.
#
# Usage:
#   docker/cpp/smoke-test.sh <image-tag> [runtime]
#
# <image-tag> e.g. dev-cpp-clang:20. [runtime] overrides runtime selection
# (defaults to VRG_CONTAINER_RUNTIME, then nerdctl, then docker).
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"

image="${1:-}"
if [ -z "$image" ]; then
  echo "ERROR: usage: $0 <image-tag> [runtime]" >&2
  exit 1
fi

# Select the container runtime, mirroring docker/build.sh.
runtime="${2:-${VRG_CONTAINER_RUNTIME:-}}"
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

echo "Smoke-testing ${image} (runtime: ${runtime}) ..."
"$runtime" run --rm \
  -v "${script_dir}/smoke:/smoke:ro" \
  "$image" \
  bash /smoke/run-in-container.sh
