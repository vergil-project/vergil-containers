# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [2.0.11] - 2026-05-28
## [2.0.10] - 2026-05-28

### Bug fixes

- pass app secrets to github-config audit
- suppress DL3003 for checksum verification subshells
- suppress linux-libc-dev CVE-2024-2193 and CVE-2026-43503
- suppress Perl Archive::Tar and Go stdlib CVEs blocking dev image publish
- suppress additional Perl and Go stdlib CVEs from updated Trivy DB

### Chores

- bump version to 2.0.8
- add Version label to site header version selector
- suppress five new HIGH CVEs blocking docker-publish
- replace .githooks with Claude Code hook guard
- add missing container parameters and fix stale standards doc
- remove orphaned [workflows.post-merge] from vergil.toml
- align CLAUDE.md with consumer template and drop unsupported primary-language

### Documentation

- document download integrity verification in architecture page

### Features

- integrate repo docs into site and add Trivy triage runbook
- add checksum verification to binary tool downloads
- add trivy 0.70.0 to security-tools fragment

## [2.0.7] - 2026-05-18

### Bug fixes

- pass app secrets to github-config audit
- suppress DL3003 for checksum verification subshells
- suppress linux-libc-dev CVE-2024-2193 and CVE-2026-43503
- suppress Perl Archive::Tar and Go stdlib CVEs blocking dev image publish
- suppress additional Perl and Go stdlib CVEs from updated Trivy DB

### Documentation

- document download integrity verification in architecture page

### Features

- integrate repo docs into site and add Trivy triage runbook
- add checksum verification to binary tool downloads
- add trivy 0.70.0 to security-tools fragment

## [2.0.7] - 2026-05-18

### Bug fixes

- suppress 11 new CVEs blocking CD publish pipeline

### Documentation

- add scorecard CLI implementation plan for #234
- add scorecard to Common Layer inventory

### Features

- deploy deny rules to project-level settings
- add security-tools fragment with scorecard 5.5.0
- include security-tools in dev-base template

## [2.0.6] - 2026-05-14

### Bug fixes

- suppress CVE-2026-5773 curl SMB connection reuse

### Features

- deploy permission model configuration

## [2.0.4] - 2026-05-13

### Documentation

- replace stale standard-tooling references with vergil-docker

## [2.0.3] - 2026-05-13

### Documentation

- replace stale standard-tooling-docker references with vergil-docker

## [2.0.1] - 2026-05-13

### Bug fixes

- pin go-test-coverage to v2.18.3 for hadolint DL3062
- suppress new Go stdlib CVEs in Trivy ignore list
- pin go-test-coverage v2.18.3 for Go 1.25 compatibility
- correct trivy action path in cd-docker-publish
- point vergil dependency at v2.0.1 (setup action reads this key)

### CI

- update vergil-actions refs from v1.5 to v2.0

### Features

