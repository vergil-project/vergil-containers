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

# Validate the resolved runtime — covers both the override and the
# auto-detect paths, so a typo'd or uninstalled VRG_CONTAINER_RUNTIME
# fails here with a clear message rather than later as a raw
# "command not found".
if ! command -v "$runtime" >/dev/null 2>&1; then
  echo "ERROR: container runtime '$runtime' not found on PATH" \
       "(set VRG_CONTAINER_RUNTIME to nerdctl or docker, or leave it unset" \
       "to auto-detect)" >&2
  exit 1
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
- **No silent failure:** if neither runtime exists — or an overridden
  runtime is not installed — the script exits non-zero with a clear message
  rather than falling through. The override is *not* restricted to a fixed
  allow-list, so a deliberate alternative OCI runtime (e.g. `podman`) is
  still possible; it just has to actually be on PATH.

### Command substitution

Replace the three hard-coded `docker` invocations with `"$runtime"`:

| Current | New |
| --- | --- |
| `docker build --build-arg … -t … <dir>` | `"$runtime" build --build-arg … -t … <dir>` |
| `docker image prune -f` | `"$runtime" image prune -f` |
| `docker builder prune -af --filter 'until=720h'` | runtime-aware (below) |

`nerdctl build` requires `buildkitd` to be running; `image prune -f` is
identical across both runtimes. The buildkit dependency is handled by an
explicit precondition check (below) rather than left to surface as a raw
build error.

### Buildkit precondition (nerdctl only)

`nerdctl build` fails if `buildkitd` is not reachable. buildkit is confirmed
present in the current Lima setup (rootless containerd worker), but nothing
*in this repo* guarantees it — a freshly provisioned or differently
configured Lima VM could lack it. Rather than let the first `build` call die
with nerdctl's native error, `build.sh` probes buildkit up front (only when
the runtime is `nerdctl`) and exits with a remediation message if it is
unreachable:

```bash
if [ "$runtime" = "nerdctl" ]; then
  if ! nerdctl info >/dev/null 2>&1; then
    echo "ERROR: nerdctl cannot reach its containerd/buildkit backend." \
         "Ensure the Lima VM is running and provisions buildkitd" \
         "(see the vergil-vm Lima template). To use Docker instead," \
         "set VRG_CONTAINER_RUNTIME=docker." >&2
    exit 1
  fi
fi
```

`nerdctl info` is a cheap round-trip that fails when the VM/containerd/
buildkit backend is not reachable, turning a cryptic mid-build failure into
an actionable up-front error.

**Handoff:** the `vergil-vm` Lima template must guarantee `buildkitd` is
installed and running so `nerdctl build` works out of the box. This is the
real owner of the dependency; track it against `vergil-vm` rather than
papering over it here. This spec only ensures `build.sh` *fails informatively*
when the guarantee is not met.

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

- `docker/build.sh` header comment: it currently states "dangling images and
  stale build cache (>30 days) are pruned". After the change that is true only
  on docker, so reword it to describe the runtime-aware behaviour — e.g.
  "dangling images are pruned; build-cache pruning is runtime-aware — docker
  prunes cache older than 30 days, nerdctl prunes dangling cache only
  (`nerdctl builder prune` has no `--filter`)". Keeps the comment honest at
  the point of use.
- `CLAUDE.md`: the "**No host requirements — Docker is the only
  prerequisite for local development**" design principle and the
  `docker build --build-arg …` example are reworded to reference "an OCI
  runtime (nerdctl / Lima preferred, Docker supported)".
- `README.md`: soften any "install Docker" prerequisite language the same
  way.

## Validation

- `vrg-container-run -- vrg-validate` — shellcheck / shfmt must pass on the
  edited `build.sh`.
- Manual round-trip under `nerdctl`: run `build.sh` end-to-end for at least
  one image, then confirm the result is not just *built* but *usable* by the
  run path:
  - the tag appears in `nerdctl images`, **and**
  - it is consumable downstream — `vrg-container-run` against the freshly
    built tag (or a plain `nerdctl run … <tag>`) succeeds.
  - This guards against the namespace gap: nerdctl + buildkit loads images
    into a containerd namespace, and a "successful" build is worthless if the
    run path reads a different namespace. The round-trip proves build → run
    continuity, not just build success.
- Precondition behaviour: with `buildkitd` stopped/unreachable, confirm
  `build.sh` (under nerdctl) exits with the remediation message rather than a
  raw nerdctl build error.
- Override validation: confirm `VRG_CONTAINER_RUNTIME=<not-installed>` exits
  with the clear "runtime not found on PATH" error.
- Confirm the `VRG_CONTAINER_RUNTIME=docker` code path remains syntactically
  intact for developers who still use Docker (static review; no Docker
  install required to verify the branch).

## Risks and notes

- **buildkitd availability** is the main runtime dependency for `nerdctl
  build`. It is confirmed present in the current Lima setup, and the
  precondition check (see "Buildkit precondition") converts a missing backend
  into an actionable up-front error. The durable fix — guaranteeing buildkitd
  in the Lima VM — is owned by `vergil-vm` and tracked there.
- **Behavioural change on nerdctl prune** is intentional and documented
  above; it is gentler, not more destructive, than the docker path.
