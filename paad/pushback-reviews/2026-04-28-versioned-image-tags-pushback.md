# Pushback Review: versioned-image-tags

**Date:** 2026-04-28
**Spec:** docs/specs/versioned-image-tags.md
**Commit:** 7127b28064c28c2a502ed6ac53051aef244fed14

## Source Control Conflicts

None — no conflicts with recent changes.

## Issues Reviewed

### [1] `st-docker-docs` bypasses pin mechanism
- **Category:** Omission
- **Severity:** Serious
- **Issue:** `docker_docs.py` hardcodes `ghcr.io/wphillipmoore/dev-base:latest`
  and uses its own `DOCKER_DOCS_IMAGE` env var. It does not call `docker.py`'s
  `default_image()`, so the `_DOCKER_PIN` mechanism would not reach
  `st-docker-docs`. After fleet activation, `st-docker-run` would use pinned
  images while `st-docker-docs` silently remained on bare `:latest`.
- **Resolution:** Accepted recommendation. Refactor `docker_docs.py` to use
  `docker.py`'s resolution path. Added to Phase 2 scope in the spec.

### [2] `develop` and `main` both push versioned tags — unclear ownership
- **Category:** Ambiguity
- **Severity:** Serious
- **Issue:** The workflow fires on both `develop` and `main`. If both branches
  push the same versioned tags, "immutable" tags appear on GHCR from
  unreleased `develop` builds before the release ceremony on `main`.
- **Resolution:** Option 2 selected. `develop` builds push a `-dev` suffix
  (e.g., `dev-python:3.14-v1.2.1-dev`). Clean versioned tags (`-v1.2`,
  `-v1.2.1`) only come from `main`. This gives a staging path: exercise
  `-dev` tags in consumer repos before releasing.

### [3] `publish.yml` release semantics — every merge to `main` a release?
- **Category:** Feasibility
- **Severity:** Moderate
- **Issue:** If every merge to `main` triggers a GitHub Release via
  `publish.yml`, VERSION must be bumped before every merge. If not, duplicate
  tag creation fails.
- **Resolution:** Moot. The release workflow (`st-prepare-release`) owns
  VERSION management. It cuts a release branch with fresh VERSION, merges to
  `main`, then immediately bumps the patch on `develop`. `publish.yml`
  consumes VERSION — it does not manage it. The invariant is enforced
  upstream.

### [4] `dev-base` tag form is awkward under the versioned scheme
- **Category:** Ambiguity
- **Severity:** Moderate
- **Issue:** `dev-base:latest` with an appended pin produces
  `dev-base:latest-v1.2` — `:latest` suffixed with a version sends mixed
  signals.
- **Resolution:** Use `common` as the language-version slot:
  `dev-base:common-v1.2`. This keeps the tag structure uniform across all
  images (`{category}-{docker-version}`). The mutable `dev-base:latest` tag
  is retained as a migration aid and deprecated once rollout completes.

### [5] VERSION bump responsibility is implicit
- **Category:** Ambiguity
- **Severity:** Minor
- **Issue:** The "Ongoing operations" table says "bump VERSION patch, merge"
  but doesn't state who/what bumps it.
- **Resolution:** Moot. VERSION is fully managed by `st-prepare-release`.
  "Docker-only patch" just means a change scoped to this repo — it still goes
  through the standard release workflow.

### [6] `repository_dispatch` breaks under versioned tags
- **Category:** Omission
- **Severity:** Major (elevated from minor during discussion)
- **Issue:** With mutable-only tags, `repository_dispatch` from a
  standard-tooling release could fire a rebuild that overwrote tags in place.
  With versioned tags, a standard-tooling release means vergil-docker
  needs a new release (bump VERSION, release branch, PR to `main`). That
  ceremony is AI/human-driven (`st-prepare-release`) — a GitHub Action cannot
  trigger it autonomously. The `repository_dispatch` pipeline breaks.
- **Resolution:** Remove `repository_dispatch` from the design. Standard-tooling
  has three deployment targets (docker images, host install, Python repo venvs).
  A release is not complete until all three are updated. The standard-tooling
  release skill should surface a post-release checklist as its final step.
  The docker re-release is one item on that checklist, executed by the
  human/AI when appropriate — and sometimes intentionally skipped when the ST
  change does not affect in-container behavior. Spec expanded to cover the
  full coordination model.

## Unresolved Issues

None — all issues addressed.

## Summary

- **Issues found:** 6
- **Issues resolved:** 6 (2 moot, 4 with design changes)
- **Unresolved:** 0
- **Spec status:** Updated with all resolutions. Ready for implementation
  after spec revision review.
