#!/usr/bin/env bash
# checks-invariants.sh — the build-time checks every image built on base keeps
# (epic vergil-project/.github#649, spec §5.2 and §5.2.1). base copies it to
# /usr/local/lib/vergil/checks/, so base and every language image built on it
# run the same file unchanged as part of their last RUN.
#
# It reads the core series from base's ENV (VERGIL_CORE_PYTHON,
# VERGIL_CORE_NODE_MAJOR), never from a build arg: a build ARG does not carry
# into a child image. Every check runs and reports, then the script exits 1 if
# any failed, naming each.
#
# The checks:
#   - no package toolchain marker; /etc/os-release is Ubuntu 24.04;
#   - the core Python is the core series and imports tomllib;
#   - /usr/local/bin/python3 exists and imports tomllib (the standard library
#     is all it promises, spec §5.5);
#   - each core tool runs, mike --help, a material-themed fixture builds, and
#     markdownlint runs;
#   - a real semgrep scan passes through both entry points, semgrep and
#     pysemgrep: one inline rule against one file, exit 0 and one finding
#     (vergil-project/vergil-containers#825: `semgrep --version` passed while
#     every scan crashed);
#   - each core tool runs on its core runtime: every uv tool environment's
#     interpreter is under /opt/vergil/python/<core>/ (for a wrapped entry
#     point, the one it execs), and the markdownlint wrapper names
#     /opt/vergil/node/<core-major>/bin/node;
#   - the vergil apt source is in place, no bootstrap source or key is left,
#     and apt-get update passes.
#
# Usage: checks-invariants.sh   (as root, at image build)
set -uo pipefail

core_python="${VERGIL_CORE_PYTHON:-}"
core_node_major="${VERGIL_CORE_NODE_MAJOR:-}"
core_python_dir="/opt/vergil/python/${core_python}"
core_python_bin="${core_python_dir}/bin/python${core_python}"
core_node_bin="/opt/vergil/node/${core_node_major}/bin/node"

# The uv tools base installs, by the entry point each puts in /usr/local/bin.
# semgrep and pysemgrep are wrappers that exec their entry points in the tool
# environment (common/core-tools.dockerfile); the rest are uv's links.
uv_tools=(yamllint ansible-lint semgrep pysemgrep mkdocs mike)

failed=()

# check <name> <function>: run one check, record it if it fails.
check() {
  local name="$1"
  shift
  if "$@"; then
    echo "checks-invariants: ok   ${name}"
  else
    echo "checks-invariants: FAIL ${name}" >&2
    failed+=("${name}")
  fi
}

say() {
  echo "checks-invariants:      $*" >&2
}

core_env_set() {
  local rc=0
  [[ "${core_python}" =~ ^[0-9]+\.[0-9]+$ ]] || {
    say "VERGIL_CORE_PYTHON is '${core_python}', want a series such as 3.15"
    rc=1
  }
  [[ "${core_node_major}" =~ ^[0-9]+$ ]] || {
    say "VERGIL_CORE_NODE_MAJOR is '${core_node_major}', want a major such as 22"
    rc=1
  }
  return "${rc}"
}

no_package_toolchain_marker() {
  [ ! -e /etc/vergil/package-toolchain ] || {
    say "/etc/vergil/package-toolchain exists: base removes it in its first layer"
    return 1
  }
}

os_is_ubuntu_2404() {
  if ! grep -qx 'ID=ubuntu' /etc/os-release || ! grep -qx 'VERSION_ID="24.04"' /etc/os-release; then
    say "/etc/os-release is $(grep -E '^(ID|VERSION_ID)=' /etc/os-release | tr '\n' ' '), want ID=ubuntu VERSION_ID=\"24.04\""
    return 1
  fi
}

# python_series <interpreter>: its X.Y.
python_series() {
  "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])'
}

core_python_is_core_series() {
  local got
  [ -x "${core_python_bin}" ] || {
    say "no core Python at ${core_python_bin}"
    return 1
  }
  got="$(python_series "${core_python_bin}")" || return 1
  [ "${got}" = "${core_python}" ] || {
    say "${core_python_bin} is Python ${got}, want ${core_python}"
    return 1
  }
  "${core_python_bin}" -c 'import tomllib' || {
    say "${core_python_bin} cannot import tomllib"
    return 1
  }
}

python3_imports_tomllib() {
  [ -x /usr/local/bin/python3 ] || {
    say "no /usr/local/bin/python3"
    return 1
  }
  /usr/local/bin/python3 -c 'import tomllib' || {
    say "/usr/local/bin/python3 cannot import tomllib"
    return 1
  }
}

core_tools_run() {
  local rc=0 tool
  for tool in yamllint ansible-lint semgrep mkdocs markdownlint; do
    "${tool}" --version >/dev/null || {
      say "'${tool} --version' failed"
      rc=1
    }
  done
  mike --help >/dev/null || {
    say "'mike --help' failed"
    rc=1
  }
  # ansible-lint warns that the setup is broken when its environment's bin is
  # not on PATH, unless the environment is under a uv/tools directory.
  if ansible-lint --version 2>&1 | grep -q 'PATH altered'; then
    say "ansible-lint warns that PATH was altered: its environment is not under a uv/tools directory"
    rc=1
  fi
  return "${rc}"
}

