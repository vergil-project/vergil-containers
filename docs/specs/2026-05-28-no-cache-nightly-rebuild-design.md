# No-cache nightly rebuild

**Issue:** [#304](https://github.com/vergil-project/vergil-docker/issues/304)
**Date:** 2026-05-28
**Status:** Design approved

## Problem

The Docker buildx registry cache (`cache-from`/`cache-to` with `mode=max`)
silently serves stale `apt-get update && apt-get upgrade` layers across CD
runs. Since the `apt-get upgrade` instruction text is identical across runs,
buildx treats it as a cache hit and serves the old layer. The cache is only
fully invalidated when the upstream base image tag gets a new push on Docker
Hub, which varies by language and is outside our control.

This means security patches published by Debian between cache invalidations
are silently skipped. The staleness window is unbounded and depends entirely
on upstream base image push frequency. The Rust upstream (`rust:X-slim`)
updates less frequently than Go or Python, making Rust images
disproportionately stale.

## Strategy

Bound the staleness window to ~24 hours by separating build concerns:

- **Nightly rebuilds** run with no cache, guaranteeing fresh apt packages
  and surfacing Trivy failures proactively before the workday.
- **Intraday CD builds** (merge-triggered) keep full registry caching for
  speed. They build on top of the previous night's fresh base, so they are
  at most ~24h stale.

## Design

### 1. New `no-cache` input on `cd-docker-publish.yml`

Add a boolean input to the reusable workflow:

```yaml
on:
  workflow_call:
    inputs:
      image-prefix:
        description: "Image name prefix (dev or prod)"
        type: string
        required: true
      no-cache:
        description: "Skip registry cache (for nightly fresh rebuilds)"
        type: boolean
        required: false
        default: false
```

### 2. Conditional cache parameters on build steps

Both `build-scan-push` and `publish-base` jobs use the same pattern.
The `docker/build-push-action` cache parameters become conditional:

```yaml
cache-from: ${{ inputs.no-cache && '' || format('type=registry,ref={0}', env.CACHE_TAG) }}
cache-to: ${{ inputs.no-cache && '' || format('type=registry,ref={0},mode=max', env.CACHE_TAG) }}
```

When `no-cache` is true, both resolve to empty string, which
`build-push-action` treats as no caching. When false, current behavior is
preserved exactly.

### 3. Nightly rebuilds in `ops.yml`

Rename the existing `nightly-rebuild` job to `nightly-rebuild-dev` and add a
`nightly-rebuild-prod` job. Both pass `no-cache: true`:

```yaml
nightly-rebuild-dev:
  uses: ./.github/workflows/cd-docker-publish.yml
  with:
    image-prefix: dev
    no-cache: true

nightly-rebuild-prod:
  uses: ./.github/workflows/cd-docker-publish.yml
  with:
    image-prefix: prod
    no-cache: true
```

The two jobs run in parallel (no dependency between them). Both require the
same permissions as the existing `nightly-rebuild` job (`packages: write`,
`contents: read`, `security-events: write`, `attestations: write`,
`id-token: write`). The existing `github-config` job is unrelated and
unchanged.

### 4. CD builds unchanged

`cd.yml` does not pass `no-cache`, so it defaults to `false`. Intraday
merge-triggered builds continue using full registry caching exactly as
they do today.

### 5. Manual escape hatch

`ops.yml` already has `workflow_dispatch` as a trigger. Dispatching it
manually runs both nightly-rebuild jobs with `no-cache: true`, providing an
on-demand forced fresh rebuild when needed (e.g., when a Trivy scan reveals
a fixable CVE mid-day).

## Scope

### In scope

- New `no-cache` input on `cd-docker-publish.yml`
- Conditional cache parameters on both build steps (`build-scan-push` and
  `publish-base`)
- Rename `nightly-rebuild` to `nightly-rebuild-dev` in `ops.yml`
- Add `nightly-rebuild-prod` job in `ops.yml`
- Both nightly jobs pass `no-cache: true`

### Out of scope

- No changes to Dockerfile templates, `generate.sh`, or `build.sh`
- No changes to Trivy scan steps, attestation, or promotion logic
- No changes to `cd.yml` or `ci.yml`
- No changes to the version matrix

## Files changed

| File | Change |
|------|--------|
| `.github/workflows/cd-docker-publish.yml` | Add `no-cache` input; conditional `cache-from`/`cache-to` on both build steps |
| `.github/workflows/ops.yml` | Rename `nightly-rebuild` to `nightly-rebuild-dev` with `no-cache: true`; add `nightly-rebuild-prod` with `no-cache: true` |
