#!/usr/bin/env bash
# run-in-container.sh — the in-image half of the TypeScript smoke check.
#
# Runs inside a built dev-ts-node image with the smoke fixture mounted read-only
# at /smoke. Copies the fixture to a writable dir, then:
#   1. confirms the shared runtime-agnostic analysis toolset (tsc, eslint,
#      prettier, vitest, license-checker, @vitest/coverage-v8, typescript-eslint)
#      is present and runnable — so every ts-node image is verified to carry it;
#   2. installs the fixture's vendored devDependencies with `npm ci`;
#   3. typechecks with `tsc --noEmit`;
#   4. runs one Vitest test.
# Any failure exits non-zero.
set -euo pipefail

work="$(mktemp -d)"
cp -R /smoke/. "${work}/"
cd "${work}"

echo "--- node runtime ---"
echo "node: $(node --version)"
echo "npm:  $(npm --version)"

echo "--- shared TypeScript analysis toolset (global) ---"
# Every ts-node image carries the same analysis tools
# (common/typescript-analysis.dockerfile); confirm each is present on PATH.
for tool in tsc eslint prettier vitest license-checker; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "SMOKE FAIL: analysis tool '${tool}' not found on PATH" >&2
    exit 1
  fi
done
echo "tsc:             $(tsc --version)"
echo "eslint:          $(eslint --version)"
echo "prettier:        $(prettier --version)"
echo "vitest:          $(vitest --version)"
echo "license-checker: $(command -v license-checker)"

# Library packages have no bin; assert they are installed in the global tree.
for lib in "@vitest/coverage-v8" typescript-eslint; do
  if ! npm ls -g "${lib}" >/dev/null 2>&1; then
    echo "SMOKE FAIL: '${lib}' not installed globally" >&2
    exit 1
  fi
  echo "${lib}: present (global)"
done

echo "--- npm ci (vendored devDependencies) ---"
npm ci

echo "--- tsc --noEmit (typecheck) ---"
npx tsc --noEmit

echo "--- vitest run (one test) ---"
npx vitest run

echo "SMOKE PASS"
