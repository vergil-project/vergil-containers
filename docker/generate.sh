#!/usr/bin/env bash
# generate.sh — expand Dockerfile.template files into Dockerfiles.
#
# Processes "# @include common/<fragment>.dockerfile" directives by
# replacing each include line with the contents of the referenced file.
# Includes nest: a fragment may itself include other fragments.
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

  expand "$template" 0 > "$output"
}

# expand FILE DEPTH — print FILE with every include line replaced by the
# expanded fragment. Fragments may include other fragments (for example
# common/node-markdownlint includes common/nodesource-node); the depth cap
# turns an include cycle into an error instead of unbounded recursion.
expand() {
  local file="$1" depth="$2" line fragment
  if (( depth > 8 )); then
    echo "ERROR: @include nesting too deep (cycle?) at: ${file}" >&2
    return 1
  fi
  while IFS= read -r line; do
    if [[ "$line" =~ ^#\ @include\ (.+)$ ]]; then
      fragment="${script_dir}/${BASH_REMATCH[1]}"
      if [[ ! -f "$fragment" ]]; then
        echo "ERROR: fragment not found: ${fragment}" >&2
        return 1
      fi
      expand "$fragment" $((depth + 1)) || return 1
    else
      printf '%s\n' "$line"
    fi
  done < "$file"
}

if [[ $# -eq 0 ]]; then
  langs=(python go rust java cpp-clang cpp-gcc ts-node base)
else
  langs=("$@")
fi

for lang in "${langs[@]}"; do
  generate "$lang"
done
