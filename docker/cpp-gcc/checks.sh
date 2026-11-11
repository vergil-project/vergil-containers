#!/usr/bin/env bash
# checks.sh — cpp-gcc's build-time checks, its template's last RUN (epic
# vergil-project/.github#649, plan Task 12): base's invariants, every one of
# base's defaults (cpp-gcc changes none of python3, node or pip), then the
# family's own checks:
#   - gcc-<v> and g++-<v> are a released <v>.x (never a pre-release
#     snapshot), and the unversioned gcc, g++ and gcov are that major;
#   - g++ builds against libstdc++ <v>, GCC <v>'s own;
#   - clang-format-<t> and clang-tidy-<t> are LLVM <t>, and the unversioned
#     clang-format, clang-tidy and run-clang-tidy resolve to them;
#   - cmake and cppcheck are noble's (spike item 6: Kitware's channel is not
#     needed).
#
# Usage: checks.sh <gcc-major> <clang-tools-major>   (as root, at image build,
# with checks-invariants.sh and checks-defaults.sh at
# /usr/local/lib/vergil/checks/, or in VERGIL_CHECKS_DIR)
set -uo pipefail

# noble's cmake and cppcheck, which the C++ images use (spike item 6).
CMAKE_VERSION="3.28.3"
CPPCHECK_VERSION="2.13.0"

if [ "$#" -ne 2 ] || ! [[ "$1" =~ ^[0-9]+$ ]] || ! [[ "$2" =~ ^[0-9]+$ ]]; then
  echo "usage: $0 <gcc-major> <clang-tools-major>" >&2
  exit 2
fi
gcc_major="$1"
tools_major="$2"
dir="${VERGIL_CHECKS_DIR:-/usr/local/lib/vergil/checks}"

failed=()

# check <name> <function> [<arg> ...]: run one check, record it if it fails.
check() {
  local name="$1"
  shift
  if "$@"; then
    echo "checks: ok   ${name}"
  else
    echo "checks: FAIL ${name}" >&2
    failed+=("${name}")
  fi
}

say() {
  echo "checks:      $*" >&2
}

# first_line <command> ...: the first line of the command's --version output.
first_line() {
  "$@" --version 2>/dev/null | head -n 1
}

# gcc_is_release <compiler>: <compiler> --version names a released
# <gcc_major>.<minor>.<patch>, the last field of its first line. A
# pre-release snapshot ends its first line otherwise (such as
# "14.0.1 20240412 (experimental) ...").
gcc_is_release() {
  local line
  line="$(first_line "$1")"
  if ! [[ "${line}" =~ \ ${gcc_major}\.[0-9]+\.[0-9]+$ ]]; then
    say "'$1 --version' is '${line}', want a released ${gcc_major}.x"
    return 1
  fi
}

gcc_released() {
  local rc=0
  gcc_is_release "gcc-${gcc_major}" || rc=1
  gcc_is_release "g++-${gcc_major}" || rc=1
  return "${rc}"
}

# The unversioned names CMake, Conan and gcovr use, and CC/CXX, are that major.
unversioned_is_major() {
  local rc=0 tool real
  for tool in gcc g++ gcov; do
    real="$(readlink -f "$(command -v "${tool}")")"
    if [ "${real}" != "$(readlink -f "/usr/bin/${tool}-${gcc_major}")" ]; then
      say "${tool} resolves to '${real}', want ${tool}-${gcc_major}"
      rc=1
    fi
  done
  if [ "${CC:-}" != gcc ] || [ "${CXX:-}" != g++ ]; then
    say "CC is '${CC:-}' and CXX is '${CXX:-}', want gcc and g++"
    rc=1
  fi
  return "${rc}"
}

libstdcxx_is_major() {
  local got
  got="$(g++ -print-file-name=libstdc++.so)"
  case "${got}" in
    /usr/lib/gcc/*/"${gcc_major}"/libstdc++.so) ;;
    *)
      say "g++ links libstdc++ from '${got}', want /usr/lib/gcc/<triplet>/${gcc_major}/"
      return 1
      ;;
  esac
}

# llvm_tool <name>: <name>-<t> reports LLVM <t>, and the unversioned <name>
# resolves to it.
llvm_tool() {
  local tool="$1" line real rc=0
  line="$(first_line "${tool}-${tools_major}")"
  if ! [[ "${line}" =~ version\ ${tools_major}\.[0-9]+\.[0-9]+ ]]; then
    say "'${tool}-${tools_major} --version' is '${line}', want LLVM ${tools_major}"
    rc=1
  fi
  real="$(readlink -f "$(command -v "${tool}")")"
  if [ "${real}" != "$(readlink -f "/usr/bin/${tool}-${tools_major}")" ]; then
    say "${tool} resolves to '${real}', want ${tool}-${tools_major}"
    rc=1
  fi
  return "${rc}"
}

clang_tools_major() {
  local rc=0 real
  llvm_tool clang-format || rc=1
  llvm_tool clang-tidy || rc=1
  real="$(readlink -f "$(command -v run-clang-tidy)")"
  if [ "${real}" != "$(readlink -f "/usr/bin/run-clang-tidy-${tools_major}")" ]; then
    say "run-clang-tidy resolves to '${real}', want run-clang-tidy-${tools_major}"
    rc=1
  fi
  return "${rc}"
}

cmake_is_noble() {
  local line
  line="$(first_line cmake)"
  if [ "${line}" != "cmake version ${CMAKE_VERSION}" ]; then
    say "'cmake --version' is '${line}', want cmake version ${CMAKE_VERSION}"
    return 1
  fi
}

cppcheck_is_noble() {
  local line
  line="$(first_line cppcheck)"
  if [ "${line}" != "Cppcheck ${CPPCHECK_VERSION}" ]; then
    say "'cppcheck --version' is '${line}', want Cppcheck ${CPPCHECK_VERSION}"
    return 1
  fi
}

check "base's invariants" "${dir}/checks-invariants.sh"
check "base's defaults" "${dir}/checks-defaults.sh" check_python3_is_core check_no_node check_no_pip
check "gcc-${gcc_major} and g++-${gcc_major} are a released ${gcc_major}.x" gcc_released
check "gcc, g++, gcov, CC and CXX are GCC ${gcc_major}" unversioned_is_major
check "g++ builds against libstdc++ ${gcc_major}" libstdcxx_is_major
check "clang-format, clang-tidy and run-clang-tidy are LLVM ${tools_major}" clang_tools_major
check "cmake ${CMAKE_VERSION}" cmake_is_noble
check "cppcheck ${CPPCHECK_VERSION}" cppcheck_is_noble

if [ "${#failed[@]}" -gt 0 ]; then
  echo "checks: ${#failed[@]} check(s) failed:" >&2
  printf '  - %s\n' "${failed[@]}" >&2
  exit 1
fi
echo "checks: all checks passed"
