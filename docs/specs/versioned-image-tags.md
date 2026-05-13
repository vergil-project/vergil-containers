# Versioned image tags for dev container images

**Status:** Draft — passed `paad:pushback` 2026-04-28
**Issue:** [#60](https://github.com/vergil-project/vergil-docker/issues/60)
**Pushback review:**
[`paad/pushback-reviews/2026-04-28-versioned-image-tags-pushback.md`](../../paad/pushback-reviews/2026-04-28-versioned-image-tags-pushback.md)
**Author:** wphillipmoore
**Last updated:** 2026-04-28

## Purpose

Introduce immutable versioned tags alongside the existing mutable tags
for all `dev-*` container images. This enables staged rollout of
radical image changes, per-repo pinning for stability, and decouples
docker image patch releases from standard-tooling's release cycle.

This spec reaches across repo boundaries: the publish side lives in
`vergil-docker`, the consumer resolution logic lives in
`standard-tooling`, consuming repos exercise the override mechanism,
and standard-tooling's release skill gains a post-release coordination
checklist.

## Problem statement

Today all `dev-*` images are published with mutable tags only
(`dev-python:3.14`, `dev-go:1.26`, etc.). Every push to `develop` or
`main` overwrites these tags.

This produces two problems:

1. **No staging.** "Deploy the new images" and "everyone gets the new
   images" are the same event. There is no way to exercise a
   radically changed image set in a single consumer before fleet-wide
   exposure.

2. **Tight coupling with standard-tooling releases.** Standard-tooling
   is embedded in the docker images. Today a standard-tooling release
   fires a `repository_dispatch` that rebuilds and overwrites the
   mutable tags. There is no way to ship a docker-only patch (base
   image security fix, tool version bump) without an unversioned image
   overwrite that cannot be rolled back. And the dispatch-triggered
   rebuild model breaks entirely under versioned tags (see
   "Release coordination" below).

## Design

### Tag scheme (three tiers)

Every build of `docker-publish.yml` pushes tags according to which
branch triggered the build:

#### Builds triggered by `main` (release builds)

| Tag form | Example | Mutability | Purpose |
|----------|---------|------------|---------|
| Language version only | `dev-python:3.14` | Mutable | Backwards compatibility (deprecated after migration) |
| Rolling minor | `dev-python:3.14-v1.2` | Mutable (force-updated on each patch) | Fleet default — auto-receives patches |
| Exact patch | `dev-python:3.14-v1.2.1` | Immutable (never overwritten) | Per-repo pinning, rollback target |

#### Builds triggered by `develop` (development builds)

| Tag form | Example | Mutability | Purpose |
|----------|---------|------------|---------|
| Language version only | `dev-python:3.14` | Mutable | Backwards compatibility (deprecated after migration) |
| Dev exact | `dev-python:3.14-v1.2.1-dev` | Mutable | Pre-release testing in consumer repos |

Development builds do **not** push the rolling minor or clean
immutable tags. Those are reserved for release builds on `main`. This
ensures versioned tags correspond to released code.

#### `dev-base` tag form

`dev-base` has no language version. The word `common` fills the
language-version slot to keep tag structure uniform:

| Tag form | Example |
|----------|---------|
| Mutable (legacy) | `dev-base:latest` |
| Rolling minor | `dev-base:common-v1.2` |
| Exact patch | `dev-base:common-v1.2.1` |
| Dev exact | `dev-base:common-v1.2.1-dev` |

The `dev-base:latest` tag is retained as a migration aid and
deprecated once rollout completes.

### Version source

The version is read from this repo's `VERSION` file, managed by
`st-prepare-release`. The rolling minor is derived by stripping the
patch component (e.g., `1.2.1` → `v1.2`).

### Consumer resolution (standard-tooling)

`standard_tooling/lib/docker.py` gains a `_DOCKER_PIN` constant:

```python
_DOCKER_PIN = "v1.2"  # rolling minor — fleet default
```

Image resolution appends the pin as a tag suffix:

```python
def default_image(lang: str, *, fallback: bool = False) -> str:
    image = _DEFAULT_IMAGES.get(lang, "")
    if not image and fallback:
        image = _FALLBACK_IMAGE
    if image and _DOCKER_PIN:
        image = f"{image}-{_DOCKER_PIN}"
    return image
```

All docker commands that resolve images — `st-docker-run` and
`st-docker-docs` — must use this resolution path. `st-docker-docs`
currently hardcodes `ghcr.io/wphillipmoore/dev-base:latest` and
bypasses `docker.py`; it must be refactored to use `default_image()`
(or at minimum read `_DOCKER_PIN` / `DOCKER_PIN`).

### Override priority (highest wins)

| Priority | Mechanism | Scope | Use case |
|----------|-----------|-------|----------|
| 1 | `DOCKER_DEV_IMAGE` env var | Full image override | Custom/local images |
| 2 | `DOCKER_PIN` env var | Suffix override | Per-repo freeze on exact patch, or testing `-dev` tags |
| 3 | `_DOCKER_PIN` constant | Fleet default | Normal operation (rolling minor) |
| 4 | (empty pin) | No suffix | Legacy / opt-out (bare `:3.14` tag) |

A repo that needs to freeze on an exact patch while the fleet rolls
forward:

```bash
DOCKER_PIN=v1.2.0 st-docker-run -- uv run pytest
```

A repo that wants to test a development build before release:

```bash
DOCKER_PIN=v1.3.0-dev st-docker-run -- cargo test
```

### Publish workflow changes (this repo)

`docker-publish.yml` tag-and-push step becomes branch-aware:

```yaml
- name: Read version
  id: version
  run: |
    VERSION=$(cat VERSION)
    MINOR="v${VERSION%.*}"
    echo "full=v${VERSION}" >> "$GITHUB_OUTPUT"
    echo "minor=${MINOR}" >> "$GITHUB_OUTPUT"

- name: Tag and push image
  run: |
    # Mutable language-version tag (all branches, backwards compat)
    docker tag "$CANDIDATE" "$IMAGE"
    docker push "$IMAGE"

    if [ "${{ github.ref_name }}" = "main" ]; then
      # Release builds: clean versioned tags
      docker tag "$CANDIDATE" "$IMAGE-${{ steps.version.outputs.full }}"
      docker tag "$CANDIDATE" "$IMAGE-${{ steps.version.outputs.minor }}"
      docker push "$IMAGE-${{ steps.version.outputs.full }}"
      docker push "$IMAGE-${{ steps.version.outputs.minor }}"
    else
      # Development builds: -dev suffix
      docker tag "$CANDIDATE" "$IMAGE-${{ steps.version.outputs.full }}-dev"
      docker push "$IMAGE-${{ steps.version.outputs.full }}-dev"
    fi
```

### Release workflow (new, this repo)

A lightweight `publish.yml` fires on push to `main`:

- Reads `VERSION`, creates git tag `v{VERSION}`, creates GitHub
  Release with changelog.
- `publish.yml` consumes VERSION — it does not manage it. The
  invariant that VERSION is fresh on `main` is enforced upstream by
  `st-prepare-release`, which cuts a release branch with the new
  version and immediately bumps the patch on `develop` after merge.

## Release coordination

### Standard-tooling's three deployment targets

Standard-tooling is deployed to three places:

1. **Docker images** — embedded via `ST_TOOLING_TAG` pin in the
   Dockerfile fragments (`standard-tooling-uv.dockerfile`,
   `standard-tooling-pip.dockerfile`).
2. **Host install** — user's local environment via
   `uv tool install`.
3. **Python repo venvs** — pulled as a dev dependency into each
   Python repo's virtual environment.

A standard-tooling release is not complete until all three targets are
updated. The fleet has patch-level compliance checks that catch drift,
but the release workflow itself must surface the coordination
requirement.

### Removing `repository_dispatch`

The existing `repository_dispatch: [standard-tooling-released]`
trigger in `docker-publish.yml` is **removed** by this spec. Under
mutable-only tags, dispatch could fire a rebuild that overwrote tags
in place — fully automated. Under versioned tags, updating the docker
images requires a new release of vergil-docker (bump
VERSION, `st-prepare-release`, release branch, PR to `main`, merge).
That ceremony is AI/human-driven; a GitHub Action cannot trigger it
autonomously.

### Post-release checklist

Standard-tooling's release skill (`st-prepare-release` or its
surrounding workflow) gains a post-release checklist as its final
output. After cutting a standard-tooling release, the skill reminds
the human:

