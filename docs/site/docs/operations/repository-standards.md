# Repository Standards

Standards and conventions specific to the vergil-docker repository.
For ecosystem-wide standards, see the
[vergil-tooling documentation](https://vergil-project.github.io/vergil-tooling/).

## External Tooling Dependencies

The following tools are required for local development and CI:

- **hadolint** — Dockerfile linting
- **shellcheck** — Shell script linting
- **markdownlint** (markdownlint-cli) — Markdown linting

These tools are installed inside the dev container images themselves.
For local development outside containers, install them via your
system package manager or download the binaries.

## CI Gates

### Required status checks on develop

- **Hadolint** — lint all generated Dockerfiles
- **ShellCheck** — lint `docker/build.sh` and `docker/generate.sh`
- **Security and standards** (via `vergil-actions/ci-security`):
  - Semgrep (Dockerfile language rules)
  - Repository profile validation
  - Markdownlint
  - Commit message lint (conventional commits)
  - PR issue linkage validation

### Local pre-commit hooks

The `.githooks/pre-commit` gate enforces:

- **Branch naming** — branching-model-aware prefix validation
- **Commit message format** — conventional commits required

Enable hooks with:

```bash
git config core.hooksPath .githooks
```

## Commit and PR Scripts

AI agents and contributors use wrapper scripts for commits and PR
submission. These enforce formatting standards and co-authorship
attribution.

### Committing

```bash
vrg-commit \
  --type TYPE --scope SCOPE --message MESSAGE \
  [--body BODY]
```

- `--type` (required): `feat | fix | docs | style | refactor | test | chore | ci | build | revert`
- `--scope` (required): conventional commit scope
- `--message` (required): commit description
- `--body` (optional): detailed commit body

The script resolves the correct `Co-Authored-By` identity from
`vergil.toml` and the git hooks validate the result.

### Submitting PRs

```bash
vrg-submit-pr \
  --issue NUMBER --summary TEXT \
  [--linkage KEYWORD] [--title TEXT] \
  [--notes TEXT] [--dry-run]
```

- `--issue` (required): GitHub issue number
- `--summary` (required): one-line PR summary
- `--linkage` (optional, default: `Ref`): `Fixes | Closes | Resolves | Ref`
- `--title` (optional): PR title (default: most recent commit subject)
- `--notes` (optional): additional context
- `--dry-run` (optional): print generated PR without executing

The script detects the target branch and merge strategy automatically.

## Local Deviations

- No primary runtime language — this repo contains Dockerfiles, shell
  scripts, and Markdown documentation.
- No language-specific CI (no ruff, mypy, pytest, etc.).
- Validation runs `docker/generate.sh` before hadolint to expand
  templates into lintable Dockerfiles.
