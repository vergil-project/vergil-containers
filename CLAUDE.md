# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

<!-- vergil:template:claude-md:begin -->
## Memory

Never write, edit or delete memory files without explicit human approval.
Propose the entry and where it belongs first, then wait for the decision.

## Worktrees

- Sessions always start at the project root, never inside `.worktrees/`.
- One worktree per issue: `.worktrees/issue-<N>-<slug>/` on branch
  `feature/<N>-<slug>`. Remove it once its branch lands.
- The main worktree is read-only; every edit goes through a worktree.
- Read, Edit and Write use the worktree's absolute path. Bash commands `cd`
  into the worktree first or use absolute paths.
- The full convention: <https://github.com/vergil-project/vergil-tooling/blob/develop/docs/specs/worktree-convention.md>.
- Brief each parallel sub-agent with its [Agent prompt contract](https://github.com/vergil-project/vergil-tooling/blob/develop/docs/specs/worktree-convention.md#agent-prompt-contract).

## Git and GitHub

Use `vrg-git` and `vrg-gh` only; the hook guard blocks raw `git` and `gh`. If a
command is not available through the wrappers, explain why and ask the human to
run it with `! <command>` in the prompt.

## Validation

`vrg-container-run -- vrg-validate` is the only validation command. Don't run
linters, formatters or tests outside it; a tool it doesn't invoke is not part
of the pipeline.

## PR handoff

- Agents never run `vrg-submit-pr`. Submitting, merging and finalizing a PR are
  human actions.
- Hand off with `vrg-pr-workflow report-ready --issue <N> --title --summary
  --notes`. It pushes the branch itself. Leave `--linkage` at its default (`Ref`).
- A delta touching `.github/workflows/**` makes GitHub refuse the agent push.
  That is expected: report-ready records the state anyway and the human's
  `vrg-submit-pr` pushes the branch.
- After report-ready the branch is frozen: no new commits and no push that
  advances it; more work is a new follow-up issue. Re-running report-ready to
  fix the prose is allowed. `vrg-pr-workflow unfreeze` is the only way to lift it.
- The report-ready title, summary and notes are public (the relay ref is
  world-readable): never put secrets in them.

## Local settings

`.claude/settings.local.json` must stay absent or exactly `{}`; the agent tools
refuse otherwise. See the [ownership model](https://github.com/vergil-project/vergil-tooling/blob/develop/docs/site/docs/guides/claude-config-ownership.md).

## Engineering principles

- Correctness over cost over speed. Never ship known-broken code with a
  follow-up fix; if something is wrong, fix it now.
- No silent failures: no swallowed exceptions, no `except: return ""`, no
  fallbacks that hide errors. A failure hidden in code becomes a hallucination
  at the AI layer.

## paad

paad usage policy and deviations:
<https://github.com/vergil-project/vergil-claude-plugin/blob/develop/docs/paad-policy.md>.
<!-- vergil:template:claude-md:end -->

## Project overview

vergil-containers builds the dev container images (`dev-<language>` and
`prod-<language>` on GHCR) that CI and local Docker-first development use
across every managed repository: a language runtime plus the shared tooling
layer. Architecture, image layout, publishing and design principles:
[architecture](docs/site/docs/architecture/index.md); the per-image tool
inventory: [images](docs/site/docs/images/index.md). Host setup for the
`vrg-*` tools: [consuming-repo setup](https://github.com/vergil-project/vergil-tooling/blob/develop/docs/site/docs/guides/consuming-repo-setup.md).

## Building images locally

```bash
docker/build.sh                 # Build all images for every version in the matrix
```

`build.sh` auto-detects the runtime — it prefers `nerdctl` (Lima +
containerd) and falls back to `docker`. Set `VRG_CONTAINER_RUNTIME` to
force one. The single-image command below works with either `nerdctl
build` or `docker build`.

Individual images can be built with:

```bash
docker/generate.sh python
docker build --build-arg PYTHON_VERSION=3.14 -t dev-python:3.14 docker/python/
```

Each `Dockerfile.template` pulls shared fragments from `docker/common/` via
`# @include` directives; `generate.sh` expands them into the gitignored
`Dockerfile`.

## Language versions

Every language version list is generated from
[`docker/versions/manifest.yml`](docker/versions/manifest.yml). Edit the
manifest, never a generated list, then run `docker/versions/generate.py`
(CI runs `generate.py --check`). See the
[Language version lifecycle](docs/site/docs/languages/lifecycle.md).

## Tool versions

Never hardcode a tool version list here. Ten binary-download tools are
auto-managed (bumped daily by the `upstream-refresh` job). Every pin, auto-managed
or held, is recorded with its justification in `docker/pins/pins.yml`, and a CI
gate blocks any undocumented pin. Current state:
[`docker/pins/CATALOG.md`](docker/pins/CATALOG.md); doctrine:
[Tool Version Management](docs/site/docs/operations/version-management.md).

## Key references

Sibling repositories: `../vergil-tooling` (the `vrg-*` CLI tools and
validators) and `../vergil-claude-plugin` (Claude Code plugin: hooks, skills).
