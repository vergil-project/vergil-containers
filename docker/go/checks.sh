#!/usr/bin/env bash
# checks.sh — the go image's build-time checks, its template's last RUN (epic
# vergil-project/.github#649, Task 9): base's invariants, all three of base's
# defaults (go changes none of python3, node or pip), then the Go toolchain.
#
# The Go checks:
#   - `go version` is the pinned release, go<TOOLCHAIN_VERSION> for this arch;
#   - GOROOT is /usr/local/go, GOPATH is /go and GOTOOLCHAIN is local, so the
#     toolchain never downloads another Go (the env the golang images set);
#   - cgo is on, with a C compiler, and a `go run` of a cgo program works with
#     the image's own toolchain;
#   - each Go tool the image installs is on PATH and runs.
#
# Usage: checks.sh <TOOLCHAIN_VERSION>   (as root, at image build, with
# checks-invariants.sh and checks-defaults.sh at /usr/local/lib/vergil/checks/,
# or in VERGIL_CHECKS_DIR)
set -uo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "usage: $0 <TOOLCHAIN_VERSION>" >&2
  exit 2
fi
want_version="$1"

dir="${VERGIL_CHECKS_DIR:-/usr/local/lib/vergil/checks}"
failed=()

say() {
  echo "checks-go:      $*" >&2
}

# report <name> <status>: report one check by its exit status, record it if it
# failed.
report() {
  if [ "$2" -eq 0 ]; then
    echo "checks-go: ok   $1"
  else
    echo "checks-go: FAIL $1" >&2
    failed+=("$1")
  fi
}

go_version() {
  local got want
  case "$(uname -m)" in
    x86_64) want="go version go${want_version} linux/amd64" ;;
    aarch64) want="go version go${want_version} linux/arm64" ;;
    *)
      say "unsupported machine '$(uname -m)'"
      return 1
      ;;
  esac
  got="$(go version 2>&1)" || {
    say "go version failed: ${got}"
    return 1
  }
  if [ "${got}" != "${want}" ]; then
    say "go version is '${got}', want '${want}'"
    return 1
  fi
}

# go_env <variable> <want>: `go env <variable>` is <want>.
go_env() {
  local got
  got="$(go env "$1" 2>&1)" || {
    say "go env $1 failed: ${got}"
    return 1
  }
  if [ "${got}" != "$2" ]; then
    say "go env $1 is '${got}', want '$2'"
    return 1
  fi
}

go_layout() {
  local rc=0
  go_env GOROOT /usr/local/go || rc=1
  go_env GOPATH /go || rc=1
  go_env GOTOOLCHAIN local || rc=1
  go_env CGO_ENABLED 1 || rc=1
  return "${rc}"
}

go_run_cgo() {
  local work out rc=0
  work="$(mktemp -d)" || return 1
  printf 'module example.com/check\n\ngo %s\n' "${want_version%.*}" >"${work}/go.mod"
  printf '%s\n' 'package main' '' '// #include <stdlib.h>' 'import "C"' '' \
    'import "fmt"' '' 'func main() { fmt.Println("cgo", C.abs(-7)) }' >"${work}/main.go"
  if ! out="$(cd "${work}" && GOCACHE="${work}/cache" go run . 2>&1)"; then
    say "go run of a cgo program failed: ${out}"
    rc=1
  elif [ "${out}" != "cgo 7" ]; then
    say "go run of a cgo program printed '${out}', want 'cgo 7'"
    rc=1
  fi
  rm -rf "${work}"
  return "${rc}"
}

# tool_runs <want-exit> <tool> <flag>: <tool> is on PATH and `<tool> <flag>`
# exits <want-exit>. gocyclo and goimports have no version flag and print their
# usage with exit 2 on -h, so for them 2 is the expected exit.
tool_runs() {
  local want="$1" tool="$2" flag="$3" out got
  if ! command -v "${tool}" >/dev/null 2>&1; then
    say "${tool} is not on PATH"
    return 1
  fi
  out="$("${tool}" "${flag}" 2>&1)"
  got="$?"
  if [ "${got}" -ne "${want}" ]; then
    say "${tool} ${flag} exited ${got}, want ${want}: ${out}"
    return 1
  fi
}

# The tools the template installs.
go_tools() {
  local rc=0
  tool_runs 0 golangci-lint --version || rc=1
  tool_runs 0 govulncheck -version || rc=1
  tool_runs 0 go-licenses --help || rc=1
  tool_runs 2 gocyclo -h || rc=1
  tool_runs 2 goimports -h || rc=1
  tool_runs 0 go-test-coverage --version || rc=1
  return "${rc}"
}

rc=0
"${dir}/checks-invariants.sh" || rc=1
"${dir}/checks-defaults.sh" check_python3_is_core check_no_node check_no_pip || rc=1

go_version
report go_version "$?"
go_layout
report go_layout "$?"
go_run_cgo
report go_run_cgo "$?"
go_tools
report go_tools "$?"

if [ "${#failed[@]}" -gt 0 ]; then
  echo "checks-go: ${#failed[@]} check(s) failed:" >&2
  printf '  - %s\n' "${failed[@]}" >&2
  rc=1
else
  echo "checks-go: all Go checks passed"
fi
if [ "${rc}" -ne 0 ]; then
  echo "checks: go's checks failed" >&2
fi
exit "${rc}"