material_fixture_builds() {
  local dir rc=0
  dir="$(mktemp -d)" || return 1
  mkdir -p "${dir}/docs"
  printf '%s\n' 'site_name: vergil base check' 'theme:' '  name: material' \
    'markdown_extensions:' '  - admonition' '  - pymdownx.superfences' >"${dir}/mkdocs.yml"
  printf '%s\n' '# Fixture' '' '!!! note' '    A material-themed page.' >"${dir}/docs/index.md"
  if ! (cd "${dir}" && NO_MKDOCS_2_WARNING=1 mkdocs build --quiet --strict --site-dir "${dir}/site"); then
    say "mkdocs build of the material fixture failed"
    rc=1
  elif ! grep -q 'md-header' "${dir}/site/index.html"; then
    say "the fixture's index.html is not material-themed (no md-header)"
    rc=1
  fi
  rm -rf "${dir}"
  return "${rc}"
}

# semgrep_scan_finds: one inline rule (`echo $X`, bash) against one `echo hi`
# file, run through each semgrep entry point with no metrics, no version check
# and no network rule pack, must exit 0 with exactly one finding.
semgrep_scan_finds() {
  local dir rc=0 tool status got
  dir="$(mktemp -d)" || return 1
  mkdir -p "${dir}/src"
  # SC2016: the rule's $X is semgrep's metavariable, written literally.
  # shellcheck disable=SC2016
  printf '%s\n' 'rules:' '  - id: vergil-check-echo' '    pattern: echo $X' \
    '    message: an echo' '    languages: [bash]' '    severity: INFO' >"${dir}/rule.yml"
  printf '%s\n' '#!/bin/sh' 'echo hi' >"${dir}/src/hello.sh"
  for tool in semgrep pysemgrep; do
    status=0
    "${tool}" scan --metrics=off --disable-version-check --config "${dir}/rule.yml" \
      --json --output "${dir}/${tool}.json" "${dir}/src" >"${dir}/${tool}.log" 2>&1 || status=$?
    if [ "${status}" -ne 0 ]; then
      say "'${tool} scan' of the fixture exited ${status}; its last lines:"
      tail -n 5 "${dir}/${tool}.log" | sed 's/^/    /' >&2
      rc=1
      continue
    fi
    got="$(jq '.results | length' "${dir}/${tool}.json")" || {
      say "'${tool} scan' wrote no readable JSON to ${dir}/${tool}.json"
      rc=1
      continue
    }
    [ "${got}" = 1 ] || {
      say "'${tool} scan' of the fixture found ${got} result(s), want 1"
      rc=1
    }
  done
  rm -rf "${dir}"
  return "${rc}"
}

# entry_target <entry>: the file an entry point runs: what a wrapper's exec
# line names, else what the link resolves to.
entry_target() {
  local target
  target="$(sed -n 's/^exec \([^ ]*\) .*/\1/p' "$1")"
  readlink -f "${target:-$1}"
}

uv_tools_on_core_python() {
  local rc=0 tool entry real cfg home
  for tool in "${uv_tools[@]}"; do
    entry="$(command -v "${tool}")" || {
      say "${tool} is not on PATH"
      rc=1
      continue
    }
    [ "${entry}" = "/usr/local/bin/${tool}" ] || {
      say "${tool} resolves to ${entry}, want /usr/local/bin/${tool}"
      rc=1
      continue
    }
    real="$(entry_target "${entry}")"
    cfg="$(dirname "$(dirname "${real}")")/pyvenv.cfg"
    home="$(sed -n 's/^home *= *//p' "${cfg}" 2>/dev/null)"
    case "${home}" in
      "${core_python_dir}"/*) ;;
      *)
        say "${tool} (${real}) runs on '${home:-no pyvenv.cfg at ${cfg}}', want ${core_python_dir}/"
        rc=1
        ;;
    esac
  done
  return "${rc}"
}

markdownlint_on_core_node() {
  local got
  if ! grep -q "^exec ${core_node_bin} " /usr/local/bin/markdownlint 2>/dev/null; then
    say "/usr/local/bin/markdownlint does not run ${core_node_bin}"
    return 1
  fi
  got="$("${core_node_bin}" --version)" || return 1
  case "${got}" in
    "v${core_node_major}".*) ;;
    *)
      say "${core_node_bin} is ${got}, want Node ${core_node_major}"
      return 1
      ;;
  esac
}

vergil_apt_source_clean() {
  local rc=0 path
  [ -e /etc/apt/sources.list.d/vergil.sources ] || {
    say "no /etc/apt/sources.list.d/vergil.sources"
    rc=1
  }
  for path in /etc/apt/sources.list.d/vergil-bootstrap.sources /etc/apt/keyrings/vergil-bootstrap.asc; do
    [ ! -e "${path}" ] || {
      say "${path} is left from the bootstrap"
      rc=1
    }
  done
  return "${rc}"
}

apt_update_passes() {
  local rc=0
  apt-get update >/dev/null || {
    say "apt-get update failed"
    rc=1
  }
  rm -rf /var/lib/apt/lists/*
  return "${rc}"
}

check "core series set in ENV" core_env_set
check "no package toolchain marker" no_package_toolchain_marker
check "Ubuntu 24.04" os_is_ubuntu_2404
check "core Python is the core series" core_python_is_core_series
check "/usr/local/bin/python3 imports tomllib" python3_imports_tomllib
check "core tools run" core_tools_run
check "material fixture builds" material_fixture_builds
check "semgrep scan finds the fixture's one result" semgrep_scan_finds
check "uv tools run on the core Python" uv_tools_on_core_python
check "markdownlint runs on the core Node" markdownlint_on_core_node
check "vergil apt source, no bootstrap left" vergil_apt_source_clean
check "apt-get update passes" apt_update_passes

if [ "${#failed[@]}" -gt 0 ]; then
  echo "checks-invariants: ${#failed[@]} check(s) failed:" >&2
  printf '  - %s\n' "${failed[@]}" >&2
  exit 1
fi
echo "checks-invariants: all checks passed"
