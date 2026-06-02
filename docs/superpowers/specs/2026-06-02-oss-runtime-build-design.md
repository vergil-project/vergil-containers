# Prefer OSS container runtime for local builds

- **Issue:** [#322](https://github.com/vergil-project/vergil-docker/issues/322)
- **Supersedes:** [#71](https://github.com/vergil-project/vergil-docker/issues/71) (Colima research)
- **Date:** 2026-06-02
- **Status:** Design approved

## Goal

Remove the hard requirement to install the **Docker client** for local work
in this repo. `docker/build.sh` should prefer `nerdctl` — the Lima +
containerd runtime already in use locally — and fall back to `docker` only
if that is what a developer has installed. Nothing you must pay for should be
required on a local macOS box to build these images.

This is the implementation successor to the #71 investigation. That issue
evaluated Colima as a Docker Desktop replacement; the local setup has since
moved to Lima + nerdctl over containerd, which makes the original
comparison moot. The remaining local hard dependency on the Docker client in
this repo is `docker/build.sh`.

## Scope

In scope, **this repo only**:

- `docker/build.sh` — the one standalone local script that hard-codes `docker`.
- Documentation that presents Docker as a hard prerequisite.

Explicitly **out of scope** (tracked elsewhere):

- MQ REST Admin `dev-environment/scripts/mq_*.sh` (`docker compose` for IBM
  MQ) — to be folded into the in-flight migration of MQ integration into the
  `vrg-validate` framework.
- Stale `mq-rest-admin-*/scripts/dev/test-integration.sh` and the dead
  `vrg-docker-test` reference — part of a separate `scripts/dev` cleanup.
- CI publishing (`cd-docker-publish.yml`) — unchanged.

## Convention (ecosystem-wide, recorded here)

This spec implements one repo's slice of a broader convention worth stating
once:

- **Local client prefers the OSS runtime.** `nerdctl` first, `docker` as an
  optional fallback. No one is forced to install — or to uninstall — Docker
  locally.
- **CI / GitHub Actions stays on Docker.** Runners ship Docker Engine
  preinstalled and free; the licensing/installation concern does not apply
  there. Out of scope by design.
- **No renaming churn.** "docker" in script names, paths, and environment
  variable names (`DOCKER_NETWORK`, etc.) stays. Docker is the standard and
  image format; nerdctl and Lima implement it. This is about which binary is
  invoked and what must be installed, not cosmetics.
- **Framework scripts inherit runtime detection for free.** Anything running
  under `vrg-validate` / `vrg-container-*` already uses the Python
  `detect_runtime()` (which prefers `nerdctl`, then `docker`). No per-script
  work is needed there.
- **Standalone bash** uses a small inline detection snippet. We deliberately
  do *not* add a shared `vrg-` helper for this: `build.sh` is meant to be
  runnable with only a container runtime installed (no `vrg-tooling`
  dependency), and it is the only standalone bash script in this repo that
  invokes a runtime.

## Design

### Runtime detection in `docker/build.sh`

Add a short detection block near the top of the script, after `set -euo
pipefail`:

```bash
runtime="${VRG_CONTAINER_RUNTIME:-}"
if [ -z "$runtime" ]; then
  if command -v nerdctl >/dev/null 2>&1; then
    runtime=nerdctl
  elif command -v docker >/dev/null 2>&1; then
    runtime=docker
  else
    echo "ERROR: no container runtime found (need nerdctl or docker)" >&2
    exit 1
  fi
fi
```

Properties:

- **Override:** `VRG_CONTAINER_RUNTIME` lets CI or tests pin a specific
  runtime. The name follows the `vrg-` convention. (The Python
  `detect_runtime()` has no such override today; adding a matching one there
  is a possible future consistency improvement, out of scope here.)
- **Preference:** `nerdctl` before `docker`, matching the Python
  `detect_runtime()` so local behaviour is consistent across the bash and
  framework paths.
- **No silent failure:** if neither runtime exists, the script exits non-zero
  with a clear message rather than falling through.

### Command substitution

Replace the three hard-coded `docker` invocations with `"$runtime"`:

| Current | New |
| --- | --- |
| `docker build --build-arg … -t … <dir>` | `"$runtime" build --build-arg … -t … <dir>` |
| `docker image prune -f` | `"$runtime" image prune -f` |
| `docker builder prune -af --filter 'until=720h'` | runtime-aware (below) |

`nerdctl build` requires `buildkitd`, which is confirmed running in the Lima
environment (rootless containerd worker). `image prune -f` is identical
across both runtimes.

### Builder-cache prune (runtime divergence)

`docker builder prune -af --filter 'until=720h'` keeps build cache newer than
30 days — intentional hygiene related to issue #66. `nerdctl builder prune`
supports only `-a` / `-f`; it has **no `--filter`**, so the age window cannot
be expressed identically.

Resolution — make the prune step runtime-aware:

```bash
if [ "$runtime" = "docker" ]; then
  docker builder prune -af --filter 'until=720h'
else
  # nerdctl has no --filter; prune dangling cache only to preserve
  # reusable layers across builds.
  "$runtime" builder prune -f
fi
```

- On `docker`: unchanged behaviour, preserving the issue #66 hygiene window.
- On `nerdctl`: dangling-only prune is gentler than `-af` (which would purge
  *all* cache and force full rebuilds). Reusable cache is retained on both
  paths. A containerd-native age-based hygiene story, if wanted, is left to
  issue #66.

### Documentation

- `CLAUDE.md`: the "**No host requirements — Docker is the only
  prerequisite for local development**" design principle and the
  `docker build --build-arg …` example are reworded to reference "an OCI
  runtime (nerdctl / Lima preferred, Docker supported)".
- `README.md`: soften any "install Docker" prerequisite language the same
  way.

## Validation

- `vrg-container-run -- vrg-validate` — shellcheck / shfmt must pass on the
  edited `build.sh`.
- Manual: run `build.sh` end-to-end for at least one image under `nerdctl`
  and confirm the image is produced.
- Confirm the `VRG_CONTAINER_RUNTIME=docker` code path remains syntactically
  intact for developers who still use Docker (static review; no Docker
  install required to verify the branch).

## Risks and notes

- **buildkitd availability** is the only real runtime risk for `nerdctl
  build`; it is confirmed present in the current Lima setup. If a developer's
  Lima VM lacks buildkit, `nerdctl build` will error clearly — acceptable,
  and surfaced rather than hidden.
- **Behavioural change on nerdctl prune** is intentional and documented
  above; it is gentler, not more destructive, than the docker path.
