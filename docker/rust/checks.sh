#!/usr/bin/env bash
# checks.sh — the rust image's build-time checks, its template's last RUN (epic
# vergil-project/.github#649, Task 10): base's invariants, all three of base's
# defaults (rust changes none of them), then the Rust toolchain itself.
#
# The toolchain checks:
#   - rustc and cargo are the pinned release (RUST_VERSION, the ENV
#     the template sets from TOOLCHAIN_VERSION), and that release is rustup's
#     default toolchain;
#   - the toolchain carries exactly today's components on the minimal profile:
#     cargo, clippy, llvm-tools, rust-std, rustc and rustfmt;
#   - cargo-deny and cargo-llvm-cov run;
#   - a new crate builds and runs with the image's C linker, and passes
#     cargo clippy.
#
# Every check runs and reports; the script exits 1 if any failed, naming each.
#
# Usage: checks.sh   (as root, at image build, with checks-invariants.sh and
# checks-defaults.sh at /usr/local/lib/vergil/checks/, or in VERGIL_CHECKS_DIR)
set -uo pipefail

dir="${VERGIL_CHECKS_DIR:-/usr/local/lib/vergil/checks}"
want="${RUST_VERSION:-}"

# The components the image has always had: the minimal profile's, plus clippy,
# rustfmt and llvm-tools.
want_components="cargo clippy llvm-tools rust-std rustc rustfmt"

failed=()

check() {
  local name="$1"
  shift
  if "$@"; then
    echo "checks-rust: ok   ${name}"
  else
    echo "checks-rust: FAIL ${name}" >&2
    failed+=("${name}")
  fi
}

say() {
  echo "checks-rust:      $*" >&2
}

toolchain_env_set() {
  [[ "${want}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    say "RUST_VERSION is '${want}', want an exact release such as 1.93.1"
    return 1
  }
}

# reports_release <command> ...: the command prints "<name> <want> (...".
reports_release() {
  local got
  got="$("$@")" || {
    say "'$*' failed"
    return 1
  }
  case "${got}" in
    *" ${want} ("* | *" ${want}") ;;
    *)
      say "'$*' is '${got}', want release ${want}"
      return 1
      ;;
  esac
}

rustc_is_pinned() {
  reports_release rustc --version
}

cargo_is_pinned() {
  reports_release cargo --version
}

default_toolchain_is_pinned() {
  local got
  got="$(rustup default)" || {
    say "'rustup default' failed"
    return 1
  }
  case "${got}" in
    "${want}-"*) ;;
    *)
      say "rustup's default toolchain is '${got}', want ${want}"
      return 1
      ;;
  esac
}

components_are_todays() {
  local got
  # Each installed component is "<name>-<target>"; keep the name.
  got="$(rustup component list --installed | sed -E 's/-(x86_64|aarch64)-unknown-linux-gnu$//' | LC_ALL=C sort | tr '\n' ' ')" || {
    say "'rustup component list --installed' failed"
    return 1
  }
  if [ "${got% }" != "${want_components}" ]; then
    say "installed components are '${got% }', want '${want_components}'"
    return 1
  fi
}

cargo_tools_run() {
  local rc=0
  cargo deny --version >/dev/null || {
    say "'cargo deny --version' failed"
    rc=1
  }
  cargo llvm-cov --version >/dev/null || {
    say "'cargo llvm-cov --version' failed"
    rc=1
  }
  return "${rc}"
}

new_crate_builds_and_passes_clippy() {
  local work rc=0 out
  work="$(mktemp -d)" || return 1
  if ! (cd "${work}" && cargo new --quiet --vcs none vergil-check); then
    say "'cargo new' failed"
    rc=1
  elif ! out="$(cd "${work}/vergil-check" && cargo run --quiet)"; then
    say "'cargo run' of a new crate failed (is the C linker installed?)"
    rc=1
  elif [ "${out}" != "Hello, world!" ]; then
    say "the new crate printed '${out}', want 'Hello, world!'"
    rc=1
  elif ! (cd "${work}/vergil-check" && cargo clippy --quiet -- -D warnings); then
    say "'cargo clippy' of a new crate failed"
    rc=1
  fi
  rm -rf "${work}"
  return "${rc}"
}

rc=0
"${dir}/checks-invariants.sh" || rc=1
"${dir}/checks-defaults.sh" check_python3_is_core check_no_node check_no_pip || rc=1

check "toolchain release set in ENV" toolchain_env_set
check "rustc is the pinned release" rustc_is_pinned
check "cargo is the pinned release" cargo_is_pinned
check "the pinned release is rustup's default" default_toolchain_is_pinned
check "components are today's" components_are_todays
check "cargo-deny and cargo-llvm-cov run" cargo_tools_run
check "a new crate builds, runs and passes clippy" new_crate_builds_and_passes_clippy

if [ "${#failed[@]}" -gt 0 ]; then
  echo "checks-rust: ${#failed[@]} check(s) failed:" >&2
  printf '  - %s\n' "${failed[@]}" >&2
  rc=1
fi
if [ "${rc}" -ne 0 ]; then
  echo "checks: rust's checks failed" >&2
  exit 1
fi
echo "checks-rust: all checks passed"
