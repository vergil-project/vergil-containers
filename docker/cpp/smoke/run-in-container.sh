#!/usr/bin/env bash
# run-in-container.sh — the in-image half of the C++ smoke check.
#
# Runs inside a built dev-cpp-* image with the smoke fixture mounted read-only
# at /smoke. Copies the fixture to a writable dir, resolves the fmt dependency
# with Conan 2, configures + builds with CMake against the image's default
# compiler, runs the binary, and asserts its output. Any failure exits non-zero.
set -euo pipefail

work="$(mktemp -d)"
mkdir -p "${work}/src"
cp /smoke/conanfile.txt /smoke/CMakeLists.txt "${work}/"
cp /smoke/src/main.cpp "${work}/src/"
cd "${work}"

echo "--- compiler ---"
echo "CC=${CC:-<unset>} CXX=${CXX:-<unset>}"
"${CXX:-c++}" --version | head -1

echo "--- conan install (resolves + builds deps) ---"
conan profile detect --force
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
