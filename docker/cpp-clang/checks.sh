#!/usr/bin/env bash
# checks.sh — cpp-clang's build-time checks, its template's last RUN (epic
# vergil-project/.github#649, plan Task 11): base's invariants, all three of
# base's defaults (cpp-clang changes none of them), then the family's own:
#   - clang-<v> is LLVM <v>, from apt.llvm.org's noble suite;
#   - Clang builds against GCC 14's libstdc++ (g++-14 installed; with only
#     noble's unversioned g++, 13, it would select 13);
#   - clang-format-<t> and clang-tidy-<t> are the tools major <t>;
#   - cmake and cppcheck are noble's own: cmake 3.28.3, cppcheck 2.13.0.
#
# Every check runs and reports; the script exits 1 if any failed, and 2 on bad
# usage.
#
# Usage: checks.sh <clang-version> <clang-tools-version>   (as root, at image
# build, with base's checks at /usr/local/lib/vergil/checks/, or in
# VERGIL_CHECKS_DIR)
#
# Each check function runs through check(), by name, which shellcheck cannot
# follow, so it reports them (and the helpers only they call) as never invoked.
# shellcheck disable=SC2329
set -uo pipefail

clang_version="${1:-}"
tools_version="${2:-}"

# The libstdc++ series Clang must select, and noble's cmake and cppcheck.
gcc_series=14
cmake_version=3.28.3
cppcheck_version=2.13.0

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
  local out
  out="$("$@" 2>&1)" || {
    say "'$*' failed: ${out}"
    return 1
  }
  printf '%s\n' "${out%%$'\n'*}"
}

# llvm_major <tool> <major>: '<tool> --version' reports LLVM <major>.x.
llvm_major() {
  local tool="$1" major="$2" out
  out="$("${tool}" --version 2>&1)" || {
    say "'${tool} --version' failed: ${out}"
    return 1
  }
  if ! grep -Eq "version ${major}\.[0-9]+\.[0-9]+" <<<"${out}"; then
    say "'${tool} --version' is not LLVM ${major}: $(head -n 2 <<<"${out}" | tr '\n' ' ')"
    return 1
  fi
}

clang_is_the_series() {
  local rc=0
  llvm_major "clang-${clang_version}" "${clang_version}" || rc=1
  # The unversioned names CMake, Conan and gcovr resolve are this series.
  llvm_major clang "${clang_version}" || rc=1
  llvm_major clang++ "${clang_version}" || rc=1
  return "${rc}"
}

clang_selects_gcc_libstdcxx() {
  local out selected
  out="$("clang++-${clang_version}" -v -E -x c++ /dev/null -o /dev/null 2>&1)" || {
    say "'clang++-${clang_version} -v' failed: ${out}"
    return 1
  }
  selected="$(sed -n 's/^Selected GCC installation: //p' <<<"${out}")"
  case "${selected}" in
    */gcc/*-linux-gnu/"${gcc_series}") ;;
    *)
      say "clang++-${clang_version} selects GCC installation '${selected:-none}', want .../gcc/<triple>/${gcc_series}"
      return 1
      ;;
  esac
}

clang_tools_are_the_tools_major() {
  local rc=0
  llvm_major "clang-format-${tools_version}" "${tools_version}" || rc=1
  llvm_major "clang-tidy-${tools_version}" "${tools_version}" || rc=1
  return "${rc}"
}

cmake_is_noble() {
  local got
  got="$(first_line cmake --version)" || return 1
  [ "${got}" = "cmake version ${cmake_version}" ] || {
    say "cmake is '${got}', want 'cmake version ${cmake_version}' (noble's)"
    return 1
  }
}

cppcheck_is_noble() {
  local got
  got="$(first_line cppcheck --version)" || return 1
  [ "${got}" = "Cppcheck ${cppcheck_version}" ] || {
    say "cppcheck is '${got}', want 'Cppcheck ${cppcheck_version}' (noble's)"
    return 1
  }
}

if [ "$#" -ne 2 ] || ! [[ "${clang_version}" =~ ^[0-9]+$ ]] || ! [[ "${tools_version}" =~ ^[0-9]+$ ]]; then
  echo "usage: $0 <clang-version> <clang-tools-version> (two LLVM majors, such as 20 20)" >&2
  exit 2
fi

rc=0
"${dir}/checks-invariants.sh" || rc=1
"${dir}/checks-defaults.sh" check_python3_is_core check_no_node check_no_pip || rc=1

check "clang-${clang_version} is LLVM ${clang_version}" clang_is_the_series
check "Clang selects GCC ${gcc_series}'s libstdc++" clang_selects_gcc_libstdcxx
check "clang-format and clang-tidy are LLVM ${tools_version}" clang_tools_are_the_tools_major
check "cmake ${cmake_version}" cmake_is_noble
check "cppcheck ${cppcheck_version}" cppcheck_is_noble

if [ "${#failed[@]}" -gt 0 ]; then
  echo "checks: ${#failed[@]} cpp-clang check(s) failed:" >&2
  printf '  - %s\n' "${failed[@]}" >&2
  rc=1
fi
if [ "${rc}" -ne 0 ]; then
  echo "checks: cpp-clang's checks failed" >&2
else
  echo "checks: all cpp-clang checks passed"
fi
exit "${rc}"
