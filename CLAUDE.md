# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Memory management

Memory is allowed with human approval. The authoritative policy is in
the user's global `~/.claude/CLAUDE.md` — agents must propose memory
writes and suggest a destination (repo memory, global CLAUDE.md, or
plugin/skill issue) before writing. See that file for the full
workflow.

Available skills:

- `/vergil:memory-init` — set up or update the policy header
  in a project's `MEMORY.md`.
- `/vergil:memory-audit` — structured collaborative review
  of memory files.

## Parallel AI agent development

This repository supports running multiple Claude Code agents in parallel via
git worktrees. The convention keeps parallel agents' working trees isolated
while preserving shared project memory (which Claude Code derives from the
session's starting CWD).

**Canonical spec:**
[`vergil-tooling/docs/specs/worktree-convention.md`](https://github.com/vergil-project/vergil-tooling/blob/develop/docs/specs/worktree-convention.md)
— full rationale, trust model, failure modes, and memory-path implications.
The canonical text lives in `vergil-tooling`; this section is the local
on-ramp.

### Structure

```text
~/dev/projects/vergil-project/vergil-docker/     ← sessions ALWAYS start here
  .git/
  CLAUDE.md, docker/, …                   ← main worktree (usually `develop`)
  .worktrees/                             ← container for parallel worktrees
    issue-48-adopt-worktree-convention/   ← worktree on feature/48-...
    …
```

### Rules

1. **Sessions always start at the project root.**
   `cd ~/dev/projects/vergil-project/vergil-docker && claude` — never from inside
   `.worktrees/<name>/`. This keeps the memory-path slug stable and shared.
2. **Each parallel agent is assigned exactly one worktree.** The session
   prompt names the worktree (see Agent prompt contract below).
   - For Read / Edit / Write tools: use the worktree's absolute path.
   - For Bash commands that touch files: `cd` into the worktree first,
     or use absolute paths.
3. **The main worktree is read-only.** All edits flow through a worktree
   on a feature branch — the logical endpoint of the standing
   "no direct commits to develop" policy.
4. **One worktree per issue.** Don't stack in-flight issues. When a
   branch lands, remove the worktree before starting the next.
5. **Naming: `issue-<N>-<short-slug>`.** `<N>` is the GitHub issue
   number; `<short-slug>` is 2–4 kebab-case tokens.

### Agent prompt contract

When launching a parallel-agent session, use this template (fill in the
placeholders):

```text
You are working on issue #<N>: <issue title>.

Your worktree is: /Users/pmoore/dev/github/vergil-docker/.worktrees/issue-<N>-<slug>/
Your branch is:   feature/<N>-<slug>

Rules for this session:
- Do all git operations from inside your worktree:
    cd <absolute-worktree-path> && git <command>
- For Read / Edit / Write tools, use the absolute worktree path.
- For Bash commands that touch files, cd into the worktree first
  or use absolute paths.
- Do not edit files at the project root. The main worktree is
  read-only — all changes flow through your worktree on your
  feature branch.
```

All fields are required.

## Project Overview

This repository contains the Docker dev container images for the
VERGIL ecosystem. Each image provides a language runtime plus
shared tooling (Node.js, ShellCheck, markdownlint) used by CI and local
Docker-first development across all managed repositories.

**Project name**: vergil-docker

**Status**: Active

**Standards reference**: <https://github.com/vergil-project/standards-and-conventions>
— historical reference; active standards documentation lives in the
vergil-tooling repository under `docs/`.

## Shell command policy

Use `vrg-git` instead of `git` for all git operations. Use `vrg-gh`
instead of `gh` for all GitHub CLI operations. These wrappers enforce
subcommand allowlists, flag deny lists, credential selection, and
audit logging.

Raw `git` and `gh` are denied by the permission model. If a command
is not available through the wrappers, explain the situation to the
human who can run it directly via `! <command>` in the prompt.

## Development Commands

### Environment Setup

```bash
# Host-installed vergil-tooling provides vrg-* commands on PATH.
# Install per the host-level-tool spec
# (https://github.com/vergil-project/vergil-tooling/blob/develop/docs/specs/host-level-tool.md):
uv tool install 'vergil-tooling @ git+https://github.com/vergil-project/vergil-tooling@v1.4'
# (or `pip install` into the same Python env that hosts `uv`).

# Enable the pre-commit gate (refuses raw `git commit`; admits
# vrg-commit). The gate is vendored at `.githooks/pre-commit` in
# this repo.
git config core.hooksPath .githooks
```

### Validation

```bash
docker/generate.sh              # Expand templates (required before hadolint)
hadolint docker/*/Dockerfile    # Lint Dockerfiles
shellcheck docker/build.sh docker/generate.sh  # Lint shell scripts
markdownlint .                  # Lint Markdown
```

### Building Images Locally

```bash
docker/build.sh                 # Build all images for every version in the matrix
```

Individual images can be built with:

```bash
docker/generate.sh python
docker build --build-arg PYTHON_VERSION=3.14 -t dev-python:3.14 docker/python/
```

## Architecture

### Image Layout

```text
docker/
  build.sh                    # Builds all images locally
  generate.sh                 # Expands Dockerfile.template → Dockerfile
  common/                     # Shared fragments included via # @include
  base/Dockerfile.template    # Base dev image (all common tools, no runtime)
  python/Dockerfile.template  # Python dev image with uv
  java/Dockerfile.template    # Java dev image, Eclipse Temurin
  go/Dockerfile.template      # Go dev image with linters
  ruby/Dockerfile.template    # Ruby dev image with bundler
  rust/Dockerfile.template    # Rust dev image with cargo tools
```

Each `Dockerfile.template` contains `# @include common/<fragment>.dockerfile`
directives. `generate.sh` expands these to produce the final `Dockerfile`
(which is gitignored). Run `docker/generate.sh` before `hadolint`.

### Common Layer

Every image includes (installed via shared fragments in `docker/common/`):

- **Node.js 22** (via NodeSource apt repository)
- **markdownlint-cli** (`0.48.0`)
- **ShellCheck** (`0.11.0`)
- **shfmt** (`3.13.1`)
- **actionlint** (`1.7.12`)
- **git-cliff** (`2.13.1`)
- **hadolint** (`2.14.0`)
- **scorecard** (`5.5.0`)
- **gh** (GitHub CLI, via official apt repository)
- **uv** (`0.11.13`)
- **yamllint** (`1.38.0`)
- **jq**, git, curl, openssh-client
- Language-specific package manager and linting tools

The `dev-base` image includes additional documentation tooling (MkDocs
Material, mike, semgrep). See the
[images documentation](https://vergil-project.github.io/vergil-docker/images/)
for the full inventory.

### GHCR Publishing

Images are published as multi-architecture manifests (amd64 + arm64) to
GitHub Container Registry via the reusable `cd-docker-publish.yml`
workflow, parameterized by an `image-prefix` input:

- **`dev-` images** — built on every push to `develop` and rebuilt
  nightly via `ops.yml` to pick up base-image security patches.
- **`prod-` images** — built on push to `main`, after the release
  workflow generates a changelog, git tag, and GitHub release.

Image naming: `ghcr.io/vergil-project/{prefix}-{language}:{version}`
where `{prefix}` is `dev` or `prod`.

Image URLs use the **user namespace** (`ghcr.io/vergil-project/...`), not a
repo-specific namespace. This means image paths are stable across repo
migrations — they do not change when the publishing repository changes.

The publish pipeline builds a candidate tag, scans both platforms with Trivy,
attests build provenance (SLSA), then promotes the candidate to the final tag
via `docker buildx imagetools create`.

#### Publishing prerequisites

The workflow uses `secrets.GITHUB_TOKEN` with `packages: write` permission.
No PAT or additional secret is needed. However, each GHCR package must
explicitly grant this repository write access because the packages were
originally created by the `vergil-tooling` repository.

Per-package setup (one-time, for each of `dev-base`, `dev-python`, `dev-java`,
`dev-go`, `dev-ruby`, `dev-rust`, and the corresponding `prod-` packages):

1. Navigate to the package settings page on GHCR.
2. Under **Manage Actions access**, click **Add Repository**.
3. Select `vergil-docker`.
4. Set role to **Write**.

### Version Matrix

| Language | Versions         |
| -------- | ---------------- |
| Ruby     | 3.2, 3.3, 3.4    |
| Python   | 3.12, 3.13, 3.14 |
| Java     | 17, 21           |
| Go       | 1.25, 1.26       |
| Rust     | 1.92, 1.93       |

To trigger a rebuild manually: Actions > CD > Run workflow.

### Design Principles

- **Thin images** — language runtime + package manager + git/curl
- **Project-managed dependencies** — tools come from lockfiles at
  container startup (e.g., `bundle install`, `uv sync`, `go install`)
- **No host requirements** — Docker is the only prerequisite for
  local development

## Key References

**Sibling repositories**:

- `../vergil-tooling` — Python CLI tools and bash validators
- `../vergil-claude-plugin` — Claude Code plugin (hooks, skills, agents)
