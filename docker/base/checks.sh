#!/usr/bin/env bash
# checks.sh — base's build-time checks, its template's last RUN (epic
# vergil-project/.github#649): every invariant, then every one of base's
# defaults. A language image runs its own checks.sh instead, which reruns the
# invariants and only the defaults it keeps.
#
# Usage: checks.sh   (as root, at image build, with checks-invariants.sh and
# checks-defaults.sh at /usr/local/lib/vergil/checks/, or in VERGIL_CHECKS_DIR)
set -uo pipefail

dir="${VERGIL_CHECKS_DIR:-/usr/local/lib/vergil/checks}"
rc=0
"${dir}/checks-invariants.sh" || rc=1
"${dir}/checks-defaults.sh" check_python3_is_core check_no_node check_no_pip || rc=1
if [ "${rc}" -ne 0 ]; then
  echo "checks: base's checks failed" >&2
fi
exit "${rc}"
