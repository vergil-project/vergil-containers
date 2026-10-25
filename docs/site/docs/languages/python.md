# Python support policy

Image family: `dev-python`. Shared rules: [Language version
lifecycle](lifecycle.md). Upstream facts on this page were checked on
2026-10-21.

## Upstream source of truth

- **Official:** [PEP 602, Annual Release Cycle for
  Python](https://peps.python.org/pep-0602/) and the Python Developer's Guide
  [Status of Python versions](https://devguide.python.org/versions/).
- **endoflife.date product:** `python`
  ([page](https://endoflife.date/python),
  [API](https://endoflife.date/api/python.json)).

Data, from those pages:

- PEP 602 releases a new feature version every twelve months, in October.
- Each feature version is supported for five years after its `x.y.0` release.
  It receives bug fixes first, then security fixes only. The Developer's Guide
  states the split as two years of bug fixes (18 months for versions before
  3.13), then security fixes only, with support ending five years after the
  release.
- The Developer's Guide lists these branches: 3.15 (bugfix, first released
  2026-10-09, EOL 2031-10), 3.14 (bugfix, 2025-10-07, EOL 2030-10), 3.13
  (security, 2024-10-07, EOL 2029-10), 3.12 (security, 2023-10-02, EOL 2028-10)
  and 3.11 (security, 2022-10-24, EOL 2027-10). It notes that these EOL dates
  are scheduled and can be adjusted.

## Support rule

Every minor version that is GA and not EOL, subject to the no-backfill rule.
This rule was decided in epic
[vergil-project/.github#407](https://github.com/vergil-project/.github/issues/407)
(spec §5.1).

On 2026-10-21 that is 3.12, 3.13, 3.14 and 3.15. Python 3.11 is still
supported upstream, but stays out because it is older than the window's oldest
version (no backfill), not because of a special case.

A version in security-fix-only status stays in the window until EOL. The shared
rules allow dropping it earlier as a judgment call, and this policy does not
make that call.

## What counts as GA

The final `x.y.0` release. PEP 602 describes four beta releases and two or more
release candidates, which "conclude with the release of the final release of
Python 3.X.0". Alphas, betas and release candidates are pre-releases and never
GA.

In endoflife.date, a cycle is GA once its `releaseDate` is on or before the
day of the check.

## Adapter quirks

- The image is built `FROM python:<version>-slim`, the official Docker image,
  with `PYTHON_VERSION` as the build argument. A new version can be added only
  once that tag exists.
- Deployed Python code needs a `vergil-python` runtime for its version (see
  below). Containers and runtimes are released separately, so there can be a
  gap of a few days between them. A packaged Python app or library deploys on
  the newest window version that has a published runtime. That rule is
  Python-specific, so it lives in the Python adapter and resolver extension,
  never in shared code.
- The manifest's `runtime_published` field records, for each version, whether
  a `vergil-python` runtime is published. It travels in the published window.

## Deployed runtime package

**Yes.** `vergil-python` publishes the runtime that deployed Python code runs
on. Each version in the window needs one before a packaged app or library can
deploy on it.

There is one package per Python series, named `vergil-python<x.y>` and
installed at `/opt/vergil/python/<x.y>`. The patch level floats within the
series. On 2026-10-23 `vergil-python` builds the 3.15 series. The 3.14 package
stays published but is frozen at 3.14.8+20261013 and no longer rebuilt.
Building several series at once is deferred to
[vergil-project/vergil-python#36](https://github.com/vergil-project/vergil-python/issues/36).

## Automation

**`pr`.** The lifecycle check opens the pull request that adds or drops a
Python version. It also opens a `runtime` pull request when a version's
`vergil-python` runtime is first published, which sets that version's
`runtime_published` field. A newly added version starts with
`runtime_published: false`.

## Current out-of-policy versions

As of 2026-10-23: **none.** The manifest builds 3.15, 3.14, 3.13 and 3.12,
all of which are GA and not EOL, so the window is in sync with upstream. It
records a published runtime for 3.15 and 3.14.
