# Rust support policy

Image family: `dev-rust`. Shared rules: [Language version
lifecycle](lifecycle.md). Upstream facts on this page were checked on
2026-10-21.

## Upstream source of truth

- **Official:** the Rust [security
  policy](https://www.rust-lang.org/policies/security) and the Rust book's
  [How Rust is Made](https://doc.rust-lang.org/book/appendix-07-nightly-rust.html)
  appendix.
- **endoflife.date product:** `rust` ([page](https://endoflife.date/rust),
  [API](https://endoflife.date/api/rust.json)).

Data, from those pages:

- The security policy says: "The Rust project only provides support and
  security updates for the most recent stable release".
- The Rust book says Rust "releases every six weeks, like clockwork". It also
  says that when a new stable version is released, the old version reaches its
  EOL, so "each version is supported for six weeks".
- endoflife.date lists 1.99 (released 2026-10-01) as the only supported
  release, and 1.98 (released 2026-08-20) as EOL on 2026-10-01.

## Support rule

The newest stable release and the one before it (newest and newest−1). This
was decided in epic
[vergil-project/.github#407](https://github.com/vergil-project/.github/issues/407)
(spec §5.1).

**Judgment:** this is one version wider than upstream, which supports only the
newest stable. The extra version absorbs the six-week cadence, so a consumer is
not forced to move on the day a release ships. It conflicts with rule 1 (never
support a version upstream has stopped supporting) for at most one release
cycle. That is accepted because the older version was supported until the day
the newer one shipped.

On 2026-10-21 that is 1.99 and 1.98.

## What counts as GA

The stable `1.N.0` release. Beta and nightly builds are pre-releases and never
GA. In endoflife.date, a cycle is GA once its `releaseDate` is on or before the
day of the check.

## Adapter quirks

- The image is built `FROM rust:<version>-slim`, the official Docker image,
  with `RUST_VERSION` as the build argument.
- Rust has the fastest cadence of any supported language, a new stable release
  every six weeks. That is where an automated add and drop pull request saves
  the most effort.
- Upstream EOL comes with the next release, not on a fixed date. The adapter
  computes the window from release order, not from EOL dates.
- A repo's `rust-toolchain.toml` chooses a toolchain behind Vergil's back
  (rule 13). It is handled when Rust's automation is turned on.

## Deployed runtime package

**No.** Rust compiles to native binaries, so deployed code needs no runtime
package.

## Automation

**`report`.** The lifecycle check reports the gap and tracks it in an issue.
Rust is next in the queue for `pr` automation.

## Current out-of-policy versions

As of 2026-10-21: **1.93 and 1.92.** Both are built, and both are past
upstream EOL (endoflife.date: 1.93 on 2026-03-06 and 1.92 on 2026-01-22). They
stay buildable under the report-only exception until Rust's automation is
turned on.

The manifest is also **behind**: 1.99 and 1.98, the versions the rule
requires, are not built.
