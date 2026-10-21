# TypeScript / Node.js support policy

Image family: `dev-ts-node`, the TypeScript image built on the Node.js runtime.
Shared rules: [Language version lifecycle](lifecycle.md). Upstream facts on
this page were checked on 2026-10-21.

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

On 2026-10-21 that is 24 and 22. Node.js 26 joins the window when it becomes
LTS on 2026-10-28.

## What counts as GA

**Judgment:** a Node.js major is GA for Vergil on its LTS start date, not on
its initial release. A major in its _Current_ (or, from 27, _Alpha_) phase is
treated like a pre-release. In endoflife.date, the `lts` field holds the LTS
start date, or `false` for a major that never becomes LTS. A major is GA once
that date is on or before the day of the check.

## Adapter quirks

- The image is built `FROM debian:trixie-slim`, and Node.js is installed from
  the NodeSource apt channel with its `setup_<major>.x` script. `NODE_MAJOR` is
  the build argument. A new major can be added only once NodeSource publishes
  it, which the adapter must check before proposing an add.
- endoflife.date's `lts` field is either a date or `false`, and the adapter
  must handle both.
- The separate Node.js pin in `vergil-vm` must line up with this window.

## Deployed runtime package

**No.** Vergil has no deployed TypeScript application today. The need for a
runtime package is assessed when one exists.

## Automation

**`report`.** The lifecycle check reports the gap and tracks it in an issue.

## Current out-of-policy versions

As of 2026-10-21: **none.** The manifest builds 24 and 22, which are both LTS
and not EOL.

Node.js 26 becomes LTS on 2026-10-28. From that day the manifest is behind
until 26 is built.