- rename to vergil-docker under vergil-project org (#193)

### Refactoring

- align PR and issue templates with standard-tooling

## [1.5.0] - 2026-05-10

### Bug fixes

- scope standalone markdownlint step to README.md only (#197) (#13)
- update trivyignore for new CVEs and pin go-test-coverage (#21)
- add CVE-2026-29786 (tar) to trivyignore (#30)
- add CVE-2025-15558 (gh docker/cli, Windows-only) to trivyignore (#40)
- scan locally-built image with Trivy, not published :latest (#56)
- bump pip to >=26.1 (CVE-2026-3219) (#63)
- triage HIGH/CRITICAL CVEs blocking docker-publish (#68)
- pin standard-tooling-pip fragment to v1.3 (#73)
- bump stale standard-actions trivy pins from @v1.1 to @v1.3 (#80)
- triage jq CVEs blocking docker-publish (post-#78) (#82)
- fix semgrep build and triage new Trivy CVEs (#110)
- add /github/home/.local/bin to PATH for GitHub Actions compatibility (#116)
- triage 8 new linux-libc-dev kernel CVEs blocking docker-publish (#118)
- triage linux-libc-dev kernel CVE blocking docker-publish (#129)
- remove candidate tag cleanup that deletes promoted images (#134)
- triage CVE-2026-33846 and fix trailing blank lines in workflow (#135)
- install uv in non-Python dev images (#136)
- add /workspace/.venv/bin to PATH for uv sync entry points (#142)
- revert /workspace/.venv/bin PATH addition from #141 (#144)
- suppress CVE-2026-42246 (net-imap) in Trivy ignore list (#150)
- suppress new linux-libc-dev kernel CVEs in Trivy ignore list (#151)
- suppress new gnutls, libssh2, and linux-libc-dev CVEs in Trivy ignore list (#158)
- use dev-base container for hadolint instead of downloading binary (#162)
- pass boolean to ci-security reusable workflow inputs (#163)
- ensure both Trivy scans run before gating on vulnerabilities (#166)
- suppress new linux-libc-dev kernel CVEs in Trivy ignore list (#171)
- suppress new linux-libc-dev kernel CVEs in Trivy ignore list (#177)
- suppress CVE-2026-43500 linux-libc-dev kernel CVE in Trivy ignore list (#178)

### CI

- publish dev-docs container to GHCR (#27)
- bump docker/login-action to v4 and attest-build-provenance to v4 for Node.js 24 (#114)
- bump Docker actions to Node.js 24-compatible versions (#133)
- adopt standard-actions v1.5 reusable workflows and bump to 1.5.0 (#146)
- remove redundant bespoke shellcheck job (#148)

### Documentation

- add MkDocs/mike documentation site (#4)
- document GHCR package access prerequisites for publishing (#6)
- add GHCR publishing prerequisites to MkDocs site (#8)
- update documentation for templating system and current tooling inventory (#43)
- add cliff config + regenerate CHANGELOG; sanity-check docs accuracy (#58)
- remove include directives and downgrade standards-and-conventions refs (#87)
- add versioned image tags spec and pushback review (#88)
- comprehensive documentation review for consistency (#90)
- add implementation plan and review docs for host-only tool guardrails (#96)
- add multi-arch design spec, implementation plan, and review reports (#126)
- fix hadolint arch labels and add revised alignment review (#130)
- update documentation to reflect current image contents and multi-arch publishing (#138)
- replace stale repository-standards.md references with standard-tooling.toml (#168)
- review and update repository documentation (#169)

### Features

- initial repository with Docker dev container images
- add cross-language validation tools to all dev containers (#15)
- add go-test-coverage to Go dev image (#17)
- update cargo-deny to 0.19.0 for CVSS 4.0 support (#24)
- add dev-docs image for containerised MkDocs preview (#26)
- install standard-tooling in all dev container images (#29)
- add Node.js and markdownlint-cli to dev-docs image (#32)
- install gh CLI in all dev container images (#33)
- modernize tool installation and remove taplo from dev containers (#38)
- replace Dockerfiles with templated fragments and add git-cliff (#41)
- add openssh-client to all container images (#46)
- adopt git worktree convention for parallel AI agent development (#49)
- pin standard-tooling to rolling minor tag; rebuild on release (#51) (#52)
- prune dangling images and stale build cache after local build (#74)
- add jq to all dev container images (#78)
- add ~/.local/bin to default PATH in all dev container images (#103) (#104)
- bake pyyaml, semgrep, and hadolint into dev container images (#109)
- publish multi-arch (amd64 + arm64) dev container images (#131)
- add license_finder to dev-ruby image (#156)
- adopt CI/CD workflow convention (#383) (#172)
- add reusable docker-publish workflow with dev/prod naming and nightly rebuilds (#175)

### Refactoring

- rename dev-docs to dev-base with full common tooling (#44)

### Styling

- fix table alignment and code fence language for markdownlint (#5)

