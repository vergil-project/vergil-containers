# Package Hygiene

GHCR container packages accumulate untagged version cruft indefinitely unless
something prunes it. This page explains where the cruft comes from, how to
clean up the orphaned personal-namespace packages, and how the scheduled
retention workflow keeps the org packages tidy.

## Why packages accumulate

The publish pipeline (`cd-docker-publish.yml`) runs nightly for `dev-*` images
and on every release for `prod-*` images. Each run, **per image**, pushes:

- a **multi-arch** (amd64 + arm64) manifest list, whose **two per-platform
  child manifests** appear as untagged versions;
- a **provenance attestation** manifest (`attest-build-provenance`), another
  untagged version;
- a registry build cache (`cache-to ... mode=max`) tagged `:cache-<version>` —
  each run produces a new digest, leaving the previous cache digest untagged.

Multiply by 12 packages and nightly cadence and the untagged versions pile up
without bound. None of this is referenced by a consumer-facing tag, but GHCR
keeps it forever unless told otherwise.

## Cleaning up the personal namespace (one-off)

The `dev-*`/`prod-*` packages were migrated to the `vergil-project` org and are
served from the stable `ghcr.io/vergil-project/*` URLs. Any copies left under a
personal account are orphaned and safe to delete in full.

Use [`scripts/ghcr-personal-cleanup.sh`](https://github.com/vergil-project/vergil-containers/blob/develop/scripts/ghcr-personal-cleanup.sh).
It deletes **whole packages** (every version in a single API call) rather than
forcing the per-version deletion the GHCR UI requires.

```bash
# Authenticate with a token that can delete packages in YOUR namespace:
gh auth refresh -s read:packages,delete:packages

# 1. Preview — lists every personal container package and its version count:
scripts/ghcr-personal-cleanup.sh

# 2. Delete them all (prompts for a typed DELETE confirmation):
scripts/ghcr-personal-cleanup.sh --delete
```

Run the preview first and confirm the list is only the migrated leftovers. The
script must be run by a human with their own credentials — it is deliberately
kept out of CI.

## Org retention (automated)

[`.github/workflows/package-cleanup.yml`](https://github.com/vergil-project/vergil-containers/blob/develop/.github/workflows/package-cleanup.yml)
runs weekly across all 12 org packages and prunes the untagged cruft using
[`dataaxiom/ghcr-cleanup-action`](https://github.com/dataaxiom/ghcr-cleanup-action),
which is multi-arch aware: it keeps untagged child manifests that a live tag
still references, and `validate: true` re-checks that every multi-arch tag
retains its platform children after the run.

**Policy:** untagged-only. Tagged versions — `latest`, the language-version
tags, and the `cache-*` tags — are never deleted.

## Datestamp-alias retention (sliding window)

Alongside the untagged prune, the same
[`package-cleanup.yml`](https://github.com/vergil-project/vergil-containers/blob/develop/.github/workflows/package-cleanup.yml)
workflow runs a second job, `reap-aliases`, added in
[#419](https://github.com/vergil-project/vergil-containers/issues/419).

Every build publishes an **immutable datestamp alias** at the same digest as the
rolling tag — `{prefix}-{lang}:{version}-YYYYMMDD` (and
`{prefix}-base:latest-YYYYMMDD`). These aliases are what
[Image Rollback (Repoint)](rollback.md) repoints to when a bad float ships, so
they must be retained long enough to recover from — but not forever, or they
accumulate without bound.

The reaper enforces a **sliding retention window**: it deletes only the
`*-YYYYMMDD` aliases once they age past the window, keeping recent builds
addressable while old ones stop piling up.

- **prod aliases: 30 days** — the consumer rollback and bisection range.
- **dev aliases: 7 days** — the churning canary needs a shorter tail.

The window is chosen for recovery, not storage: a successful build is not proven
good until a downstream consumer exercises it, which can lag by days, so
rollback needs a *window* of history to bisect through — not just the previous
build. This is the recovery path's retention SLA: **you can only repoint to an
alias still inside the window.**

The reaper deletes **only** tags matching `…-YYYYMMDD` (an 8-digit datestamp as
the whole trailing segment). Rolling tags (`latest`, `3.14`, `1.26`, `17`,
`21`), `cache-*` tags, and pre-promotion `*-candidate` tags carry no such suffix
and are explicitly excluded — they are never reaped by this job. Untagged
pruning remains the `cleanup` job's remit.

### Arming it

The workflow ships in **dry-run by default** so the first runs only log what
they *would* delete:

- **Preview on demand:** Actions → *Package cleanup* → *Run workflow* (leave
  "Preview only" checked). Review the logs.
- **Delete on demand (one-off):** the same manual run with "Preview only"
  **unchecked** performs a real deletion for that run only, without changing the
  schedule.
- **Arm scheduled deletions:** once satisfied, set the repository variable
  `PACKAGE_CLEANUP_DRY_RUN` to `false` (Settings → Secrets and variables →
  Actions → Variables). The weekly run then deletes for real. No code change is
  needed to arm or disarm.

### Token

The default `GITHUB_TOKEN` can list and preview. If real deletion of org-owned
package versions fails with a permissions error, provision a PAT with
`delete:packages` and store it as the secret `GHCR_CLEANUP_TOKEN` — the
workflow prefers it when present and falls back to `GITHUB_TOKEN` otherwise.
