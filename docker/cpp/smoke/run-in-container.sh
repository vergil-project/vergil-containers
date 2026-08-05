#!/usr/bin/env bash
# run-in-container.sh — the in-image half of the C++ smoke check.
#
# Runs inside a built dev-cpp-* image with the smoke fixture mounted read-only
# at /smoke. Copies the fixture to a writable dir, resolves the fmt dependency
# with Conan 2, configures + builds with CMake against the image's default
# compiler, runs the binary, and asserts its output. It also confirms the shared
# compiler-agnostic analysis toolset is present and runnable — so every C++
# image (both the Clang and GCC families) is verified to carry it. Any failure
# exits non-zero.
set -euo pipefail

work="$(mktemp -d)"
mkdir -p "${work}/src"
cp /smoke/conanfile.txt /smoke/CMakeLists.txt "${work}/"
cp /smoke/src/main.cpp "${work}/src/"
cd "${work}"

echo "--- compiler ---"
echo "CC=${CC:-<unset>} CXX=${CXX:-<unset>}"
"${CXX:-c++}" --version | head -1

echo "--- analysis toolset (shared, compiler-agnostic) ---"
# Every C++ image carries the same analysis tools (common/cpp-analysis.dockerfile);
# confirm each is present on PATH and runnable regardless of compiler family.
for tool in clang-format clang-tidy cppcheck gcovr osv-scanner; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "SMOKE FAIL: analysis tool '${tool}' not found on PATH" >&2
    exit 1
  fi
  echo -n "${tool}: "
  "${tool}" --version | head -1
done

# run-clang-tidy is a driver script with no --version flag; the LINT command
# invokes the unversioned name, so assert it merely resolves on PATH (issue #487).
if ! command -v run-clang-tidy >/dev/null 2>&1; then
  echo "SMOKE FAIL: 'run-clang-tidy' not found on PATH" >&2
  exit 1
fi
echo "run-clang-tidy: $(command -v run-clang-tidy)"

echo "--- gcov (coverage front-end) ---"
# gcov must resolve in both families (issue #487): GCC images ship a native gcov,
# Clang images ship a shim that dispatches to `llvm-cov gcov`. Assert presence in
# both, and in the Clang family assert the shim actually reaches llvm-cov so the
# compiler-agnostic coverage command needs no compiler dimension.
if ! command -v gcov >/dev/null 2>&1; then
  echo "SMOKE FAIL: 'gcov' not found on PATH" >&2
  exit 1
fi
gcov --version | head -1
if [[ "${CXX:-}" == clang* ]]; then
  if ! gcov --version 2>&1 | grep -qi llvm; then
    echo "SMOKE FAIL: Clang-image gcov did not dispatch to llvm-cov" >&2
    exit 1
  fi
  echo "gcov -> llvm-cov confirmed (Clang family)"
fi

echo "--- conan install (cold: uses the image's baked default profile) ---"
# No `conan profile detect` here on purpose: the image bakes a default profile at
# build time (issue #487), so a cold `conan install` must resolve without one.
conan install . --output-folder=build --build=missing -s compiler.cppstd=20

echo "--- cmake configure + build ---"
cmake -S . -B build \
  -DCMAKE_TOOLCHAIN_FILE="${work}/build/conan_toolchain.cmake" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build

echo "--- run ---"
output="$(./build/cpp_smoke)"
echo "program output: ${output}"

expected="cpp smoke ok: 42"
if [[ "${output}" != "${expected}" ]]; then
  echo "SMOKE FAIL: expected '${expected}', got '${output}'" >&2
  exit 1
fi
echo "SMOKE PASS"
