#!/usr/bin/env bash
#
# Behavioural tests for the publish pipeline's Trivy scripts (issue #721):
#   scripts/bin/trivy-image-scan — the arm64 scan, with retry;
#   scripts/bin/trivy-gate       — the publish gate.
#
# Self-contained and framework-free, like the vergil-actions *.test.sh
# harnesses: run it with `bash scripts/tests/trivy.test.sh`.
# scripts/bin/validate-custom runs it, so PR CI does too.
#
# The scan cases put a stub `docker` first on PATH. It plays one scripted
# outcome per call, read from a plan file:
#   clean    — writes the report and exits 0;
#   findings — writes the report and exits 1 (trivy convert --exit-code 1);
#   error    — writes no report and exits 1 (Trivy stopped before reporting,
#              e.g. a dropped layer or DB download).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
scan="${here}/../bin/trivy-image-scan"
gate="${here}/../bin/trivy-gate"

pass=0
fail=0

fail_case() {
  printf 'not ok - %s: %s\n' "$1" "$2" >&2
  fail=$((fail + 1))
}

pass_case() {
  printf 'ok - %s\n' "$1"
  pass=$((pass + 1))
}

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

# check <name> <want-rc> <want-text> [<absent-text>] — asserts on rc and out.
check() {
  local name="$1" want_rc="$2" want_text="$3" absent="${4:-}"
  if [ "${rc}" -ne "${want_rc}" ]; then
    fail_case "${name}" "expected exit ${want_rc}, got ${rc}; output: ${out}"
    return 1
  fi
  if [ -n "${want_text}" ] && ! printf '%s' "${out}" | grep -qF -- "${want_text}"; then
    fail_case "${name}" "missing '${want_text}'; output: ${out}"
    return 1
  fi
  if [ -n "${absent}" ] && printf '%s' "${out}" | grep -qF -- "${absent}"; then
    fail_case "${name}" "unexpected '${absent}'; output: ${out}"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# trivy-image-scan
# ---------------------------------------------------------------------------

# run_scan <dir> <attempts> <plan...> — sets rc, out, result, calls.
run_scan() {
  local dir="$1" tries="$2"
  shift 2
  mkdir -p "${dir}/bin" "${dir}/ws"
  : >"${dir}/calls"
  : >"${dir}/gh-output"
  printf '%s\n' "$@" >"${dir}/plan"
  cat >"${dir}/bin/docker" <<EOF
#!/usr/bin/env bash
n=\$(( \$(wc -l <'${dir}/calls') + 1 ))
# One line per call: the sh -c script argument spans several lines.
printf '%s\n' "\$*" | tr '\n' ' ' >>'${dir}/calls'
echo >>'${dir}/calls'
outcome=\$(sed -n "\${n}p" '${dir}/plan')
report="\${GITHUB_WORKSPACE}/\${REPORT_FILE}"
case "\${outcome}" in
  clean) printf '{"runs":[]}\n' >"\${report}"; exit 0 ;;
  findings) printf '{"runs":[{"results":[1]}]}\n' >"\${report}"; exit 1 ;;
  error) echo "FATAL stream error: PROTOCOL_ERROR" >&2; exit 1 ;;
  *) echo "docker stub: no planned outcome for call \${n}" >&2; exit 99 ;;
esac
EOF
  chmod +x "${dir}/bin/docker"

  set +e
  out="$(PATH="${dir}/bin:${PATH}" \
    GITHUB_WORKSPACE="${dir}/ws" GITHUB_OUTPUT="${dir}/gh-output" \
    TRIVY_IMAGE=trivy:test TRIVY_SCAN_ATTEMPTS="${tries}" TRIVY_SCAN_RETRY_DELAY=0 \
    bash "${scan}" example/image:tag linux/arm64 trivy-arm64.sarif 2>&1)"
  rc=$?
  set -e
  result="$(sed -n 's/^result=//p' "${dir}/gh-output")"
  calls="$(wc -l <"${dir}/calls" | tr -d ' ')"
}

# expect_scan <name> <want-rc> <want-result> <want-calls> <want-text> [<absent>]
expect_scan() {
  local name="$1" want_rc="$2" want_result="$3" want_calls="$4"
  check "${name}" "${want_rc}" "$5" "${6:-}" || return 0
  if [ "${result}" != "${want_result}" ]; then
    fail_case "${name}" "expected result=${want_result}, got '${result}'; output: ${out}"
    return 0
  fi
  if [ "${calls}" -ne "${want_calls}" ]; then
    fail_case "${name}" "expected ${want_calls} scan attempt(s), got ${calls}; output: ${out}"
    return 0
  fi
  pass_case "${name}"
}

run_scan "${tmp}/clean" 3 clean
expect_scan scan-clean-passes 0 passed 1 ""

