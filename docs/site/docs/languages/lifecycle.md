# Language version lifecycle

Vergil does not choose language versions by hand. Each supported language has
a **support window**: the set of versions Vergil builds images for. The window
comes from the upstream community's own release and end-of-life (EOL) rules.
This page sets out the rules that every language shares. Each language then has
its own policy page, listed at the end, which applies these rules to that
language's upstream.

The design behind this page is epic
[vergil-project/.github#407](https://github.com/vergil-project/.github/issues/407).

## Where the window lives

The window is recorded in one file, the version manifest
[`docker/versions/manifest.yml`](https://github.com/vergil-project/vergil-containers/blob/develop/docker/versions/manifest.yml).
Every other version list in this repository is generated from it: the publish
matrix, `docker/build.sh`, the Dockerfile `ARG` defaults, the package-cleanup
lists and the version tables in the docs. The generator also writes
`docker/versions/window.json`, the published window that consumer repos read
at build time. CI fails if any generated file is out of date with the manifest.

The manifest records **what is built**, and labels each version as in or out of
policy. Each language family also has an **automation** setting:

- **`pr`**: a scheduled lifecycle check opens the pull request that adds or
  drops a version. The manifest and the policy converge, because every
  out-of-policy version is removed.
- **`report`**: the check reports the gap and tracks it in an issue, but does
  not change the manifest. An out-of-policy version stays buildable until a
  human acts. This is a deliberate, temporary exception to rule 1 below for
  languages whose automation has not been turned on yet.

## The lifecycle check

The `language-lifecycle` job in the nightly `ops.yml` workflow runs
`docker/versions/lifecycle/check.py`. For every family, the family's adapter
reads upstream release and EOL data, applies the policy, and compares the
target window with the manifest. Each run writes a matrix report covering every
family, published as the job summary and the `language-lifecycle-report`
artifact. The report also flags a version whose EOL falls within the next 90
days.

What the check does with a gap depends on the family's automation:

- **`pr` families** (Python and Go) get one pull request per change, on a
  branch named `lifecycle/<family>-<kind>-<version>`. A change is an add, a
  drop, or, for Python, a `runtime` change that records a newly published
  `vergil-python` runtime in the manifest. Each PR carries the manifest edit
  and every regenerated file. A rerun refreshes the same PR rather than
  opening a second one, and a PR whose change is no longer reported is closed.
- **`report` families** get one issue per change, titled
  `language lifecycle: <family> <kind> <version>` and labelled
  `language-lifecycle`. A `pr` family also gets an issue for a change no PR
  can carry: a version the base image can't install yet (`blocked`), an EOL
  coming soon, or a missing runtime.

Nothing is ever auto-merged. A person reviews and merges every lifecycle PR.
This repository's pull-request CI does not build images: an add PR's new
images are first built and scanned by the CD publish on `develop` after it
merges. Building images in pull-request CI is deferred to epic
[vergil-project/.github#213](https://github.com/vergil-project/.github/issues/213).

**A failing check is loud.** If an adapter can't fetch or parse upstream data,
the job fails. It still finishes the other families, and it opens or refreshes
one `lifecycle check failing for <family>` issue, which the next clean run
closes. So no open PR and no open `language-lifecycle` issue reliably means
"in sync".

## How consumers use the window

Consumer repos read the published window, `docker/versions/window.json` at the
`v2.1` ref, through vergil-tooling's `vrg-ci-resolve`. It is the single
resolver, called by local validation and by the vergil-actions CI setup alike.
The window is fetched on every run and never cached, and a failed fetch is an
error. For offline work, `VRG_VERSION_WINDOW` names a local `window.json`
instead.

- With no `[ci].versions` in `vergil.toml`, a repo follows the window. A
  `library` repo (`[project].repository-type`) builds every version in the
  window. Any other repository type is an app, and builds only the newest.
- `[ci].versions` is an optional pin. A pinned version that is not in the
  window is a fatal error, and so is an app pin with more than one version.
- C++ and TypeScript are the exception: their versions carry a family prefix
  (`clang-20`, `gcc-14`, `node-24`), so they have no single default and must
  still pin `[ci].versions` until each language's lifecycle turn. A missing
  pin is a fatal error.
- A packaged Python app or library deploys on the newest window version that
  has a published `vergil-python` runtime (the manifest's `runtime_published`
  field). See the [Python policy](python.md).

## The rules

1. **Follow each community.** A language's support policy is based on its
   upstream's own policy, and is compatible with it. Vergil never supports a
   version its community has stopped supporting. Vergil adds its own rules only
   where an upstream has none, and each policy page marks those rules as
   judgment.
2. **GA is the trigger, and adoption is immediate.** Once a version is
   generally available (GA) and supported upstream, Vergil is behind until it
   supports that version. The aim is the leading edge, not the bleeding edge.
3. **No pre-release builds by default.** Betas, release candidates and other
   pre-releases are not GA. Building them was tried before and mostly produced
   noise. A pre-release can be adopted early only as a deliberate, one-off
   decision driven by a real need.
4. **EOL has no exceptions.** At upstream EOL a version is dropped. It gets no
   further updates, and no new Vergil release includes it. Dropping a version
   earlier, when it reaches security-fix-only status, is allowed as a judgment
   call.
5. **Moving forward is the default, and opting out is explicit.** A new version
   reaches every consumer that is not pinned on its next build. If that breaks
   a repo, the fix is to fix forward, or to pin and file an issue. A pin is
   visible technical debt, and a pin that names a dropped version is a fatal
   error.
6. **Derive, don't hand-maintain.** Every version list is generated from the
   manifest, and the manifest is computed from upstream metadata. As little as
   possible depends on a person, or an AI, reading websites.
7. **One shared machine, with an adapter per language.** Every language follows
   the same steps: read upstream, apply the policy, compute the target window,
   then change it. A language's quirks live in that language's adapter, never in
   the shared code.
8. **Work at `x.y` and ignore the patch level.** Versions are compared at
   `x.y`, or at the major for languages numbered by whole majors (Java, Node,
   Clang, GCC). A pin of `3.14` is satisfied by any 3.14 patch release. Version
   order is semantic-version order.
9. **No special handling for major-version jumps.** A new major version is
   adopted like any other version. Anything that breaks is pinned and handled
   as usual.
10. **Vergil does not track who uses which version.** Finding every consumer of
    a version does not scale. Consumers enforce EOL instead: a repo that pins a
    dropped version fails its own build.
11. **Leading edge over trailing edge.** Keeping support current means staying
    on the leading edge, and the price is deliberately giving up the trailing
    edge.
12. **No backfill.** The window grows only at the top, through new GA releases.
    A version older than the window's current oldest is never added, even if
    upstream still supports it. Python 3.11 and Java 11 are both examples. The
    rule is enforced once, in the shared machinery.
13. **Vergil owns which toolchain runs, and a language's own files declare only
    a floor.** Settings that choose a toolchain version (for example
    `.python-version` or `rust-toolchain.toml`) duplicate Vergil and are
    removed. Settings that declare a minimum (for example `requires-python` or
    the `go` directive in `go.mod`) are kept, as a floor with no upper bound.
    Settings that choose only where a toolchain comes from, such as uv's
    `python-preference` and `python-downloads`, are not version pins and may
    stay. Vergil sets the source itself wherever it runs Python, with
    `UV_PYTHON_PREFERENCE=only-system`, and names the resolved version with
    `UV_PYTHON` wherever it has one. So the image's interpreter is always the
    one used.

## How to read a policy page

Every policy page has the same seven sections:

1. **Upstream source of truth:** the official page for releases and EOL, plus
   the [endoflife.date](https://endoflife.date/) product where one exists.
   endoflife.date is a community aggregator. The lifecycle check reads it, and
   each policy confirms its facts against the official page.
2. **Support rule:** the rule that determines the window.
3. **What counts as GA:** the release that makes a version eligible.
4. **Adapter quirks:** what the language's adapter must handle beyond the
   shared rules.
5. **Deployed runtime package:** whether deployed code needs a Vergil runtime
   package for each version, as Python does with `vergil-python`.
6. **Automation:** `pr` or `report`, as recorded in the manifest.
7. **Current out-of-policy versions:** a snapshot, on the date the page was
   checked, of manifest versions the policy says should not be built. Versions
   upstream has released that the manifest lacks are noted too. The lifecycle
   check's report is the live record.

Each page separates **data**, meaning what an upstream source actually says,
from **judgment**, meaning a rule Vergil chose where upstream has none. Every
upstream fact cites its source and the date it was checked.

## Policies

| Family | Automation | Policy |
|---|---|---|
| `python` | `pr` | [Python](python.md) |
| `go` | `pr` | [Go](go.md) |
| `rust` | `report` | [Rust](rust.md) |
| `java` | `report` | [Java](java.md) |
| `ts-node` | `report` | [TypeScript / Node.js](ts-node.md) |
| `cpp-clang` | `report` | [C++ / Clang](cpp-clang.md) |
| `cpp-gcc` | `report` | [C++ / GCC](cpp-gcc.md) |

Ruby is no longer a supported language. It was removed in epic
[vergil-project/.github#407](https://github.com/vergil-project/.github/issues/407),
so it has no policy page.
