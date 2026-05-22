# VERGIL Docker Repository Standards

## Table of Contents

- [External tooling dependencies](#external-tooling-dependencies)
- [CI gates](#ci-gates)
- [Commit and PR scripts](#commit-and-pr-scripts)
- [Local deviations](#local-deviations)

## External tooling dependencies

- hadolint
- shellcheck
- markdownlint (markdownlint-cli)

## CI gates

Hard gates (required status checks on `develop`):

- Hadolint: lint all generated Dockerfiles
- ShellCheck: lint `docker/build.sh` and `docker/generate.sh`
- Security and standards (`standard-actions/ci-security`):
  - Semgrep (Dockerfile language)
  - Repository profile validation (`repo-profile`)
  - Markdownlint (`markdown-standards`)
  - Commit message lint (CI validator)
  - Issue linkage validation (`pr-issue-linkage`)

Local hard gates (pre-commit hooks):

- Branch naming enforcement: branching-model-aware prefix validation.
- Commit message lint: Conventional Commits required.

## Commit and PR scripts

AI agents **must** use the wrapper scripts for commits and PR submission.
Do not construct commit messages or PR bodies manually.

### Committing

```bash
vrg-commit \
  --type TYPE --scope SCOPE --message MESSAGE \
  [--body BODY]
```

- `--type` (required): `feat|fix|docs|style|refactor|test|chore|ci|build|revert`
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

- `--issue` (required): GitHub issue number (just the number)
- `--summary` (required): one-line PR summary
- `--linkage` (optional, default: `Fixes`): `Fixes|Closes|Resolves|Ref`
- `--title` (optional): PR title (default: most recent commit subject)
- `--notes` (optional): additional notes
- `--dry-run` (optional): print generated PR without executing

The script detects the target branch and merge strategy automatically.

## Local deviations

- No primary runtime language — this repo contains Dockerfiles, shell scripts,
  and Markdown documentation.
- No language-specific CI (no ruff, mypy, pytest, etc.).