```
Release v1.5.0 tagged and published.

Post-release checklist:
[ ] Host install: uv tool install --upgrade 'standard-tooling @ git+...@v1.5'
[ ] Docker images: if this release affects in-container behavior,
    cut a new vergil-docker release
    (bump ST_TOOLING_TAG, st-prepare-release, merge to main)
[ ] Python repo venvs: version constraint pulls new release
    automatically on next uv sync
```

The docker re-release is a conscious decision. Sometimes the human
will skip it because the standard-tooling change does not affect
in-container behavior (e.g., a change to `st-commit` or
`st-submit-pr` which are host-only tools). The checklist surfaces the
decision without forcing it.

### Decoupling benefit

**Before this spec:**

```
standard-tooling release
  → repository_dispatch (automated)
  → docker rebuild (overwrites mutable tags)
  → all consumers get new image (no control, no versioning)
```

**After this spec:**

- **Docker-only patches** (security fixes, base image bumps, tool
  version updates): `st-prepare-release` in this repo → merge to
  `main` → versioned tags pushed → rolling minor auto-updates
  consumers. No standard-tooling release required.

- **Standard-tooling releases that affect containers**: human/AI
  updates `ST_TOOLING_TAG` in this repo, runs `st-prepare-release`,
  merges to `main`. New docker minor (e.g., v1.3) published. Then PR
  to standard-tooling bumping `_DOCKER_PIN = "v1.3"` → next
  standard-tooling release → fleet follows.

