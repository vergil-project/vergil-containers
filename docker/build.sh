#!/usr/bin/env bash
# Managed by vergil-docker — DO NOT EDIT in downstream repos.
# Canonical source: https://github.com/vergil-project/vergil-docker
# build.sh — build all dev container images with default version tags.
#
# Each image is defined by a Dockerfile.template that may contain
# "# @include common/<fragment>.dockerfile" lines.  generate.sh
# expands these includes to produce the final Dockerfile before
# each build.
#
# After a successful build, dangling images and stale build cache
# (>30 days) are pruned to prevent local disk bloat.  Tagged images
# and volumes are never touched.
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"

build() {
  local lang="$1" version_arg="$2" version_val="$3"
  "${script_dir}/generate.sh" "$lang"
  echo "Building dev-${lang}:${version_val} ..."
  docker build \
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

"${script_dir}/generate.sh" base
echo "Building dev-base:latest ..."
docker build -t "dev-base:latest" "${script_dir}/base"

echo "All images built successfully."

echo "Pruning dangling images and stale build cache ..."
docker image prune -f
docker builder prune -af --filter 'until=720h'
