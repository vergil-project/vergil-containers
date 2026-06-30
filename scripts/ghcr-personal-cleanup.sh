#!/usr/bin/env bash
# One-off cleanup of stale personal-namespace GHCR container packages.
#
# Context: the dev-*/prod-* container images were migrated to the
# vergil-project org and are served from ghcr.io/vergil-project/* (stable
# URLs). The copies still sitting under the personal account are orphaned.
# This deletes WHOLE packages — every version at once — rather than the
# painful version-by-version deletion the GHCR UI forces on you.
#
# This is intentionally NOT run by CI or the agent: it must run with a HUMAN
# token that carries delete:packages, against the human's own namespace.
#
#   gh auth refresh -s read:packages,delete:packages
#
# Usage:
#   scripts/ghcr-personal-cleanup.sh                # dry run: list packages + version counts
#   scripts/ghcr-personal-cleanup.sh --only dev-    # restrict to names matching a substring
#   scripts/ghcr-personal-cleanup.sh --delete       # delete every listed package, in full
#
# Safety: dry run is the default; --delete additionally requires typing DELETE.
set -euo pipefail

DELETE=false
FILTER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --delete) DELETE=true ;;
    --only)   FILTER="${2:-}"; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

command -v gh >/dev/null || { echo "gh CLI not found" >&2; exit 1; }

echo "Enumerating container packages for the authenticated user..."
mapfile -t PKGS < <(
  gh api --paginate '/user/packages?package_type=container' --jq '.[].name' \
    | { if [ -n "$FILTER" ]; then grep -- "$FILTER"; else cat; fi; }
)

if [ "${#PKGS[@]}" -eq 0 ]; then
  echo "No matching container packages found."
  exit 0
fi

printf '\n%-32s %s\n' "PACKAGE" "VERSIONS"
printf '%-32s %s\n'   "-------" "--------"
for pkg in "${PKGS[@]}"; do
  enc=${pkg//\//%2F}
  count=$(gh api --paginate "/user/packages/container/${enc}/versions" --jq 'length' \
            2>/dev/null | awk '{s+=$1} END{print s+0}')
  printf '%-32s %s\n' "$pkg" "$count"
done

echo
if [ "$DELETE" != true ]; then
  echo "DRY RUN — nothing deleted."
  echo "Re-run with --delete to remove these ${#PKGS[@]} package(s) entirely."
  exit 0
fi

echo "About to DELETE ${#PKGS[@]} package(s) IN FULL (all versions). This is irreversible."
read -r -p "Type 'DELETE' to proceed: " confirm
[ "$confirm" = "DELETE" ] || { echo "Aborted."; exit 1; }

for pkg in "${PKGS[@]}"; do
  enc=${pkg//\//%2F}
  echo "Deleting package: $pkg"
  gh api --method DELETE "/user/packages/container/${enc}"
done
echo "Done. Deleted ${#PKGS[@]} package(s)."
