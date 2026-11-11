#!/usr/bin/env bash
# Managed by vergil-containers — DO NOT EDIT in downstream repos.
# Canonical source: https://github.com/vergil-project/vergil-containers
# build.sh — build the dev container images with default version tags.
#
# Usage: build.sh [--pull-parents] [<family> ...]
#
# With no family, every entry of docker/versions/matrix.json is built, in the
# publish workflow's tier order: an image's parent (the image it is built
# FROM, named in docker/versions/manifest.yml) is always built before it. With
# families named, every version of each is built, after its parents;
# --pull-parents pulls those parents from GHCR (ghcr.io/vergil-project/dev-*)
# instead of building them. Each build gets every --build-arg in its matrix
# entry's build-args, and a child gets PARENT_IMAGE=dev-<parent>:<version>, the
# local tag of its parent.
#
# VRG_APT_MIRROR, when set, is passed as the APT_MIRROR build arg to each image
# that declares it (pkg-ubuntu, through common/apt-mirror.dockerfile): an http
# Ubuntu mirror for this host's architecture (an ubuntu-ports one on arm64) that
# apt tries before the default mirror list. It is for local builds only; CI and
# publish never set it.
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

usage() {
  echo "Usage: $0 [--pull-parents] [<family> ...]"
}

pull_parents=0
families=()
for arg in "$@"; do
  case "$arg" in
    --pull-parents) pull_parents=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    -*)
      echo "ERROR: unknown option '$arg'" >&2
      usage >&2
      exit 2
      ;;
    *) families+=("$arg") ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found on PATH; build.sh reads its build plan with docker/versions/build_plan.py" >&2
  exit 1
fi

# The plan is read before anything is built, so a malformed matrix or an
# unknown family fails here, with nothing half-built.
plan="$(python3 "${script_dir}/versions/build_plan.py" ${families[@]+"${families[@]}"})"

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

# build <language> <version> <parent> <build-args>: one image, from a plan
# line. <parent> is <language>:<version> or -, <build-args> space-separated
# NAME=value pairs or -.
build() {
  local lang="$1" version="$2" parent="$3" args="$4"
  local cmd=("$runtime" build) build_args=() a
  if [ "$args" != "-" ]; then
    read -r -a build_args <<<"$args"
    for a in "${build_args[@]}"; do
      cmd+=(--build-arg "$a")
    done
  fi
  if [ "$parent" != "-" ]; then
    cmd+=(--build-arg "PARENT_IMAGE=dev-${parent}")
  fi
  "${script_dir}/generate.sh" "$lang"
  if [ -n "${VRG_APT_MIRROR:-}" ] && grep -q '^ARG APT_MIRROR=' "${script_dir}/${lang}/Dockerfile"; then
    cmd+=(--build-arg "APT_MIRROR=${VRG_APT_MIRROR}")
  fi
  echo "Building dev-${lang}:${version} ..."
  "${cmd[@]}" -t "dev-${lang}:${version}" "${script_dir}/${lang}"
}

# pull_parent <language> <version>: fetch a published parent and give it the
# local tag its children are built FROM.
pull_parent() {
  local lang="$1" version="$2"
  local remote="ghcr.io/vergil-project/dev-${lang}:${version}"
  echo "Pulling ${remote} as dev-${lang}:${version} ..."
  "$runtime" pull "$remote"
  "$runtime" tag "$remote" "dev-${lang}:${version}"
}

# The build-time smoke check of each family that has one, as <family>:<dir>
# for docker/<dir>/smoke-test.sh (the family's own directory, else its
# language's). The C++ check compiles, links and runs a trivial CMake + Conan
# 2 project (spec vergil-project/.github#207); the TypeScript check installs,
# typechecks and runs one vitest test (epic vergil-project/.github#284). Both
# also confirm the shared analysis toolset. The block below is generated: edit
# docker/versions/manifest.yml and run docker/versions/generate.py, never the
# line itself.
# BEGIN generated: versions
smoke_tests="cpp-clang:cpp cpp-gcc:cpp ts-node:ts-node"
# END generated: versions

# smoke_dir <family>: the smoke-test directory of a family, or nothing.
smoke_dir() {
  local pair
  for pair in $smoke_tests; do
    if [ "${pair%%:*}" = "$1" ]; then
      echo "${pair#*:}"
      return 0
    fi
  done
}

# Build in plan order (parents first), then smoke-test what was asked for.
# The plan is read on fd 3 so that no build or pull can consume it.
smoke=()
while IFS=$'\t' read -r -u 3 role lang version parent args; do
  if [ "$role" = "parent" ] && [ "$pull_parents" -eq 1 ]; then
    pull_parent "$lang" "$version"
    continue
  fi
  build "$lang" "$version" "$parent" "$args"
  if [ "$role" = "build" ]; then
    dir="$(smoke_dir "$lang")"
    if [ -n "$dir" ]; then
      smoke+=("${dir}" "dev-${lang}:${version}")
    fi
  fi
done 3<<<"$plan"

i=0
while [ "$i" -lt "${#smoke[@]}" ]; do
  "${script_dir}/${smoke[$i]}/smoke-test.sh" "${smoke[$((i + 1))]}" "$runtime"
  i=$((i + 2))
done

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
