# Package Hygiene

GHCR container packages accumulate untagged version cruft indefinitely unless
something prunes it. This page explains where the cruft comes from, how to
clean up the orphaned personal-namespace packages, and how the scheduled
retention workflow keeps the org packages tidy.

## Why packages accumulate

The publish pipeline (`cd-docker-publish.yml`) runs on every `develop` push for
`dev-*` images, on every release for `prod-*` images, and nightly (`ops.yml`)
for both. Each run, **per image**, pushes:

- a **multi-arch** (amd64 + arm64) manifest list, whose **two per-platform
  child manifests** appear as untagged versions;
- a **provenance attestation** manifest (`attest-build-provenance`), another
  untagged version;
- a registry build cache (`cache-to ... mode=max`) per architecture, tagged
  `:cache-<version>-<arch>` — each run produces a new digest, leaving the
  previous cache digest untagged.

Each architecture's image is pushed by digest, untagged, and is only tagged
(through the stitched multi-arch candidate) once every build in the run has
finished. The `cleanup` job therefore prunes only untagged versions older than
24 hours, so it never reaps a digest a publish in flight is about to stitch.
The shared `:cache-<version>` tags from before the per-arch builds are no
longer written; they can be deleted by hand.

Multiply by every package (each image under both prefixes) and nightly
cadence and the untagged versions pile up without bound. None of this is
referenced by a consumer-facing tag, but GHCR keeps it forever unless told
otherwise.

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

### Running it

