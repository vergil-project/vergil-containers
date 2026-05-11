## [develop-v1.0.0] - 2026-03-05

### 🚀 Features

- Initial repository with Docker dev container images
- Add cross-language validation tools to all dev containers (#15)
- *(dev-go)* Add go-test-coverage to Go dev image (#17)

### 🐛 Bug Fixes

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

### CI

- publish dev-docs container to GHCR (#27)

### Documentation

- add MkDocs/mike documentation site (#4)
- document GHCR package access prerequisites for publishing (#6)
- add GHCR publishing prerequisites to MkDocs site (#8)
- update documentation for templating system and current tooling inventory (#43)
- add cliff config + regenerate CHANGELOG; sanity-check docs accuracy (#58)
- remove include directives and downgrade standards-and-conventions refs (#87)
- add versioned image tags spec and pushback review (#88)

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

### Refactoring

- rename dev-docs to dev-base with full common tooling (#44)

### Styling

- fix table alignment and code fence language for markdownlint (#5)

