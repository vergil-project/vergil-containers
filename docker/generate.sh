#!/usr/bin/env bash
# generate.sh — expand Dockerfile.template files into Dockerfiles.
#
# Processes "# @include common/<fragment>.dockerfile" directives by
# replacing each include line with the contents of the referenced file.
#
# Usage:
#   docker/generate.sh              # generate all
#   docker/generate.sh python base  # generate specific images
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"

generate() {
  local lang="$1"
  local template="${script_dir}/${lang}/Dockerfile.template"
  local output="${script_dir}/${lang}/Dockerfile"

  if [[ ! -f "$template" ]]; then
    echo "ERROR: template not found: ${template}" >&2
    return 1
  fi

  while IFS= read -r line; do
    if [[ "$line" =~ ^#\ @include\ (.+)$ ]]; then
      local fragment="${script_dir}/${BASH_REMATCH[1]}"
      if [[ ! -f "$fragment" ]]; then
        echo "ERROR: fragment not found: ${fragment}" >&2
        return 1
      fi
      cat "$fragment"
    else
      printf '%s\n' "$line"
    fi
  done < "$template" > "$output"
}

if [[ $# -eq 0 ]]; then
  langs=(python go rust java ruby cpp-clang base)
else
  langs=("$@")
fi

for lang in "${langs[@]}"; do
  generate "$lang"
done
