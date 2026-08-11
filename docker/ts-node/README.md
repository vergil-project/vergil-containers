# TypeScript (Node.js) dev/prod images

Node.js-family TypeScript dev container images for the Vergil ecosystem, built
for epic [vergil-project/.github#284](https://github.com/vergil-project/.github/issues/284)
task T1 (issue vergil-project/vergil-containers#519).

## Toolchain discovery — pinned Node majors

The spec's hard rule (§3.5) is **prebuilt stable binaries only — never built
from source** — and the durable requirement is **two recent LTS majors**. The
concrete majors are whatever is cleanly available prebuilt.

Discovery was run empirically against `debian:trixie-slim` (the Debian release
underlying the other images in this repo) plus the official NodeSource apt
channel (`deb.nodesource.com`):

| Major | Source (prebuilt) | Version observed | npm | Decision |
| ----- | ----------------- | ---------------- | --- | -------- |
| **24** | NodeSource `setup_24.x` | 24.19.0 | 11.17.0 | **pinned (primary)** |
| **22** | NodeSource `setup_22.x` | 22.23.2 | 10.9.8 | **pinned (secondary, T2)** |

Both majors install cleanly as prebuilt stable binaries with npm bundled, so the
target pins (24 and 22) qualify and no fallback is needed. `node-20` is excluded
(EOL Apr 2026) and `node-26` (Oct 2026) is deferred, per the epic's global
constraints.

**Node 24 is the primary major** — `versions[0]`; the `[once]` TYPECHECK / LINT /
AUDIT stages run on it, and only TEST runs per Node version (spec §3.6). This
image (T1) ships node-24; the node-22 second image is added in T2, reusing this
same `Dockerfile.template` via the `NODE_MAJOR` build-arg.

If a future major is wanted, advance the matrix **only once it is available as a
prebuilt stable binary** on this channel (§3.5). The version axis lives in
`docker/build.sh` (the `ts-node` build lines) and the publish matrix.

## Structure (matches this repo's existing image idiom)

- **`docker/ts-node/Dockerfile.template`** — the Node image. `FROM
  debian:trixie-slim`, installs the `NODE_MAJOR` runtime from NodeSource, then
  composes the shared validation fragments (the same set the `rust` image uses,
  minus `node-markdownlint` since this image installs its own runtime Node) plus
  `common/typescript-analysis.dockerfile`.
- **`common/typescript-analysis.dockerfile`** — the shared, runtime-agnostic
  analysis toolset every TypeScript image carries (`typescript`/`tsc`, `eslint` +
  `typescript-eslint`, `prettier`, `vitest` + `@vitest/coverage-v8`,
  `license-checker`). This is plan T1's "shared base layer" ("Dockerfile.base"),
  expressed as an `@include` fragment because language images in this repo
  compose fragments rather than `FROM`-chaining a locally-built base image. The
  node-22 second image (T2) includes the same fragment.
- **`docker/ts-node/smoke/`** + **`docker/ts-node/smoke-test.sh`** — the trivial
  `package.json` + `tsconfig.json` + Vitest project used as the build-time smoke
  check: `npm ci`, `tsc --noEmit`, and one `vitest run` under the image. Shared
  across the node-24 and node-22 images.

Images are named `dev-ts-node:<major>` / `prod-ts-node:<major>`, following the
established `{prefix}-{language}:{version}` convention where the `{language}`
token is `ts-node` (the directory name == the image name). This is the name
T5's image resolution (`prod-ts-node:<major>`) and T7's CI workflows consume.

## Building and smoke-testing locally

```bash
docker/generate.sh ts-node
nerdctl build --build-arg NODE_MAJOR=24 -t dev-ts-node:24 docker/ts-node
docker/ts-node/smoke-test.sh dev-ts-node:24
```

`docker/build.sh` builds the pinned major(s) and runs the smoke check for each.
Manual builds must pass `--build-arg NODE_MAJOR=<major>`; the template's default
(24) documents the primary.