- **Standard-tooling releases that don't affect containers**: no
  docker action needed. Human checks the box and moves on.

The rolling minor tag absorbs patch churn silently. Only minor
boundaries require cross-repo coordination via `_DOCKER_PIN`.

## Migration plan

Three phases, strictly ordered, each independently shippable and
backwards-compatible.

### Phase 1: Publish versioned tags (this repo)

**PR scope:**
- `docker-publish.yml`: branch-aware tag logic (mutable + `-dev` on
  `develop`; mutable + rolling minor + immutable on `main`).
- Remove `repository_dispatch: [standard-tooling-released]` trigger.
- Add `publish.yml` workflow (git tag + GitHub Release on push to
  `main`).
- Bump `VERSION` to `1.1.0` via `st-prepare-release`.
- Update `standard-tooling.toml` to reflect real release model
  (resolves issue #61).

**Consumer impact:** None. Existing mutable tags still pushed.
Additional versioned tags appear on GHCR but nothing references them
yet. Removing `repository_dispatch` means standard-tooling releases
no longer auto-trigger docker rebuilds — this is intentional and
replaced by the post-release checklist.

**Rollback:** Remove extra tag/push lines, restore
`repository_dispatch` trigger.

### Phase 2: Add pin resolution and post-release checklist (standard-tooling)

**PR scope:**
- `docker.py`: add `_DOCKER_PIN = ""` constant and `DOCKER_PIN` env
  var support in `default_image()`.
- `docker_docs.py`: refactor to use `docker.py`'s `default_image()`
  for the base image default instead of hardcoding
  `ghcr.io/wphillipmoore/dev-base:latest`.
- `docker_run.py`: print resolved pin in startup banner.
- Update `st-docker-run` and `st-docker-docs` help text to document
  `DOCKER_PIN`.
- Release skill: add post-release checklist output (host install,
  docker images, Python venvs).

**Consumer impact:** None. Empty pin preserves today's behavior
exactly (bare language-version tags). Post-release checklist is
informational only.

**Rollback:** Revert commit.

### Phase 3: Activate fleet pinning (standard-tooling)

**PR scope:** Single commit:

```python
_DOCKER_PIN = "v1.1"
```

Cut a standard-tooling release. All consumers of `st-docker-run` and
`st-docker-docs` now resolve images to rolling-minor tags (e.g.,
`dev-python:3.14-v1.1`).

**Consumer impact:** Fleet-wide. All docker command invocations
resolve to the pinned rolling minor tag.

**Rollback:** Set `_DOCKER_PIN = ""` + emergency release, or
individual users set `DOCKER_PIN=""` locally.

**This is the one-shot fleet migration** — a single standard-tooling
release pins the entire fleet to versioned images.

### Phase 4: Deprecate unversioned tags

After confirming fleet-wide operation on versioned tags:

- Remove bare mutable tag push from `docker-publish.yml` (stop
  publishing `dev-python:3.14`, `dev-base:latest`).
- Remove `DOCKER_DOCS_IMAGE` env var from `docker_docs.py` (unified
  under `DOCKER_DEV_IMAGE` / `DOCKER_PIN`).
- Delete stale unversioned tags from GHCR.

This is cleanup, not a migration step. It can happen at any pace.

## Ongoing operations

| Scenario | Action | Touches standard-tooling? |
|----------|--------|--------------------------|
| Docker-only patch (CVE fix, tool bump) | `st-prepare-release` in this repo, merge to `main` | No |
| New language version in matrix | Add matrix entry, `st-prepare-release` (minor bump), merge | No (same rolling minor) |
| Radical image change (base OS, restructure) | Minor bump, publish, test via `DOCKER_PIN=vX.Y.Z-dev` in consumer repos, then release and PR to bump `_DOCKER_PIN` | Yes (minor boundary) |
| Standard-tooling release (affects containers) | Post-release checklist reminds human. Human bumps `ST_TOOLING_TAG` in this repo, runs `st-prepare-release`, merges. Then PRs `_DOCKER_PIN` bump if minor changed. | Yes (if minor boundary) |
| Standard-tooling release (host-only change) | Post-release checklist — human skips docker item | No |

## Related issues

- [#60](https://github.com/vergil-project/vergil-docker/issues/60) — original design issue (this spec implements it)
- [#61](https://github.com/vergil-project/vergil-docker/issues/61) — repo profile claims tagged-release but no workflow exists (resolved by Phase 1)
- [#51](https://github.com/vergil-project/vergil-docker/issues/51) — standard-tooling freshness in images (orthogonal but related coupling concern)
