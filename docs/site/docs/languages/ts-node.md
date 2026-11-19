# TypeScript / Node.js support policy

Image family: `dev-ts-node`, the TypeScript image built on the Node.js runtime.
Shared rules: [Language version lifecycle](lifecycle.md). Upstream facts on
this page were checked on 2026-11-18.

## Upstream source of truth

- **Official:** Node.js [Previous
  Releases](https://nodejs.org/en/about/previous-releases) and the Release
  Working Group's [release schedule](https://github.com/nodejs/release#release-schedule).
- **endoflife.date product:** `nodejs` ([page](https://endoflife.date/nodejs),
  [API](https://endoflife.date/api/nodejs.json)).

Data, from those pages:

- Node.js says a new major spends six months as _Current_. Up to Node.js 26,
  odd-numbered majors become unsupported after that, and even-numbered majors
  move to _Active LTS_. LTS "typically guarantees that critical bugs will be
  fixed for a total of 30 months". The page also says: "Production
  applications should only use _Active LTS_ or _Maintenance LTS_ releases."
- **The schedule changes with Node.js 27.** The release cycle becomes annual,
  every release line goes through an _Alpha_ phase before _Current_, and
  "every release line is promoted to LTS". So the even-numbered rule applies
  only up to Node.js 26.
- The release schedule gives these dates:

  | Major | Initial release | LTS start | End of life |
  |---|---|---|---|
  | 26 | 2026-05-05 | 2026-10-28 | 2029-04-30 |
  | 24 | 2025-05-06 | 2025-10-28 | 2028-04-30 |
  | 22 | 2024-04-24 | 2024-10-29 | 2027-04-30 |

## Support rule

LTS majors that are not EOL, subject to the no-backfill rule.

**Judgment:** the spec proposed this window and left it to this policy to
confirm. It follows upstream's own advice that production should use only LTS
releases. The plan states the rule as "LTS (even-numbered) majors". This policy
uses the LTS status itself, not the parity of the number, because from Node.js
27 every major becomes LTS.

On 2026-11-17 that is 26, 24 and 22. Node.js 26 joined the window when it
became LTS on 2026-10-28.

## What counts as GA

**Judgment:** a Node.js major is GA for Vergil on its LTS start date, not on
its initial release. A major in its _Current_ (or, from 27, _Alpha_) phase is
treated like a pre-release. In endoflife.date, the `lts` field holds the LTS
start date, or `false` for a major that never becomes LTS. A major is GA once
that date is on or before the day of the check.

## Adapter quirks

- The image is built on `base`, and Node.js is the nodejs.org prebuilt
  tarball for the major, unpacked at `/opt/node/<major>`. The release and the
  SHA-256 of each architecture's tarball are pinned in
  `docker/pins/toolchains.yml`, which the daily upstream refresh moves to the
  newest release of the major. `NODE_MAJOR` is the build argument. A new major
  can be added only once nodejs.org's release index has a release of it with
  `linux-x64` and `linux-arm64` tarballs, which the adapter checks before
  proposing an add. It reads the index with the same fetcher the refresh uses.
- endoflife.date's `lts` field is either a date or `false`, and the adapter
  must handle both.
- The image carries only two TypeScript tools of its own, prettier and
  license-checker. `typescript`, `eslint`, `typescript-eslint`, `vitest` and
  `@vitest/coverage-v8` are not in the image: each TypeScript repository
  declares them as devDependencies, and Vergil's gates run them from the
  repository's `node_modules/.bin`, never from a global install. The rule is
  vergil-tooling's
  [Tool Ownership Guideline](https://vergil-project.github.io/vergil-tooling/latest/standards/development/tool-ownership/);
  the image's full tool list is under [Images](../images/index.md).
- The separate Node.js pin in `vergil-vm` must line up with this window.
  Lining it up is the work of epic 4,
  [vergil-project/.github#959](https://github.com/vergil-project/.github/issues/959).

## Deployed runtime package

**No.** Vergil has no deployed TypeScript application today. The need for a
runtime package is assessed when one exists.

## Automation

**`pr`.** The lifecycle check opens the pull request that adds or drops a
Node.js major. Each PR carries its own toolchain pin change in
`docker/pins/toolchains.yml` (an add's new series pin, a drop's removed one)
and is merged by a human. The one exception is the `node` pin of the
`core.node` major: the manifest still needs it, so it stays when the ts-node
family drops that major (see
[Language toolchain pins](../operations/version-management.md#language-toolchain-pins)).

## Current out-of-policy versions

As of 2026-11-18: **none.** The manifest builds 26, 24 and 22, the window.
Under `pr` automation, a major that leaves the window is dropped through a
lifecycle pull request, so none is kept out of policy; the manifest lags
upstream only while such a PR waits for a human to merge it. The open
lifecycle PRs (branches `lifecycle/ts-node-add-<major>` and
`lifecycle/ts-node-drop-<major>`) show any pending change.
