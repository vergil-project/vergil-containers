# C++ / Clang support policy

Image family: `dev-cpp-clang`, the C++ image built with the Clang compiler.
Shared rules: [Language version lifecycle](lifecycle.md). Upstream facts on
this page were checked on 2026-10-21.

## Upstream source of truth

- **Official:** the [`llvm/llvm-project`
  releases](https://github.com/llvm/llvm-project/releases) on GitHub, LLVM's
  [How To Release LLVM](https://llvm.org/docs/HowToReleaseLLVM.html), and the
  [LLVM Debian/Ubuntu packages](https://apt.llvm.org/) site, which is where the
  image installs Clang from.
- **endoflife.date product:** none. endoflife.date has no product for LLVM,
  Clang or GCC.

Data, from those pages:

- LLVM says it "is released on a time-based schedule — with major releases
  roughly every 6 months", followed by a series of bug-fix releases.
- The first final release of a major is `X.1.0`. Its release candidates are
  tagged `llvmorg-X.1.0-rcN` and marked as pre-releases.
- The newest releases are 23.1.0 (2026-08-25) through 23.1.4 (2026-10-20). The
  last 22 release is 22.1.8 (2026-06-16), before 23.1.0 shipped.
- apt.llvm.org says it publishes packages for "the last 2 LLVM releases" and
  for `main`, the development branch. For Debian trixie it lists
  `llvm-toolchain-trixie-23` (stable), `llvm-toolchain-trixie-22` (old-stable)
  and `llvm-toolchain-trixie` (the development branch, currently 24).
- LLVM does not publish an EOL date, or a rule for how long a major is
  supported. Its release list shows that bug-fix releases stop on the older
  major once a newer major ships.

## Support rule

**Judgment:** the newest LLVM major and the one before it (newest and
newest−1), limited to the majors that apt.llvm.org publishes for the image's
Debian base. LLVM has no written support rule, so this rule is the policy
author's call. It matches what apt.llvm.org publishes, and is one version wider
than the single major that still gets bug-fix releases, for the same reason as
[Rust](rust.md).

On 2026-10-21 that is 23 and 22.

## What counts as GA

The `llvmorg-X.1.0` release on GitHub, not marked as a pre-release. Release
candidates are never GA. A GA major can be added only once apt.llvm.org
publishes it for the Debian base.

## Adapter quirks

- The image is built `FROM debian:trixie-slim`, and Clang is installed from the
  `llvm-toolchain-trixie-<major>` suite on apt.llvm.org. `CLANG_VERSION` is the
  build argument.
- There is no endoflife.date data. The adapter reads the GitHub releases API
  for `llvm/llvm-project` and must skip pre-releases.
- The adapter must check that apt.llvm.org publishes a suite for the major on
  the Debian base. When it does not, the version is reported as blocked, not as
  behind.
- Versions are compared at the major. The `clang-` token prefix is ignored for
  ordering.

## Deployed runtime package

**No.** C++ compiles to native binaries, so deployed code needs no runtime
package.

## Automation

**`report`.** The lifecycle check reports the gap and tracks it in an issue.

## Current out-of-policy versions

As of 2026-10-21: **20 and 19.** Both are built, but neither is among the two
newest majors, and neither gets bug-fix releases from upstream. apt.llvm.org no
longer lists them for trixie. They stay buildable under the report-only
exception until Clang's automation is turned on.

The manifest is also **behind**: 23 and 22, the majors the rule requires, are
not built.
