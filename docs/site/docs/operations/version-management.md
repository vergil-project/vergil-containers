# Tool Version Management

The images bundle a shared layer of build, lint, and security tools. This page
explains **how those tool versions are managed** — the pinning philosophy, the
lifecycle every pin follows, the generated catalog and its CI gate, the weekly
leading-edge bumper, and the exposure report that flags pins due for
re-evaluation.

It is the operator-facing companion to the container-pinning design (epic
[vergil-project/.github#155](https://github.com/vergil-project/.github/issues/155)).
The authoritative, always-current list of what is pinned and why is the
generated catalog:
[`docker/pins/CATALOG.md`](https://github.com/vergil-project/vergil-containers/blob/develop/docker/pins/CATALOG.md).
This page is doctrine; the catalog is data.

## Pinning philosophy

A pinned version with no management process is a permanent, silently-drifting
freeze — it slides from the leading edge to the trailing edge and can carry a
known CVE indefinitely because nothing is watching it. The doctrine exists to
make every pin **re-evaluable** and to keep pins rare:

1. **Default is unpinned.** Tools float on each product's leading edge.
2. **A pin is a reaction, never a default** — a reaction to being unable to
   stay on the leading edge because a release breaks us.
3. **Every pin carries a written justification** — held because of release X,
   for reason Y.
4. **Least-specific pin that solves the problem** — pin `1.x`, not the exact
   patch, when that is enough.
5. **When in doubt, set it free** — unpin, see what breaks, then pin only the
   specific culprit at the least-specific working constraint.
6. **A pin is anchored to the release that induced it and carries a
   re-evaluation trigger — never permanence.** Every pin records the specific
   upstream release whose problem caused it. The pin is valid *only while that
   release is the leading edge*; the moment the leading edge moves past the
   inducing release, the pin is automatically **due for re-evaluation**. The
   trigger ("has the leading edge moved past the inducing release?") is always
   deterministic and observable, even when the underlying problem is not. This
   is what kills permanent pins structurally.

## Two axes of change

Two independent things move in these images, and they recover differently:

- **Axis A — container structure** (Dockerfiles, tool inventory). Source-
  controlled; moves as a step function through GitFlow (`develop → main` =
  `dev → prod`). Rollback is a source revert / re-release.
- **Axis B — dependency versions** (whatever floats in at each nightly build,
  within pin constraints). A continuous target; a bad leading-edge release is
  an Axis-B problem. Rollback is an **artifact-digest repoint**, not a rebuild —
  a source rebuild would merely re-float the same broken version. See
  [Image Rollback (Repoint)](rollback.md).

Version management is the discipline that governs Axis B.

## Pin states

Each pin entry in
[`docker/pins/pins.yml`](https://github.com/vergil-project/vergil-containers/blob/develop/docker/pins/pins.yml)
carries an explicit **state** — never a commented-out line, so the metadata
stays structured:

| State | Enforced? | Meaning |
| --- | --- | --- |
| **active** | Yes | A Tenet-6 break-hold: a specific upstream release broke us; the constraint applies and names its `inducing_release`. |
| **under-evaluation** | No (floats) | Retained with full metadata and a scheduled follow-up issue. The observe phase for a non-deterministic / stability pin. |
| **freed** | No | Removed; the tool floats with no record needed (the entry is deleted). |
| **auto-managed** | Yes (as source pin) | Pinned in source for reproducibility, but floated to the newest upstream release weekly by the bumper (below). `inducing_release` is null — not a break-hold. |

## The generated catalog and its CI gate

The catalog is **generated, never hand-maintained** — the founding problem was
exactly a hand-edited version list drifting from the code (`CLAUDE.md` once said
`uv 0.11.13` while the image shipped a newer one). The pipeline:

- Version *facts* are extracted from the Dockerfile templates and fragments —
  the single source of truth (`docker/pins/extract_pins.py`).
- *Justifications* live in the keyed `pins.yml` (schema per pin: `constraint`,
  `inducing_release`, `deterministic`, `reason`, `state`, `tracking_issue`).
- `docker/pins/generate_catalog.py` joins them into the human-readable
  `CATALOG.md`.

A **CI gate** (`docker/pins/check_pins.py`, run in `ci.yml`) fails the build if
any exact-pinned tool lacks a `pins.yml` justification, if a `pins.yml` entry no
longer pins anything, or if an entry declares an unknown state. **A new pin
cannot merge undocumented.** A companion `generate_catalog.py --check` fails if
`CATALOG.md` is stale relative to the templates and `pins.yml`.

## Auto-managed tools and the weekly bumper

Most package-manager tools (installed via `npm`, `pip`, `uv`, `go install`,
`cargo`) were **freed** in the pin audit: dropping the version token lets them
resolve latest at build time, so they float cleanly and need no entry.

Nine tools install from a **binary release tarball** whose download URL and
per-version checksum embed an explicit version, so they cannot float by simply
dropping a token. Rather than add an unauthenticated GitHub version-resolution
round-trip to every image build, these are **auto-managed**: shellcheck, shfmt,
actionlint, git-cliff, hadolint, opentofu, nfpm, scorecard, and trivy.

They stay pinned in source (hermetic, reproducible, revertible) while the weekly
[`bump-tools.yml`](https://github.com/vergil-project/vergil-containers/blob/develop/.github/workflows/bump-tools.yml)
workflow tracks the leading edge:

- Runs Mondays 06:30 UTC (and on demand). For each tool it resolves the newest
  release via the `/releases/latest` redirect
  (`docker/pins/resolve_latest.py`), rewrites the `ARG *_VERSION=` pins in
  `docker/common/*`, and regenerates `CATALOG.md`.
- **Only if something drifted** it opens a bump PR, authored by the GitHub App
  (so the PR fires CI and every bump is validated). **Nothing is auto-merged** —
  fleet policy keeps a human merge gate.

This is how a leading-edge CVE fix reaches the images without a hand edit — for
example the trivy `0.70.0 → 0.72.0` security bump landed through the bumper.

## Exposure report — pins due for re-evaluation

`docker/pins/report_exposure.py` (WS4) generates the internal-state
observability view for a daily morning-review ritual. It reports:

- **Due for re-evaluation** (the headline signal): active pins whose
  `inducing_release` is no longer the leading edge — i.e. Tenet 6's trigger has
  fired and the pin must be reconsidered per the lifecycle below.
- The **auto-managed** set and their leading-edge constraints.
- **Installed tool versions per image** (pinned and floating), joined with pin
  state.

It is deliberately scoped to what is local and un-driftable — one upstream
"latest" lookup per pinned tool, no full cross-registry drift tracker. A tool
whose latest cannot be resolved is simply absent from the report (unknowns never
raise a false alarm). Full upstream-distance drift tracking is the report-only
Dependabot follow-on (epic
[vergil-project/.github#158](https://github.com/vergil-project/.github/issues/158)),
intentionally not built here.

## Re-evaluation lifecycle (operator guidance)

When the exposure report flags a pin as due for re-evaluation — the leading edge
has moved past its `inducing_release` — work it through this algorithm (spec
§4.3). Which branch you take depends on whether the pin's problem is
**deterministic** (reproducible and testable) or not.

### Deterministic pin (the problem is reproducible → testable)

1. Test the new leading edge against the known problem.
2. **Problem gone** → **delete the pin** (state → `freed`); the tool floats
   again.
3. **Problem persists** → **re-anchor**: set `inducing_release` to the new
   leading edge and keep holding. The trigger will not fire again until
   something *newer* than the new anchor appears. A persistent problem advances
   the anchor; it does not delete the pin.

### Non-deterministic / stability pin (cannot pre-test)

1. **Suppress and observe**: set state → `under-evaluation` (the constraint is
   no longer enforced, so the tool floats to the new leading edge), add a note,
   and open a **scheduled follow-up issue** to proactively check stability at a
   future date. [Image Rollback (Repoint)](rollback.md) covers the interim if
   instability recurs.
2. **Instability recurs** → restore the pin (state → `active`, re-anchor past
   the bad release).
3. **Stable across the evaluation window** → set state → `freed`.

**Mechanization boundary:** the *trigger* is fully mechanized (the exposure
report flags it) and the deterministic re-test often is (a CI test); the
non-deterministic observation is not — but its *process* is fully described (the
`under-evaluation` state plus a tracking issue), so nothing silently rots.

## See also

- [`docker/pins/CATALOG.md`](https://github.com/vergil-project/vergil-containers/blob/develop/docker/pins/CATALOG.md)
  — the generated source of truth for current versions.
- [Image Rollback (Repoint)](rollback.md) — Axis-B recovery when a bad float
  ships.
- [Package Hygiene](package-hygiene.md) — datestamp-alias retention that keeps
  rollback targets available.
- [Images](../images/index.md) — the tool inventory per image.
