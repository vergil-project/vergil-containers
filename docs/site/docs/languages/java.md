# Java support policy

Image family: `dev-java`, built on Eclipse Temurin. Shared rules: [Language
version lifecycle](lifecycle.md). Upstream facts on this page were checked on
2026-10-21.

## Upstream source of truth

- **Official:** the Eclipse Adoptium [support
  page](https://adoptium.net/support/), which holds the Temurin release roadmap.
- **endoflife.date product:** `eclipse-temurin`
  ([page](https://endoflife.date/eclipse-temurin),
  [API](https://endoflife.date/api/eclipse-temurin.json)).

Data, from those pages:

- Adoptium says that "every two years since 2021 one feature release will be
  designated as a Long Term Supported (LTS) release."
- The Adoptium roadmap gives an end-of-availability date for each LTS release,
  stated as a minimum: Java 25 at least to September 2031, Java 21 at least to
  December 2029, Java 17 at least to October 2027, and Java 11 at least to
  October 2027.
- Non-LTS releases have a short life. The roadmap lists Java 26 as ended in
  September 2026, and Java 27 as ending in March 2027.
- endoflife.date gives the same LTS releases with exact dates: 25 (released
  2025-09-22, EOL 2031-09-30), 21 (EOL 2029-12-31) and 17 (EOL 2027-10-31).

## Support rule

LTS releases that are not EOL, subject to the no-backfill rule.

**Judgment:** the spec proposed this window and left it to this policy to
confirm. Non-LTS releases are excluded because each one is replaced within
about six months, which is the churn an LTS-only window avoids. Java 11 and 8
are still supported by Adoptium, but stay out because they are older than the
window's oldest version (no backfill).

On 2026-10-21 that is 25, 21 and 17.

## What counts as GA

The first Temurin general-availability release of an LTS feature version, as
dated by endoflife.date's `releaseDate`. Early-access builds are pre-releases
and never GA. A non-LTS feature release is GA but outside the window.

## Adapter quirks

- The image is built `FROM eclipse-temurin:<version>-jdk`, the official Docker
  image, with `JDK_VERSION` as the build argument. A new version can be added
  only once that tag exists.
- The adapter must read the `lts` flag, because the window rule depends on it.
- Adoptium states EOL as "at least" a month. The adapter uses endoflife.date's
  exact dates and treats a moved date as normal data, not an error.

## Deployed runtime package

**No.** Vergil has no deployed Java application that needs a Vergil-built
runtime. The need for one is assessed when Java's automation is turned on.

## Automation

**`report`.** The lifecycle check reports the gap and tracks it in an issue.

## Current out-of-policy versions

As of 2026-10-21: **none.** The manifest builds 21 and 17, which are both LTS
and not EOL.

The manifest is **behind**: Java 25, an LTS release that has been GA since
2025-09-22, is not built.
