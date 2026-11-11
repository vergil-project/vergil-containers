#!/usr/bin/env bash
# checks.sh — the ts-node image's build-time checks, its template's last RUN
# (epic vergil-project/.github#649, plan Task 13): base's invariants, the two
# base defaults ts-node keeps (python3 is the core Python, no pip), and the
# family's own checks. ts-node changes one default, node, so check_no_node is
# not rerun.
#
# The family checks:
#   - node on PATH is /usr/local/bin/node, the nodejs.org Node unpacked at
#     /opt/node/<NODE_MAJOR>, and is release TOOLCHAIN_VERSION of that major;
#   - npm and npx on PATH are that Node's;
#   - npm's global prefix is /usr, so `npm root -g` is /usr/lib/node_modules
#     (spec §5.3, §5.5);
#   - markdownlint on PATH is still base's wrapper, which runs on the core Node
#     at /opt/vergil/node/<core-major>, never on the family's;
#   - the TypeScript analysis tools run on the family's Node.
#
# Usage: checks.sh   (as root, at image build, with NODE_MAJOR and
# TOOLCHAIN_VERSION set, as the template's build args are, and base's
# checks-invariants.sh and checks-defaults.sh at /usr/local/lib/vergil/checks/,
# or in VERGIL_CHECKS_DIR)
set -uo pipefail

dir="${VERGIL_CHECKS_DIR:-/usr/local/lib/vergil/checks}"
major="${NODE_MAJOR:-}"
version="${TOOLCHAIN_VERSION:-}"
node_dir="/opt/node/${major}"

failed=()

# report <status> <name>: record one check's result, from its exit status.
report() {
  if [ "$1" -eq 0 ]; then
    echo "checks-ts-node: ok   $2"
  else
    echo "checks-ts-node: FAIL $2" >&2
    failed+=("$2")
  fi
}

say() {
  echo "checks-ts-node:      $*" >&2
}

build_args_set() {
  local rc=0
  [[ "${major}" =~ ^[0-9]+$ ]] || {
    say "NODE_MAJOR is '${major}', want a major such as 24"
    rc=1
  }
  [[ "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    say "TOOLCHAIN_VERSION is '${version}', want a release such as 24.11.1"
    rc=1
  }
  return "${rc}"
}

# on_path <command> <want>: the command resolves to /usr/local/bin/<command>,
# a link to <want>.
on_path() {
  local cmd="$1" want="$2" entry
  entry="$(command -v "${cmd}")" || {
    say "${cmd} is not on PATH"
    return 1
  }
  [ "${entry}" = "/usr/local/bin/${cmd}" ] || {
    say "${cmd} resolves to ${entry}, want /usr/local/bin/${cmd}"
    return 1
  }
  [ "$(readlink -f "${entry}")" = "$(readlink -f "${want}")" ] || {
    say "/usr/local/bin/${cmd} resolves to $(readlink -f "${entry}"), want ${want}"
    return 1
  }
}

node_is_the_pinned_release() {
  local got
  on_path node "${node_dir}/bin/node" || return 1
  got="$(node --version)" || return 1
  [ "${got}" = "v${version}" ] || {
    say "node is ${got}, want v${version}"
    return 1
  }
  case "${version}" in
    "${major}".*) ;;
    *)
      say "TOOLCHAIN_VERSION ${version} is not a release of Node ${major}"
      return 1
      ;;
  esac
}

npm_and_npx_are_the_family_nodes() {
  local rc=0
  on_path npm "${node_dir}/bin/npm" || rc=1
  on_path npx "${node_dir}/bin/npx" || rc=1
  npm --version >/dev/null || {
    say "'npm --version' failed"
    rc=1
  }
  npx --version >/dev/null || {
    say "'npx --version' failed"
    rc=1
  }
  return "${rc}"
}

npm_global_prefix_is_usr() {
  local rc=0 got
  got="$(npm prefix -g)" || return 1
  [ "${got}" = /usr ] || {
    say "npm prefix -g is '${got}', want /usr"
    rc=1
  }
  got="$(npm root -g)" || return 1
  [ "${got}" = /usr/lib/node_modules ] || {
    say "npm root -g is '${got}', want /usr/lib/node_modules"
    rc=1
  }
  return "${rc}"
}

markdownlint_is_the_core_wrapper() {
  local entry
  entry="$(command -v markdownlint)" || {
    say "markdownlint is not on PATH"
    return 1
  }
  [ "${entry}" = /usr/local/bin/markdownlint ] || {
    say "markdownlint resolves to ${entry}, want base's wrapper /usr/local/bin/markdownlint"
    return 1
  }
  if grep -q "${node_dir}/" "${entry}"; then
    say "${entry} names the family Node ${node_dir}"
    return 1
  fi
  markdownlint --version >/dev/null || {
    say "'markdownlint --version' failed"
    return 1
  }
}

typescript_tools_run() {
  local rc=0 tool
  for tool in tsc eslint prettier vitest; do
    "${tool}" --version >/dev/null || {
      say "'${tool} --version' failed"
      rc=1
    }
  done
  return "${rc}"
}

rc=0
"${dir}/checks-invariants.sh" || rc=1
"${dir}/checks-defaults.sh" check_python3_is_core check_no_pip || rc=1

build_args_set
report "$?" "NODE_MAJOR and TOOLCHAIN_VERSION set"
node_is_the_pinned_release
report "$?" "node is the pinned release at ${node_dir}"
npm_and_npx_are_the_family_nodes
report "$?" "npm and npx are the family Node's"
npm_global_prefix_is_usr
report "$?" "npm's global prefix is /usr"
markdownlint_is_the_core_wrapper
report "$?" "markdownlint is base's wrapper on the core Node"
typescript_tools_run
report "$?" "the TypeScript analysis tools run"

if [ "${#failed[@]}" -gt 0 ]; then
  echo "checks-ts-node: ${#failed[@]} check(s) failed:" >&2
  printf '  - %s\n' "${failed[@]}" >&2
  rc=1
else
  echo "checks-ts-node: all family checks passed"
fi
if [ "${rc}" -ne 0 ]; then
  echo "checks: ts-node's checks failed" >&2
fi
exit "${rc}"
