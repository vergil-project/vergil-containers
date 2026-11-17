# TypeScript (Node.js) dev/prod images

Node.js-family TypeScript dev container images for the Vergil ecosystem, built
for epic [vergil-project/.github#284](https://github.com/vergil-project/.github/issues/284)
task T1 (issue vergil-project/vergil-containers#519).

## Toolchain discovery — pinned Node majors

The spec's hard rule (§3.5) is **prebuilt stable binaries only — never built
from source** — and the durable requirement is **two recent LTS majors**. The
concrete majors are whatever is cleanly available prebuilt.

Discovery was first run against `debian:trixie-slim` and the NodeSource apt
channel. Since epic
[vergil-project/.github#649](https://github.com/vergil-project/.github/issues/649)
the image is built on `base` (Ubuntu 24.04), and each major is the official
nodejs.org prebuilt tarball, which its spike installed for both majors on both
architectures:

| Major | Source (prebuilt) | Decision |
| ----- | ----------------- | -------- |
| **24** | nodejs.org tarballs, `linux-x64` and `linux-arm64` | **pinned (primary)** |
| **22** | nodejs.org tarballs, `linux-x64` and `linux-arm64` | **pinned (secondary)** |

The exact release of each major, and the SHA-256 of each architecture's
tarball, are pinned in `docker/pins/toolchains.yml`; the daily upstream refresh
moves each pin to the newest release of its major. npm is the one each tarball
bundles: it is never upgraded in place, so it changes only when the pin moves
(the site's Trivy CVE triage page, `docs/site/docs/operations/trivy-triage.md`).
`node-20` is excluded (EOL Apr 2026), per the epic's global constraints.

**Node 24 is the primary major** — `versions[0]`; the `[once]` TYPECHECK / LINT /
AUDIT stages run on it, and only TEST runs per Node version (spec §3.6). Both
majors are built from the same `Dockerfile.template` via the `NODE_MAJOR`
build-arg.

If a future major is wanted, advance the matrix **only once it is available as a
prebuilt stable binary** (§3.5): the `ts-node` lifecycle adapter proposes a
major only once nodejs.org's release index has a release of it with `linux-x64`
and `linux-arm64` tarballs. The version axis lives in
`docker/versions/manifest.yml` (the `ts-node` family); the publish matrix,
which `docker/build.sh` reads, is generated from it.

## Structure (matches this repo's existing image idiom)

- **`docker/ts-node/Dockerfile.template`** — the Node image. `FROM
  ${PARENT_IMAGE}`, which is `base` (the manifest's `parent:`), so every common
  tool comes from `base`. It unpacks the `NODE_MAJOR` tarball at
  `/opt/node/<major>` after checking its pinned SHA-256, links `node`, `npm` and
  `npx` into `/usr/local/bin`, and sets npm's global prefix to `/usr`, so
  `npm root -g` is `/usr/lib/node_modules`. It then composes
  `common/typescript-analysis.dockerfile`. `markdownlint` stays `base`'s
  wrapper on the core Node at `/opt/vergil/node/<core-major>`, never on this
  family Node.
- **`docker/ts-node/checks.sh`** — the build-time checks, the template's last
  `RUN`: `base`'s invariants, the two `base` defaults the image keeps (`python3`
  is the core Python, no `pip`), the family Node's release and paths, `npm root
  -g`, the `markdownlint` wrapper on the core Node, and the image's TypeScript
  tools (`prettier`, `license-checker`).
- **`common/typescript-analysis.dockerfile`** — the shared, runtime-agnostic
  TypeScript tools every TypeScript image carries: `prettier` and
  `license-checker`. `typescript`, `eslint`, `typescript-eslint`, `vitest` and
  `@vitest/coverage-v8` are not in the image: each repository declares them,
  and Vergil's gates run them from its `node_modules/.bin`, under vergil-tooling's
  [Tool Ownership Guideline](https://vergil-project.github.io/vergil-tooling/latest/standards/development/tool-ownership/)
  (epic [vergil-project/.github#1174](https://github.com/vergil-project/.github/issues/1174)).
  This is plan T1's "shared base layer" ("Dockerfile.base"),
  expressed as an `@include` fragment because language images in this repo
  compose fragments rather than `FROM`-chaining a locally-built base image. The
  node-22 second image (T2) includes the same fragment.
- **`docker/ts-node/smoke/`** + **`docker/ts-node/smoke-test.sh`** — the trivial
  `package.json` + `tsconfig.json` + ESLint + Vitest project used as the
  build-time smoke check. The project declares the repo-side tools; the check
  asserts `tsc`, `eslint` and `vitest` are not on the image's `PATH`, runs
  `npm ci --ignore-scripts`, then `tsc --noEmit`, `eslint .` and one
  `vitest run --coverage` from `node_modules/.bin`, and the image's `prettier`
  and `license-checker` on the project. Shared across the node-24 and node-22
  images.

Images are named `dev-ts-node:<major>` / `prod-ts-node:<major>`, following the
established `{prefix}-{language}:{version}` convention where the `{language}`
token is `ts-node` (the directory name == the image name). This is the name
T5's image resolution (`prod-ts-node:<major>`) and T7's CI workflows consume.

## Building and smoke-testing locally

```bash
docker/build.sh ts-node
docker/ts-node/smoke-test.sh dev-ts-node:24
```

`docker/build.sh ts-node` builds the image's parents (`pkg-ubuntu:24.04`, then
`base`) and every pinned major, each with the build args of its
`docker/versions/matrix.json` entry (`NODE_MAJOR` and the `TOOLCHAIN_*` pins),
and runs the smoke check for each. A manual `nerdctl build` must pass the same
build args and `PARENT_IMAGE`; the build fails if any is missing.
