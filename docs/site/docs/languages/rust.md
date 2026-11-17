# Rust support policy

Image family: `dev-rust`. Shared rules: [Language version
lifecycle](lifecycle.md). Upstream facts on this page were checked on
2026-11-15.

## Upstream source of truth

- **Official:** the Rust [security
  policy](https://www.rust-lang.org/policies/security) and the Rust book's
  [How Rust is Made](https://doc.rust-lang.org/book/appendix-07-nightly-rust.html)
  appendix.
- **Rust release channel:** the stable channel manifest,
  [`channel-rust-stable.toml`](https://static.rust-lang.org/dist/channel-rust-stable.toml),
  names the current stable release. The [release
  notes](https://doc.rust-lang.org/stable/releases.html) list each release
  with its date.
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
- The Rust release channel's stable manifest, dated 2026-11-12, already
  carries 1.100, which endoflife.date did not list yet. endoflife.date lags
  Rust's own releases, so the lifecycle check takes new series from the
  stable channel (see [Adapter quirks](#adapter-quirks)).

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

On 2026-11-15, read from the stable channel, that is 1.100 and 1.99.

## What counts as GA

The stable `1.N.0` release. Beta and nightly builds are pre-releases and never
GA. A series is GA once its release date is on or before the day of the check:
endoflife.date's `releaseDate` for a cycle it lists, otherwise the `date` of
the `1.N.0` release's channel manifest.

## Adapter quirks

- New series come from Rust's stable channel, not from endoflife.date, which
  can lag a release by days. The adapter reads the stable channel's release
  and adds every series after endoflife.date's newest cycle, up to the stable
  one, with its `.0` release's channel manifest `date` as its GA date.
  endoflife.date stays the cross-check and the source of every other date. A
  cycle it lists as newer than the stable release and dated on or before it
  contradicts the channel, and the check fails for Rust. A newer cycle dated
  after the stable release has not shipped, and is left out. The channel
  manifests are read with the toolchain pins' own fetchers in
  `docker/pins/resolve_toolchains.py`.

- The image is built on `base`, with `RUST_VERSION` (the series) as the build
  argument. It installs the series' exact Rust release, pinned in
  `docker/pins/toolchains.yml`, with a pinned `rustup-init` whose SHA-256 is
  checked per architecture. A version is installable when the Rust release
  channel has a manifest for it (`channel-rust-<version>.toml`); the adapter
  reads it with the toolchain pins' own fetcher.
- A prebuilt Rust tool carries its digests in source, as `rustup-init`
  does. `cargo-nextest` installs from nextest's release tarball, and its
  fragment, `docker/common/cargo-nextest.dockerfile`, pins one SHA-256 per
  architecture (`CARGO_NEXTEST_SHA256_AMD64` and `_ARM64`) beside
  `CARGO_NEXTEST_VERSION`. The build checks the tarball against the pinned
  digest, never against a checksum downloaded with it, and a mismatch fails
  the build. The daily upstream refresh writes the new digests from the
  release's per-asset `.sha256` in the same run that moves the version, so a
  refresh pull request shows both changes together (epic
  [vergil-project/.github#1165](https://github.com/vergil-project/.github/issues/1165),
  spec §6.3). A release with no checksum, or a bad one, for either
  architecture fails the refresh, which then writes nothing.
- `cargo-deny` follows the same pattern. Its fragment,
  `docker/common/cargo-deny.dockerfile`, installs the release's
  `<arch>-unknown-linux-musl` tarball and checks it against
  `CARGO_DENY_SHA256_AMD64` or `_ARM64`, pinned beside
  `CARGO_DENY_VERSION`. The refresh writes the digests from the release's
  per-asset `.tar.gz.sha256`.
- `cargo-llvm-cov`'s release assets have no checksum files, and their names
  carry no version, so it is built from crates.io instead. Its fragment,
  `docker/common/cargo-llvm-cov.dockerfile`, runs
  `cargo install --locked cargo-llvm-cov@${CARGO_LLVM_COV_VERSION}`. Cargo
  checks the crate against the crates.io index's checksum, and `--locked`
  builds it from its published lockfile. The refresh moves
  `CARGO_LLVM_COV_VERSION` like any other auto-managed pin.
- All three are validation tools: they decide whether a Rust repo passes its
  gate. So each one is pinned in source and moved only by the daily upstream
  refresh, in a fenced PR that merges itself once CI passes, never installed
  at whatever version is latest on the day of the build.
  This reverses the WS2 audit (#418), which had left the `cargo install`
  tools unpinned; `docker/pins/pins.yml` records the reversal and the reason.
- Rust has the fastest cadence of any supported language, a new stable release
  every six weeks. That is where an automated add and drop pull request saves
  the most effort.
- Upstream EOL comes with the next release, not on a fixed date. The adapter
  computes the window from release order, not from EOL dates.
- A repo's `rust-toolchain.toml` (or legacy `rust-toolchain`) would choose a
  toolchain behind Vergil's back (rule 13), so `vrg-validate` treats one at
  the repo root as an error; the fix is to delete it. The image also pins
  rustup to its own release (`RUSTUP_TOOLCHAIN`, with auto-install off), so a
  toolchain file cannot select or download another toolchain (see
  [Rust](../images/index.md#rust)). A repo that needs a component or target
  the image lacks gets it through a vergil-containers change, never through a
  toolchain file.

## Deployed runtime package

**No.** Rust compiles to native binaries, so deployed code needs no runtime
package.

## Automation

**`pr`.** The lifecycle check opens the pull request that adds or drops a Rust
version. Each PR carries its own toolchain pin change in
`docker/pins/toolchains.yml` (an add's new series pin, a drop's removed one)
and is merged by a human.

## Current out-of-policy versions

As of 2026-11-15: the manifest builds 1.99 and 1.98, the two newest releases
endoflife.date lists. The stable channel already carries 1.100 (see the data
above), so the window is 1.100 and 1.99: 1.100 is missing and 1.98 is out of
policy until the lifecycle pull requests that add 1.100 and drop 1.98 are
merged.

Under `pr` automation, a new release is added and a version that leaves the
window is dropped through a lifecycle pull request, so the manifest is out of
policy only while such a PR waits for a human to merge it. The open lifecycle
PRs (branches `lifecycle/rust-add-<x.y>` and `lifecycle/rust-drop-<x.y>`) show
any pending change.
