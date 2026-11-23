#!/usr/bin/env bash
# run-in-container.sh — the in-image half of the TypeScript smoke check.
#
# Runs inside a built dev-ts-node image with the smoke fixture mounted read-only
# at /smoke. Copies the fixture to a writable dir, then:
#   1. confirms the image tool (prettier) is on PATH and runs;
#   2. confirms the repo-declared tools (tsc, eslint, vitest) are NOT on PATH,
#      and typescript-eslint and @vitest/coverage-v8 are not in the global tree:
#      a repo declares them and runs its own (vergil-tooling's tool-ownership
#      guideline, epic vergil-project/.github#1174 §6.3);
#   3. installs the fixture's declared devDependencies with
#      `npm ci --ignore-scripts`, as every Vergil gate does;
#   4. fails if tsc, eslint or vitest is missing from node_modules/.bin;
#   5. typechecks (tsc --noEmit), lints (eslint .) and runs one Vitest test
#      with V8 coverage, each from node_modules/.bin;
#   6. runs the image tool on the project: prettier --check.
# Any failure exits non-zero.
set -euo pipefail

work="$(mktemp -d)"
cp -R /smoke/. "${work}/"
cd "${work}"

echo "--- node runtime ---"
echo "node: $(node --version)"
echo "npm:  $(npm --version)"

echo "--- image tools (global) ---"
if ! command -v prettier >/dev/null 2>&1; then
  echo "SMOKE FAIL: image tool 'prettier' not found on PATH" >&2
  exit 1
fi
echo "prettier: $(prettier --version)"

echo "--- repo-declared tools (must not be global) ---"
for tool in tsc eslint vitest; do
  if entry="$(command -v "${tool}")"; then
    echo "SMOKE FAIL: '${tool}' is on the image's PATH (${entry}); the repo declares it" >&2
    exit 1
  fi
  echo "${tool}: not on PATH"
done
for lib in typescript-eslint "@vitest/coverage-v8"; do
  if npm ls -g "${lib}" >/dev/null 2>&1; then
    echo "SMOKE FAIL: '${lib}' is installed globally; the repo declares it" >&2
    exit 1
  fi
  echo "${lib}: not installed globally"
done

echo "--- npm ci --ignore-scripts (declared devDependencies) ---"
npm ci --ignore-scripts

bin="${work}/node_modules/.bin"
for tool in tsc eslint vitest; do
  if [ ! -x "${bin}/${tool}" ]; then
    echo "SMOKE FAIL: '${tool}' not installed at node_modules/.bin/${tool}" >&2
    exit 1
  fi
done
echo "tsc:    $("${bin}/tsc" --version)"
echo "eslint: $("${bin}/eslint" --version)"
echo "vitest: $("${bin}/vitest" --version)"

echo "--- tsc --noEmit (typecheck) ---"
"${bin}/tsc" --noEmit

echo "--- eslint . (lint) ---"
"${bin}/eslint" .

echo "--- vitest run --coverage (one test) ---"
"${bin}/vitest" run --coverage

echo "--- prettier --check (image tool) ---"
prettier --check src

echo "SMOKE PASS"
