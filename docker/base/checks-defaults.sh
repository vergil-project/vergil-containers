#!/usr/bin/env bash
# checks-defaults.sh — base's defaults, one check each (epic
# vergil-project/.github#649, spec §5.2 and §5.2.1). base copies it to
# /usr/local/lib/vergil/checks/ beside checks-invariants.sh. A language image
# may change a default (only python changes python3 and pip, only ts-node
# changes node), so it reruns, by name, each check whose default it keeps:
#
#   checks-defaults.sh check_no_node                      # python
#   checks-defaults.sh check_python3_is_core check_no_pip # ts-node
#
# The checks:
#   check_python3_is_core  /usr/local/bin/python3 is the core Python
#                          (VERGIL_CORE_PYTHON's series, the uv-managed one
#                          under VERGIL_CORE_PYTHON_DIR)
#   check_no_node          no node, npm or npx on PATH
#   check_no_pip           no pip or pip3 on PATH
#
# Each named check runs and reports; the script exits 1 if any failed, and 2 on
# no check or an unknown one.
#
# Usage: checks-defaults.sh <check> [<check> ...]
set -uo pipefail

checks=(check_python3_is_core check_no_node check_no_pip)

say() {
  echo "checks-defaults:      $*" >&2
}

check_python3_is_core() {
  local core_python="${VERGIL_CORE_PYTHON:-}" dir="${VERGIL_CORE_PYTHON_DIR:-}" want got
  if ! [[ "${core_python}" =~ ^[0-9]+\.[0-9]+$ ]]; then
    say "VERGIL_CORE_PYTHON is '${core_python}', want a series such as 3.15"
    return 1
  fi
  if ! [[ "${dir}" == /* ]]; then
    say "VERGIL_CORE_PYTHON_DIR is '${dir}', want an absolute path"
    return 1
  fi
  # The core Python as the vergil-tooling installs find it: uv-managed, under
  # VERGIL_CORE_PYTHON_DIR, with no download.
  want="$(env -u UV_PYTHON -u UV_PYTHON_PREFERENCE -u UV_NO_MANAGED_PYTHON \
    UV_PYTHON_INSTALL_DIR="${dir}" UV_PYTHON_DOWNLOADS=never \
    uv python find --no-config --managed-python "${core_python}")" || {
    say "uv finds no managed Python ${core_python} in ${dir}"
    return 1
  }
  got="$(readlink -f /usr/local/bin/python3)"
  if [ "${got}" != "$(readlink -f "${want}")" ]; then
    say "/usr/local/bin/python3 resolves to '${got}', want ${want}"
    return 1
  fi
  got="$(/usr/local/bin/python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')" || return 1
  if [ "${got}" != "${core_python}" ]; then
    say "/usr/local/bin/python3 is Python ${got}, want ${core_python}"
    return 1
  fi
}

# absent <command> ...: none of the commands is on PATH.
absent() {
  local rc=0 cmd
  for cmd in "$@"; do
    if command -v "${cmd}" >/dev/null 2>&1; then
      say "${cmd} is on PATH at $(command -v "${cmd}")"
      rc=1
    fi
  done
  return "${rc}"
}

check_no_node() {
  absent node npm npx
}

check_no_pip() {
  absent pip pip3
}

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <check> [<check> ...]; checks: ${checks[*]}" >&2
  exit 2
fi
for name in "$@"; do
  case " ${checks[*]} " in
    *" ${name} "*) ;;
    *)
      echo "checks-defaults: unknown check '${name}'; checks: ${checks[*]}" >&2
      exit 2
      ;;
  esac
done

failed=()
for name in "$@"; do
  if "${name}"; then
    echo "checks-defaults: ok   ${name}"
  else
    echo "checks-defaults: FAIL ${name}" >&2
    failed+=("${name}")
  fi
done
if [ "${#failed[@]}" -gt 0 ]; then
  echo "checks-defaults: ${#failed[@]} check(s) failed:" >&2
  printf '  - %s\n' "${failed[@]}" >&2
  exit 1
fi
echo "checks-defaults: all checks passed"