run_scan "${tmp}/findings" 3 findings
expect_scan scan-findings-fail-without-retry 1 findings 1 \
  "Trivy found CRITICAL/HIGH vulnerabilities in example/image:tag (linux/arm64)" \
  "scan errored"

run_scan "${tmp}/error" 3 error error error
expect_scan scan-error-retried-then-fails 1 error 3 \
  "Trivy scan errored (no report produced) for example/image:tag (linux/arm64) after 3 attempts" \
  "vulnerabilities in"

run_scan "${tmp}/recover" 3 error clean
expect_scan scan-transient-error-recovers 0 passed 2 "attempt 1/3"

mkdir -p "${tmp}/stale/ws"
printf '{"runs":[]}\n' >"${tmp}/stale/ws/trivy-arm64.sarif"
run_scan "${tmp}/stale" 2 error error
expect_scan scan-stale-report-ignored 1 error 2 "scan errored (no report produced)"

# The scan targets the requested platform and mounts the checkout at
# /workspace, where Trivy picks up trivy.yaml.
run_scan "${tmp}/args" 1 clean
# The literal $PLATFORM is the in-container expansion being checked for.
# shellcheck disable=SC2016
if grep -q -- "-e PLATFORM" "${tmp}/args/calls" &&
  grep -q -- '--platform "$PLATFORM"' "${tmp}/args/calls" &&
  grep -q -- "-w /workspace" "${tmp}/args/calls"; then
  pass_case scan-docker-invocation
else
  fail_case scan-docker-invocation "unexpected invocation: $(cat "${tmp}/args/calls")"
fi

# ---------------------------------------------------------------------------
# trivy-gate
# ---------------------------------------------------------------------------

ws="${tmp}/gate"
mkdir -p "${ws}"
printf '{}\n' >"${ws}/amd64.sarif"
printf '{}\n' >"${ws}/arm64.sarif"
missing="${ws}/missing.sarif"

# run_gate <args...> — sets rc and out.
run_gate() {
  set +e
  out="$(bash "${gate}" img:cand "$@" 2>&1)"
  rc=$?
  set -e
}

run_gate amd64 success passed "${ws}/amd64.sarif" arm64 success passed "${ws}/arm64.sarif"
check gate-clean-passes 0 "Trivy gate passed for img:cand (arm64)" "::error::" &&
  pass_case gate-clean-passes

# The run 40349047526 case: amd64 crashed with no report, arm64 was clean.
run_gate amd64 failure "" "${missing}" arm64 success "" "${ws}/arm64.sarif"
check gate-no-report-is-scan-error 1 \
  "Trivy scan errored (no report produced) for img:cand (amd64)" \
  "vulnerabilities in" && pass_case gate-no-report-is-scan-error

run_gate amd64 failure error "${missing}" arm64 success passed "${ws}/arm64.sarif"
check gate-result-error-is-scan-error 1 "scan errored (no report produced)" \
  "vulnerabilities in" && pass_case gate-result-error-is-scan-error

run_gate amd64 success passed "${ws}/amd64.sarif" arm64 failure findings "${ws}/arm64.sarif"
check gate-findings-fail 1 "Trivy found CRITICAL/HIGH vulnerabilities in img:cand (arm64)" \
  "scan errored" && pass_case gate-findings-fail

# An older shared action sets no result: a failed step that wrote a report
# finished its scan, so it found something.
run_gate amd64 failure "" "${ws}/amd64.sarif" arm64 success passed "${ws}/arm64.sarif"
check gate-legacy-failure-with-report-is-findings 1 \
  "vulnerabilities in img:cand (amd64)" "scan errored" &&
  pass_case gate-legacy-failure-with-report-is-findings

# A scan step that "succeeded" without a report never passes.
run_gate amd64 success "" "${missing}" arm64 success passed "${ws}/arm64.sarif"
check gate-success-without-report-fails 1 "scan errored (no report produced)" &&
  pass_case gate-success-without-report-fails

# A clean scan whose step failed later (e.g. the SARIF upload) still fails, but
# not as findings.
run_gate amd64 failure passed "${ws}/amd64.sarif" arm64 success passed "${ws}/arm64.sarif"
check gate-passed-scan-failed-step 1 "did not succeed (outcome 'failure', result 'passed')" \
  "vulnerabilities in" && pass_case gate-passed-scan-failed-step

# Both platforms are reported, not just the first failure.
run_gate amd64 failure "" "${missing}" arm64 failure findings "${ws}/arm64.sarif"
check gate-reports-every-platform 1 "vulnerabilities in img:cand (arm64)" &&
  check gate-reports-every-platform 1 "scan errored (no report produced) for img:cand (amd64)" &&
  pass_case gate-reports-every-platform

run_gate amd64 success passed
check gate-bad-usage 2 "usage: trivy-gate" && pass_case gate-bad-usage

printf '\n%d passed, %d failed\n' "${pass}" "${fail}"
[ "${fail}" -eq 0 ]
