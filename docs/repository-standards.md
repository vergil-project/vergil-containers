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

Hard gates (required status checks on `develop` and `main`), from
vergil-tooling's generated `CI gates` ruleset, computed from `vergil.toml`
(never set by hand):

- `quality / evidence`: the aggregate of the quality jobs, including
  `quality / custom`
- `security / trivy`, `security / semgrep` (`vergil-actions/ci-security`),
  and the code-scanning checks `Trivy` and `Semgrep OSS`
- `docs / docs`: the docs build
- `version / version-bump`: the version-bump gate
- `images / evidence`: the aggregating gate of `ci-images.yml`, which builds
  and scans the images a pull request changes (`[ci].images = true`)

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

Commits carry no AI co-author trailer; Claude Code attribution is turned
off in `.claude/settings.json` (vergil-project/vergil-tooling#3200). The
git hooks validate the result.

### Submitting PRs

```bash
vrg-submit-pr \
  --issue NUMBER --title TEXT --summary TEXT \
  [--linkage KEYWORD] [--notes TEXT] [--dry-run]
```

- `--issue` (required): GitHub issue number (just the number)
- `--title` (required): PR title
- `--summary` (required): one-line PR summary
- `--linkage` (optional, default: `Ref`): **always use `Ref`**.
  `Fixes`, `Closes`, and `Resolves` are forbidden — they auto-close
  the issue at merge time, bypassing finalization. Issues are closed
  explicitly after `vrg-finalize-repo` succeeds.
- `--notes` (optional): additional notes
- `--dry-run` (optional): print generated PR without executing

The script detects the target branch and merge strategy automatically.

## Local deviations

- No primary runtime language — this repo contains Dockerfiles, shell scripts,
  and Markdown documentation.
- No language-specific CI (no ruff, mypy, pytest, etc.).
