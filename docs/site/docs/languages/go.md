# Go support policy

Image family: `dev-go`. Shared rules: [Language version lifecycle](lifecycle.md).
Upstream facts on this page were checked on 2026-10-21.

## Upstream source of truth

- **Official:** [Go release history, Release
  Policy](https://go.dev/doc/devel/release#policy).
- **endoflife.date product:** `go` ([page](https://endoflife.date/go),
  [API](https://endoflife.date/api/go.json)).

Data, from those pages:

- The Go release policy says: "Each major Go release is supported until there
  are two newer major releases." Go calls each `1.N` a major release.
- Recent releases: go1.27.0 on 2026-08-19, go1.26.0 on 2026-02-10 and go1.25.0
  on 2025-08-12. Go 1.25 reached end of support when Go 1.27 shipped.
- Go releases have no fixed EOL date. A release's EOL is the GA date of the
  second release after it, so endoflife.date reports `eol: false` for the two
  supported releases.

## Support rule

The two newest releases. This rule matches upstream exactly. It was decided in
epic [vergil-project/.github#407](https://github.com/vergil-project/.github/issues/407)
(spec §5.1).

On 2026-10-21 that is 1.27 and 1.26.

## What counts as GA

The `go1.N.0` release. Release candidates (`go1.N rcN`) are pre-releases and
never GA. In endoflife.date, a cycle is GA once its `releaseDate` is on or
before the day of the check.

## Adapter quirks

- The image is built `FROM golang:<version>`, the official Docker image, with
  `GO_VERSION` as the build argument.
- The image builds with `GOTOOLCHAIN=local`, so the toolchain cannot fetch a
  newer Go to satisfy a tool's `go` directive. A Go tool whose newest release
  needs a newer Go than an image ships is held back for that image only, in a
  `case` block in `docker/go/Dockerfile.template` and an entry in
  `docker/pins/pins.yml`. Adding or dropping a Go version must update those
  per-version holds as well as the manifest.
- An EOL date is not known in advance, so a drop is triggered by the GA of the
  second newer release, not by a date.

## Deployed runtime package

**No.** Go compiles to native binaries, so deployed code needs no runtime
package.

## Automation

**`pr`.** The lifecycle check opens the pull request that adds or drops a Go
version.

## Current out-of-policy versions

As of 2026-10-23: **none.** The manifest builds 1.27 and 1.26, the two
supported releases, so the window is in sync with upstream.