Both jobs delete for real
([#912](https://github.com/vergil-project/vergil-containers/issues/912)). A
preview is the explicit exception:

- **Scheduled run:** every Sunday the workflow deletes for real. No repository
  variable arms or disarms it; the workflow file in git is the whole record of
  what it does.
- **Delete on demand:** Actions → *Package cleanup* → *Run workflow* with the
  default inputs ("Preview only" unchecked) deletes for real, as the schedule
  does.
- **Preview on demand:** the same manual run with "Preview only" **checked**
  (the `dry_run` input set to `true`) only logs what it *would* delete. Use it
  before a change to the delete rules, and review the logs.

A third job, `verify-deletes`, checks that the deletes happened (see
[Delete check](#delete-check)). A fourth, `report`, reports the run to the
org's operations queue (epic
[vergil-project/.github#1494](https://github.com/vergil-project/.github/issues/1494))
under the name `package-cleanup`, taking the three jobs as one result: any
failed leg, or a failed delete check, makes the run a failure. Neither of
these two jobs deletes anything. A failure opens, or comments on, the issue
`ops: vergil-containers / package-cleanup failing`, and the first green run
after it records the recovery. `package-cache-warm.yml` reports the same way,
as `package-cache-warm`. Only runs on `develop` report.

### Delete check

The action treats a 404 on a version delete as success: it logs *"wasn't
found while trying to delete it; treating as already deleted"* and goes on.
GHCR answers 404 when the token may not delete the package, so a leg whose
every delete failed used to end green: in run
[45635208056](https://github.com/vergil-project/vergil-containers/actions/runs/45635208056)
every delete failed that way
([#1051](https://github.com/vergil-project/vergil-containers/issues/1051)).

The action has no outputs that count its deletes, and a step cannot read its
own job's log while the job runs. So the `verify-deletes` job runs once every
leg has finished, failed legs included. It downloads each leg's log through the
Actions API and runs `docker/versions/cleanup_verify.py`, which fails the job,
with an error naming the leg and the package, when:

- every delete the leg set out to make was answered "not found": the token
  could not delete; or
- a version answered "not found" is still among the package's active versions:
  that delete did not happen either.

A version answered "not found" that is really gone was deleted by something
else between the action's listing and its delete, such as an overlapping run
(see [Job ordering](#job-ordering)), and passes. A preview makes no deletes,
so it always passes. The job retries a transient API failure with a back-off;
one that persists fails the check.

### Rate limits

Every leg of both jobs fetches every manifest of its package from ghcr.io. On a
cold manifest cache that is tens of thousands of registry requests per run, and
with every leg started at once ghcr.io answered HTTP 429
([#652](https://github.com/vergil-project/vergil-containers/issues/652)). The
action already retries each request a few times, but only for about a second.
The workflow adds two defences:

- **Capped fan-out:** `max-parallel: 3` on each job, and the jobs run one after
  the other (see below), so at most 3 legs hit the registry together.
- **One retry per leg:** if the action fails, the leg waits a bounded, jittered
  back-off (`RETRY_BACKOFF_BASE_SECONDS` plus up to
  `RETRY_BACKOFF_JITTER_SECONDS`), logs a warning, and runs the action once
  more with the same inputs. If that also fails, the leg fails with an error
  that names the package and says how to read a 429 or a 404. Nothing is
  skipped.

`docker/versions/test_package_cleanup.py` pins this structure. If 429s persist,
lower `max-parallel` first.

### Job ordering

`reap-aliases` starts only once every `cleanup` leg has finished, so the two
jobs never work on the same package at the same time. When they overlapped, a
reap leg loaded a package's manifests while the cleanup leg was deleting that
package's untagged versions, and failed with HTTP 404 on a manifest that had
just gone
([#911](https://github.com/vergil-project/vergil-containers/issues/911)).
GitHub cannot make one matrix leg wait for the matching leg of another job, so
the whole job waits. It runs even when a cleanup leg failed, since reaping
aliases does not depend on the prune.

A 404 in a leg's log is therefore not a rate limit: it means something else
deleted versions of the same package while the action read it, such as an
overlapping manual run.

### Manifest cache

The action keeps a cache of the manifests it has fetched, in the repository's
Actions cache, one entry per package per run. A run that finds an entry fetches
only the manifests it has not seen. GitHub evicts an entry that nobody has used
for 7 days, and the weekly cleanup often starts a few hours later than its
schedule, so the gap between runs can pass 7 days. The 2026-11-01 run started
with no cache for any package and fetched 37,500 manifests
([#700](https://github.com/vergil-project/vergil-containers/issues/700)).

[`package-cache-warm.yml`](https://github.com/vergil-project/vergil-containers/blob/develop/.github/workflows/package-cache-warm.yml)
prevents this. Every Wednesday it restores each package's newest cache entry.
A restore counts as a use, so the entry survives until Sunday's cleanup. The
restore downloads from the GitHub cache service and sends no requests to
ghcr.io.

If a package has no entry at all, the leg logs a *Manifest cache cold* warning
and rebuilds the cache with a preview-only run of the action that selects
nothing for deletion, as the org automation App (see [Token](#token)). It then
checks the entry exists and fails if it does not.
That failure means the workflow's cache path or key no longer matches what the
action writes, which can happen when the action is upgraded. The workflow
copies the action's cache scheme, so the two workflows must pin the same action
version; `docker/versions/test_package_cache_warm.py` enforces it.

To check that the cache is warm, read a cleanup leg's log: the line
`manifest cache: N/M digests served from cache (P%)` should show more than 0%.

### Token

The `cleanup` and `reap-aliases` jobs make every GHCR call with the
workflow's own `GITHUB_TOKEN`, with `packages: write` and no other
permission, and `verify-deletes` lists a package's versions with it, with
`packages: read`. It is an identity exception to the rule that unattended jobs
run as the org automation App (epic
[vergil-project/.github#1494](https://github.com/vergil-project/.github/issues/1494)):
GitHub Packages refuses App installation tokens for deletes and untags, though
the App can list and read packages, and `GITHUB_TOKEN` is the
[documented token](https://docs.github.com/en/packages/learn-github-packages/about-permissions-for-github-packages)
for a workflow repository's own packages. The cleanup ran as the App once, in
run
[45635208056](https://github.com/vergil-project/vergil-containers/actions/runs/45635208056):
every delete came back "wasn't found" and the one untag came back 403, so
nothing was deleted
([#1050](https://github.com/vergil-project/vergil-containers/issues/1050)).
Run
[45056026741](https://github.com/vergil-project/vergil-containers/actions/runs/45056026741)
deleted 10,400 versions with `GITHUB_TOKEN`, none of them answered "wasn't
found"
([#1054](https://github.com/vergil-project/vergil-containers/issues/1054)).

No personal access token is used, and nothing falls back to another token.
`GITHUB_TOKEN` is always present, so the legs read no environment secret and declare no
environment; only the `report` job declares the `automation` environment, to
read the App's keys. The token reaches a package only while the package grants
this repository access (see
[Architecture](../architecture/index.md#ghcr-package-access-grants)). A
package that does not answers its deletes 404, which the action logs as
"wasn't found", and `verify-deletes` then fails the run.

A cache-warm leg that has to rebuild its cache runs as the App: it mints an
App token with `packages: read`, and fails if the token cannot be minted or
comes back empty. That works because the rebuild only reads: it is a preview
that never deletes or untags. The GHCR proof
([vergil-project/.github#1516](https://github.com/vergil-project/.github/issues/1516))
showed that the App can read these packages through the Packages API. It cannot
push images through the registry, so the publish and nightly rebuild jobs still
log in with `GITHUB_TOKEN` (see
[Architecture](../architecture/index.md#authentication)).
