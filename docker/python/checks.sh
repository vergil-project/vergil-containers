#!/usr/bin/env bash
# checks.sh — the python image's build-time checks, its template's last RUN
# (epic vergil-project/.github#649, plan Task 8): base's invariants, the one
# base default the python family keeps (no node), and the family's own checks.
# The python family changes python3 and pip, so it does not rerun base's
# check_python3_is_core or check_no_pip.
#
# The family's own checks, for series <v>:
#   - the python-build-standalone runtime is at /opt/python/<v>, and python3,
#     python, python<v>, pip and pip3 in /usr/local/bin resolve into it;
#   - python3 --version (on PATH) is the series;
#   - uv, restricted to system interpreters as vergil-tooling runs it
#     (UV_PYTHON_PREFERENCE=only-system), finds the family Python for <v>, and
#     no uv-managed interpreter is installed;
#   - pytest-xdist is not in the image (consumers declare it themselves).
#
# Usage: checks.sh <series>   (as root, at image build, with base's
# checks-invariants.sh and checks-defaults.sh at /usr/local/lib/vergil/checks/,
# or in VERGIL_CHECKS_DIR)
#
# Each check function runs only through check(), by name, which shellcheck
# cannot see.
# shellcheck disable=SC2329
set -uo pipefail

dir="${VERGIL_CHECKS_DIR:-/usr/local/lib/vergil/checks}"
series="${1:-}"

py_dir="/opt/python/${series}"
py_bin="${py_dir}/bin/python${series}"
failed=()

say() {
  echo "checks-python:      $*" >&2
}

# check <name> <function>: run one check, record it if it fails.
check() {
  local name="$1"
  shift
  if "$@"; then
    echo "checks-python: ok   ${name}"
  else
    echo "checks-python: FAIL ${name}" >&2
    failed+=("${name}")
  fi
}

family_python_installed() {
  [ -x "${py_bin}" ] || {
    say "no family Python at ${py_bin}"
    return 1
  }
}

commands_link_to_family_python() {
  local rc=0 cmd want got
  for cmd in python3 python "python${series}" pip pip3; do
    case "${cmd}" in
      pip | pip3) want="${py_dir}/bin/pip${series}" ;;
      *) want="${py_bin}" ;;
    esac
    got="$(readlink -f "/usr/local/bin/${cmd}" 2>/dev/null)"
    if [ ! -e "/usr/local/bin/${cmd}" ] || [ "${got}" != "$(readlink -f "${want}")" ]; then
      say "/usr/local/bin/${cmd} resolves to '${got:-nothing}', want ${want}"
      rc=1
    fi
  done
  return "${rc}"
}

python3_is_series() {
  local got
  got="$(python3 --version 2>&1)" || {
    say "'python3 --version' failed: ${got}"
    return 1
  }
  case "${got}" in
    "Python ${series}".*) ;;
    *)
      say "'python3 --version' is '${got}', want Python ${series}.x"
      return 1
      ;;
  esac
  got="$(pip --version 2>&1)" || {
    say "'pip --version' failed: ${got}"
    return 1
  }
  case "${got}" in
    *"(python ${series})") ;;
    *)
      say "'pip --version' is '${got}', want a pip of Python ${series}"
      return 1
      ;;
  esac
}

uv_finds_family_python() {
  local got managed
  got="$(UV_PYTHON_PREFERENCE=only-system uv python find "${series}" 2>&1)" || {
    say "'UV_PYTHON_PREFERENCE=only-system uv python find ${series}' failed: ${got}"
    return 1
  }
  if [ "$(readlink -f "${got}")" != "$(readlink -f "${py_dir}/bin/python3")" ]; then
    say "uv (only-system) finds '${got}' for ${series}, want ${py_dir}/bin/python3"
    return 1
  fi
  managed="$(uv python list --only-installed --managed-python --output-format json 2>&1)" || {
    say "'uv python list --only-installed --managed-python' failed: ${managed}"
    return 1
  }
  if [ "${managed}" != "[]" ]; then
    say "uv-managed interpreters are installed: ${managed}"
    return 1
  fi
}

no_pytest_xdist() {
  if python3 -c 'import xdist' >/dev/null 2>&1; then
    say "pytest-xdist is importable from python3: the image no longer ships it"
    return 1
  fi
}

if ! [[ "${series}" =~ ^[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 <series>, such as 3.15; got '${series}'" >&2
  exit 2
fi

rc=0
"${dir}/checks-invariants.sh" || rc=1
"${dir}/checks-defaults.sh" check_no_node || rc=1

check "family Python at ${py_dir}" family_python_installed
check "python3, python, pip link to the family Python" commands_link_to_family_python
check "python3 --version is ${series}" python3_is_series
check "uv (only-system) finds the family Python" uv_finds_family_python
check "no pytest-xdist" no_pytest_xdist

if [ "${#failed[@]}" -gt 0 ]; then
  echo "checks-python: ${#failed[@]} check(s) failed:" >&2
  printf '  - %s\n' "${failed[@]}" >&2
  rc=1
else
  echo "checks-python: all checks passed"
fi
if [ "${rc}" -ne 0 ]; then
  echo "checks: python's checks failed" >&2
fi
exit "${rc}"
