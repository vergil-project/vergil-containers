# Image Rollback (Repoint)

When a bad tool version floats into a published image and breaks the fleet,
this runbook rolls the rolling tag back to a known-good prior build **instantly,
without a rebuild** — by repointing it at an immutable datestamp alias.

## When to use this

This is the **Axis-B** recovery path. Container structure (Dockerfiles, tool
inventory) is Axis A and rolls back through source — revert and re-release. Tool
*versions* float at build time (within pin constraints), so a bad leading-edge
release is an Axis-B problem, and a source rebuild would merely re-float the same
broken version. Axis B rolls back by **artifact-digest repoint**, not by
rebuilding.

Reach for this when a `dev-` or `prod-` image starts failing because a floating
tool resolved to a bad upstream release, and you need the fleet green *now* while
you fix forward.

!!! note "This is a break-glass procedure, not the fix"
    Repointing buys time; it does not resolve the underlying bad release. Always
    pair a repoint with a fix-forward tracking issue (step 4) — typically a pin
    with an `inducing_release`, evaluated per the pin lifecycle. See the
    re-evaluation algorithm in the container-pinning spec (§4.3, epic
    [vergil-project/.github#155](https://github.com/vergil-project/.github/issues/155)),
    which is what decides whether the eventual pin is deterministic-and-tested or
    a suppress-and-observe `under-evaluation` hold.

## Prerequisites

- **The target build must still be in the retention window.** Each build
  publishes an immutable alias `{prefix}-{lang}:{version}-YYYYMMDD` at the same
  digest as the rolling tag. Those aliases are pruned past a fixed window —
  **prod = 30 days, dev = 7 days** — by the sliding-window reaper in
  [`package-cleanup.yml`](https://github.com/vergil-project/vergil-containers/blob/develop/.github/workflows/package-cleanup.yml)
  (see also [Package Hygiene](package-hygiene.md) for org package retention). You
  can only repoint at an alias that has not yet been reaped.
- **Registry credentials with write access** to the target GHCR package. Log in
  with a token that can push to `ghcr.io/vergil-project/*`:

  ```bash
  echo "$GHCR_TOKEN" | docker login ghcr.io -u <user> --password-stdin
  ```

  `GHCR_TOKEN` needs `write:packages`. The repoint is a deliberate human action
  run with a human's credentials — it is intentionally not automated.

## Procedure

### 1. List the in-window datestamp aliases

Find the last-good `{version}-YYYYMMDD` alias for the affected image. List the
package's tags via the GitHub API:

```bash
vrg-gh api --paginate \
  "/orgs/vergil-project/packages/container/prod-<lang>/versions" \
  --jq '.[].metadata.container.tags[]' \
  | grep -E '^<version>-[0-9]{8}$' | sort
```

For example, for `prod-go` at `1.26`, match `^1\.26-[0-9]{8}$`. The datestamp in
the tag is the build's UTC date; pick the newest one that predates the bad build.
(The rolling tag itself — `prod-go:1.26` — is what consumers currently pull and
is what you are about to repoint.)

### 2. Repoint the rolling tag at the chosen alias's digest

Use `docker buildx imagetools create` to make the rolling tag reference the
chosen alias's manifest. This is a **registry-side manifest copy** — it copies
the multi-arch manifest by digest, with no pull, no rebuild, and no digest
change to the alias:

```bash
docker buildx imagetools create \
  --tag ghcr.io/vergil-project/prod-<lang>:<version> \
  ghcr.io/vergil-project/prod-<lang>:<version>-YYYYMMDD
```

This is the same command the publish pipeline
([`cd-docker-publish.yml`](https://github.com/vergil-project/vergil-containers/blob/develop/.github/workflows/cd-docker-publish.yml))
uses to promote a candidate to the rolling and immutable tags, so the rolling tag
ends up at a digest that was already scanned, attested, and published.

Confirm the rolling tag now resolves to the good alias's digest:

```bash
docker buildx imagetools inspect \
  ghcr.io/vergil-project/prod-<lang>:<version> --format '{{.Manifest.Digest}}'
docker buildx imagetools inspect \
  ghcr.io/vergil-project/prod-<lang>:<version>-YYYYMMDD --format '{{.Manifest.Digest}}'
```

The two digests must match.

### 3. Consumers get the prior build immediately

There is nothing else to trigger. The rolling tag now points at the good
manifest, so **any consumer pulling `{prefix}-{lang}:{version}` gets the prior
build on its next pull** — no rebuild, no workflow run, no cache invalidation.
CI jobs and local `vrg-container-run` pulls that reference the rolling tag pick
up the good image immediately.

### 4. Open a fix-forward tracking issue

The repoint is temporary — the next scheduled build will re-float the bad version
and undo it unless the root cause is fixed. Immediately open a tracking issue:

```bash
vrg-gh issue create --repo vergil-project/vergil-containers \
  --title "Fix forward: <lang> <version> rolled back from <bad-build> to <alias>" \
  --body "Repointed prod-<lang>:<version> at prod-<lang>:<version>-YYYYMMDD (digest <sha256>) on <date> because <what broke>. Fix forward before the alias is reaped (prod 30d / dev 7d)."
```

Record **which alias you rolled to** and **why** so the fix-forward work has the
context, and so the eventual pin decision (§4.3) has the inducing release. Until
that issue lands, the repoint is holding the fleet together on borrowed time —
the alias will eventually be reaped, and the next build will re-float the bad
version.

## Demonstration

The repoint mechanic was verified end-to-end against a throwaway local registry:
two datestamp aliases were published at different digests, the rolling tag was
pointed at the "bad" one, then repointed at the older "good" alias. After the
repoint, a fresh pull of the rolling tag returned the good build's content and
the rolling tag's manifest digest matched the good alias's digest exactly — with
no rebuild. See the pull request for the captured commands and output.
