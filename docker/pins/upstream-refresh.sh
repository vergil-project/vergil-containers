#!/usr/bin/env bash
# upstream-refresh.sh — the [upstream-refresh].hook for vergil-containers.
#
# vrg-upstream-refresh runs this from the repo root on a fresh clone of
# develop, in the prepare job, which holds no secrets (vergil.toml points at
# it; epics vergil-project/.github#472 and vergil-project/.github#1168).
# It moves the auto-managed binary-download tools to their leading edge, and
# each language toolchain pin to the newest patch of its series:
#
#   1. resolve_latest.py --write rewrites the `ARG *_VERSION=` pins in
#      docker/common/* to each tool's newest release (#435), and, for a tool
#      whose digests are pinned in source (cargo-nextest, cargo-deny), its
#      `ARG *_SHA256_<ARCH>=` lines to that release's checksums, all or
#      nothing (epic vergil-project/.github#1165); and the workflow image
#      pins in docker/pins/workflow-images.txt to theirs, refusing with an
#      error any that would change the major version (#914);
#   2. resolve_toolchains.py --write rewrites docker/pins/toolchains.yml to the
#      newest patch of each series, with both architectures' hashes (epic
#      vergil-project/.github#649);
#   3. generate.py regenerates docker/versions/matrix.json, whose build args
#      carry the toolchain pins (PR CI's `generate.py --check` fails on a
#      stale matrix);
#   4. generate_catalog.py regenerates docker/pins/CATALOG.md to match.
#
# It only edits tracked files. It never commits, pushes or opens a PR, and it
# writes no notes: vrg-upstream-refresh owns the branch, commit and PR. Any
# failure (an unresolvable tool included) exits non-zero, so nothing is pushed.
#
# Usage: docker/pins/upstream-refresh.sh
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${repo_root}"

python3 docker/pins/resolve_latest.py --write
uv run docker/pins/resolve_toolchains.py --write
uv run docker/versions/generate.py
uv run docker/pins/generate_catalog.py
