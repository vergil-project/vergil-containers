# C++ / GCC support policy

Image family: `dev-cpp-gcc`, the C++ image built with the GCC compiler. Shared
rules: [Language version lifecycle](lifecycle.md). Upstream facts on this page
were checked on 2026-10-21.

## Upstream source of truth

- **Official:** the [GCC home page](https://gcc.gnu.org/), whose "Supported
  Releases" list names the maintained release series, the [GCC
  Releases](https://gcc.gnu.org/releases.html) page, and the [GCC Development
  Plan](https://gcc.gnu.org/develop.html) for version numbering.
- **Debian packages:** the image installs GCC from Debian, so what the base
  can install comes from the Debian source package pages, for example
  [`gcc-14`](https://sources.debian.org/src/gcc-14/) and
  [`gcc-15`](https://sources.debian.org/src/gcc-15/).
- **endoflife.date product:** none. endoflife.date has no product for GCC.

Data, from those pages:

- The GCC home page lists three maintained release series, each with the
  status "regression fixes & docs only": GCC 16 (16.2, 2026-08-07), GCC 15
  (15.3, 2026-06-12) and GCC 14 (14.4). GCC 17 is in general development.
- The GCC 13 page says: "This release series is no longer supported." Its last
  release is 13.5.
- Since GCC 5, the major version is bumped for each release. `X.0` versions are
  development snapshots, and `X.1.0` is the first release of a major.
- Debian trixie, the image's base, packages `gcc-12`, `gcc-13` and `gcc-14`.
  `gcc-15` and `gcc-16` are packaged only in forky (testing) and sid
  (unstable).

## Support rule

**Judgment:** the release series that gcc.gnu.org lists as maintained, limited
to those the image's Debian base packages. GCC publishes no rule for how many
series it maintains, or when a series closes, so this rule is the policy
author's call. It relies on the "Supported Releases" list on the GCC home page
as the record of what is maintained.

On 2026-10-21 that is 14 only. GCC 15 and 16 are maintained upstream, but
Debian trixie cannot install them.

## What counts as GA

The `X.1.0` release of a new major, listed on the GCC Releases page.
Development snapshots (`X.0`) are never GA. A GA major can be added only once
the Debian base packages it.

## Adapter quirks

- The image is built `FROM debian:trixie-slim`, and GCC is installed from
  Debian as `gcc-<major>`. `GCC_VERSION` is the build argument.
- There is no endoflife.date data. The adapter reads gcc.gnu.org and must fail
  loud if the page cannot be parsed.
- A newer GCC usually needs a newer Debian base. The adapter reports "a newer
  upstream version exists but the base can't install it" (blocked) separately
  from "behind".
- Versions are compared at the major. The `gcc-` token prefix is ignored for
  ordering.

## Deployed runtime package

**No.** C++ compiles to native binaries, so deployed code needs no runtime
package.

## Automation

**`report`.** The lifecycle check reports the gap and tracks it in an issue.

## Current out-of-policy versions

As of 2026-10-21: **13.** It is built, but gcc.gnu.org says the series is no
longer supported. GCC 13 is being dropped in epic
[vergil-project/.github#407](https://github.com/vergil-project/.github/issues/407).

GCC 15 and 16 are **blocked**, not behind: upstream maintains them, but Debian
trixie does not package them.
