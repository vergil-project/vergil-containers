# OpenSSF Scorecard snapshots

Point-in-time [OpenSSF Scorecard](https://github.com/ossf/scorecard) captures for
this repository. A Scorecard result is a report of security posture at one
commit, not an open work item — so we capture it here as dated snapshots and
re-run it on a cadence, rather than accreting findings in the issue tracker.

**Remediation is tracked separately.** This document is the *record*, not the
work. The actual OpenSSF hardening work lives in epic
[vergil-project/.github#54](https://github.com/vergil-project/.github/issues/54),
tracking issue
[vergil-project/vergil-tooling#828](https://github.com/vergil-project/vergil-tooling/issues/828).

The layout here — one flat file per repo at `docs/security/openssf-scorecard-snapshots.md`,
newest snapshot first — matches the sibling repositories so the capture location
is consistent across the ecosystem (see
[vergil-claude-plugin](https://github.com/vergil-project/vergil-claude-plugin/blob/develop/docs/security/openssf-scorecard-snapshots.md)).

## How to add a snapshot

Re-run the Scorecard from a checkout of this repo and append a new dated section
at the top of [Snapshots](#snapshots) (newest first), then add a row to the
[trend table](#trend):

```bash
vrg-scorecard --repo=github.com/vergil-project/vergil-containers --show-details
```

`vrg-scorecard` runs the Scorecard CLI inside a dev container and injects the
human account's GitHub token, so it does not need a token on the host. Record,
for each snapshot: the aggregate score, the evaluated commit SHA, the Scorecard
version, the per-check table, and the detailed findings. Cadence: roughly
quarterly, or after any deliberate hardening change worth measuring.

## Trend

| Date | Aggregate | Commit | Scorecard |
|------|-----------|--------|-----------|
| 2026-08-12 | 5.0 / 10 | `c05a9065bc79` | v5.5.0 |
| 2026-05-19 | 4.7 / 10 | `a6849a8e450c` | v5.5.0 |

Score legend: 🟢 10/10 · 🔴 0–9/10 (needs work) · ⚪ -1/10 (not applicable /
not detected).

## Snapshots

### 2026-08-12

**Aggregate score:** 5.0 / 10
**Commit:** `c05a9065bc79a97a5c36adbf3a251a3640553d05`
**Scorecard version:** v5.5.0
**Tracking issue:**
[vergil-project/vergil-tooling#828](https://github.com/vergil-project/vergil-tooling/issues/828)

#### Changes since the 2026-05-19 baseline

The aggregate rose 4.7 → 5.0. Movement by check:

- **Maintained** 0 → 10 — the repo is no longer "created within the last 90
  days"; 30 commits and 7 issue activity in the trailing 90 days now score it.
- **Signed-Releases** -1 → 0 — releases now exist (v2.1.20–v2.1.24), so the
  check applies; none are signed or carry provenance, hence 0.
- **Pinned-Dependencies** 1 → 0 — still no dependencies pinned by hash; this run
  normalized the score to 0.
- **CI-Tests** 19/19 (was 12/12) and **Code-Review** 0/19 (was 0/12) — same
  scores, larger merged-PR sample.

All other checks are unchanged from the baseline.

#### Scores by check

| Score | Check | Reason |
|-------|-------|--------|
| ⚪ -1/10 | Packaging | packaging workflow not detected |
| 🔴 0/10 | CII-Best-Practices | no effort to earn an OpenSSF best practices badge detected |
| 🔴 0/10 | Code-Review | Found 0/19 approved changesets |
| 🔴 0/10 | Contributors | project has 0 contributing companies or organizations |
| 🔴 0/10 | Dependency-Update-Tool | no update tool detected |
| 🔴 0/10 | Fuzzing | project is not fuzzed |
| 🔴 0/10 | Pinned-Dependencies | dependency not pinned by hash detected |
| 🔴 0/10 | Signed-Releases | Project has not signed or included provenance with any releases. |
| 🔴 0/10 | Token-Permissions | detected GitHub workflow tokens with excessive permissions |
| 🔴 4/10 | Branch-Protection | branch protection is not maximal on development and all release branches |
| 🟢 10/10 | Binary-Artifacts | no binaries found in the repo |
| 🟢 10/10 | CI-Tests | 19 out of 19 merged PRs checked by a CI test |
| 🟢 10/10 | Dangerous-Workflow | no dangerous workflow patterns detected |
| 🟢 10/10 | License | license file detected |
| 🟢 10/10 | Maintained | 30 commit(s) and 7 issue activity found in the last 90 days |
| 🟢 10/10 | SAST | SAST tool is run on all commits |
| 🟢 10/10 | Security-Policy | security policy file detected |
| 🟢 10/10 | Vulnerabilities | 0 existing vulnerabilities detected |

#### Detailed findings

##### Packaging (-1/10)

**Reason:** packaging workflow not detected

**Warnings:**

- `no GitHub/GitLab publishing workflow detected.`

**Documentation:** https://github.com/ossf/scorecard/blob/main/docs/checks.md#packaging

##### CII-Best-Practices (0/10)

**Reason:** no effort to earn an OpenSSF best practices badge detected

**Documentation:** https://github.com/ossf/scorecard/blob/main/docs/checks.md#cii-best-practices

##### Code-Review (0/10)

**Reason:** Found 0/19 approved changesets -- score normalized to 0

**Documentation:** https://github.com/ossf/scorecard/blob/main/docs/checks.md#code-review

##### Contributors (0/10)

**Reason:** project has 0 contributing companies or organizations -- score normalized to 0

**Documentation:** https://github.com/ossf/scorecard/blob/main/docs/checks.md#contributors

##### Dependency-Update-Tool (0/10)

**Reason:** no update tool detected

**Warnings:**

- `no dependency update tool configurations found`

**Documentation:** https://github.com/ossf/scorecard/blob/main/docs/checks.md#dependency-update-tool

##### Fuzzing (0/10)

**Reason:** project is not fuzzed

**Warnings:**

- `no fuzzer integrations found`

**Documentation:** https://github.com/ossf/scorecard/blob/main/docs/checks.md#fuzzing

##### Pinned-Dependencies (0/10)

**Reason:** dependency not pinned by hash detected -- score normalized to 0

**Warnings:**

- `GitHub-owned GitHubAction not pinned by hash: .github/workflows/bump-tools.yml:40`
- `GitHub-owned GitHubAction not pinned by hash: .github/workflows/bump-tools.yml:46`
- `GitHub-owned GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:40`
- `GitHub-owned GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:120`
- `third-party GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:128`
- `third-party GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:131`
- `third-party GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:134`
- `third-party GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:141`
- `third-party GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:155`
- `GitHub-owned GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:206`
- `GitHub-owned GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:226`
- `GitHub-owned GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:262`
- `third-party GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:270`
- `third-party GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:273`
- `third-party GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:276`
- `third-party GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:283`
- `third-party GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:296`
- `GitHub-owned GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:347`
- `GitHub-owned GitHubAction not pinned by hash: .github/workflows/cd-docker-publish.yml:367`
- `third-party GitHubAction not pinned by hash: .github/workflows/cd.yml:23`
- `third-party GitHubAction not pinned by hash: .github/workflows/cd.yml:29`
- `GitHub-owned GitHubAction not pinned by hash: .github/workflows/ci.yml:30`
- `GitHub-owned GitHubAction not pinned by hash: .github/workflows/ci.yml:45`
- `third-party GitHubAction not pinned by hash: .github/workflows/ci.yml:54`
- `third-party GitHubAction not pinned by hash: .github/workflows/ci.yml:62`
- `third-party GitHubAction not pinned by hash: .github/workflows/ci.yml:78`
- `third-party GitHubAction not pinned by hash: .github/workflows/ci.yml:86`
- `third-party GitHubAction not pinned by hash: .github/workflows/epic-rollup.yml:20`
- `third-party GitHubAction not pinned by hash: .github/workflows/ops.yml:18`
- `third-party GitHubAction not pinned by hash: .github/workflows/package-cleanup.yml:129`
- `third-party GitHubAction not pinned by hash: .github/workflows/package-cleanup.yml:69`
- `pipCommand not pinned by hash: docker/base/Dockerfile.template:38-39`
- `pipCommand not pinned by hash: docker/base/Dockerfile.template:38-39`
- `pipCommand not pinned by hash: docker/base/Dockerfile.template:42-45`
- `downloadThenRun not pinned by hash: docker/common/node-markdownlint.dockerfile:3-5`
- `npmCommand not pinned by hash: docker/common/node-markdownlint.dockerfile:13-15`
- `npmCommand not pinned by hash: docker/common/node-markdownlint.dockerfile:13-15`
- `downloadThenRun not pinned by hash: docker/common/python-support.dockerfile:4-9`
- `npmCommand not pinned by hash: docker/common/typescript-analysis.dockerfile:43-51`
- `goCommand not pinned by hash: docker/go/Dockerfile.template:24-31`
- `goCommand not pinned by hash: docker/go/Dockerfile.template:24-31`
- `goCommand not pinned by hash: docker/go/Dockerfile.template:24-31`
- `goCommand not pinned by hash: docker/go/Dockerfile.template:24-31`
- `goCommand not pinned by hash: docker/go/Dockerfile.template:24-31`
- `pipCommand not pinned by hash: docker/python/Dockerfile.template:35-36`
- `pipCommand not pinned by hash: docker/python/Dockerfile.template:35-36`
- `downloadThenRun not pinned by hash: docker/ts-node/Dockerfile.template:40-42`
- `npmCommand not pinned by hash: docker/ts-node/Dockerfile.template:43-45`
- `npmCommand not pinned by hash: docker/ts-node/Dockerfile.template:43-45`

<details><summary>Info details (6 items)</summary>

- `0 out of 11 GitHub-owned GitHubAction dependencies pinned`
- `0 out of 20 third-party GitHubAction dependencies pinned`
- `0 out of 5 pipCommand dependencies pinned`
- `0 out of 3 downloadThenRun dependencies pinned`
- `1 out of 6 npmCommand dependencies pinned`
- `0 out of 5 goCommand dependencies pinned`

</details>

**Documentation:** https://github.com/ossf/scorecard/blob/main/docs/checks.md#pinned-dependencies

##### Signed-Releases (0/10)

**Reason:** Project has not signed or included provenance with any releases.

**Warnings:**

- `release artifact v2.1.24 not signed: https://api.github.com/repos/vergil-project/vergil-containers/releases/368811406`
- `release artifact v2.1.23 not signed: https://api.github.com/repos/vergil-project/vergil-containers/releases/368796729`
- `release artifact v2.1.22 not signed: https://api.github.com/repos/vergil-project/vergil-containers/releases/368771766`
- `release artifact v2.1.21 not signed: https://api.github.com/repos/vergil-project/vergil-containers/releases/368722537`
- `release artifact v2.1.20 not signed: https://api.github.com/repos/vergil-project/vergil-containers/releases/365754636`
- `release artifact v2.1.24 does not have provenance: https://api.github.com/repos/vergil-project/vergil-containers/releases/368811406`
- `release artifact v2.1.23 does not have provenance: https://api.github.com/repos/vergil-project/vergil-containers/releases/368796729`
- `release artifact v2.1.22 does not have provenance: https://api.github.com/repos/vergil-project/vergil-containers/releases/368771766`
- `release artifact v2.1.21 does not have provenance: https://api.github.com/repos/vergil-project/vergil-containers/releases/368722537`
- `release artifact v2.1.20 does not have provenance: https://api.github.com/repos/vergil-project/vergil-containers/releases/365754636`

**Documentation:** https://github.com/ossf/scorecard/blob/main/docs/checks.md#signed-releases

##### Token-Permissions (0/10)

**Reason:** detected GitHub workflow tokens with excessive permissions

**Warnings:**

- `jobLevel 'security-events' permission set to 'write': .github/workflows/cd.yml:53`
- `jobLevel 'packages' permission set to 'write': .github/workflows/cd.yml:51`
- `jobLevel 'contents' permission set to 'write': .github/workflows/cd.yml:25`
- `jobLevel 'contents' permission set to 'write': .github/workflows/cd.yml:39`
- `jobLevel 'security-events' permission set to 'write': .github/workflows/ci.yml:72`
- `jobLevel 'packages' permission set to 'write': .github/workflows/ops.yml:33`
- `jobLevel 'security-events' permission set to 'write': .github/workflows/ops.yml:35`
- `jobLevel 'packages' permission set to 'write': .github/workflows/ops.yml:46`
- `jobLevel 'security-events' permission set to 'write': .github/workflows/ops.yml:48`
- `topLevel 'contents' permission set to 'write': .github/workflows/bump-tools.yml:22`
- `topLevel 'packages' permission set to 'write': .github/workflows/cd-docker-publish.yml:22`
- `topLevel 'security-events' permission set to 'write': .github/workflows/cd-docker-publish.yml:24`
- `topLevel 'packages' permission set to 'write': .github/workflows/cd.yml:11`
- `topLevel 'security-events' permission set to 'write': .github/workflows/cd.yml:12`
- `topLevel 'contents' permission set to 'write': .github/workflows/cd.yml:10`
- `topLevel 'packages' permission set to 'write': .github/workflows/ops.yml:11`
- `topLevel 'security-events' permission set to 'write': .github/workflows/ops.yml:12`
- `topLevel 'packages' permission set to 'write': .github/workflows/package-cleanup.yml:40`

<details><summary>Info details (14 items)</summary>

- `jobLevel 'contents' permission set to 'read': .github/workflows/cd.yml:52`
- `jobLevel 'actions' permission set to 'read': .github/workflows/cd.yml:38`
- `jobLevel 'contents' permission set to 'read': .github/workflows/ci.yml:71`
- `jobLevel 'actions' permission set to 'read': .github/workflows/ci.yml:75`
- `jobLevel 'contents' permission set to 'read': .github/workflows/epic-rollup.yml:22`
- `jobLevel 'contents' permission set to 'read': .github/workflows/ops.yml:20`
- `jobLevel 'contents' permission set to 'read': .github/workflows/ops.yml:34`
- `jobLevel 'contents' permission set to 'read': .github/workflows/ops.yml:47`
- `topLevel 'contents' permission set to 'read': .github/workflows/cd-docker-publish.yml:23`
- `topLevel 'actions' permission set to 'read': .github/workflows/cd.yml:19`
- `topLevel 'contents' permission set to 'read': .github/workflows/ci.yml:16`
- `topLevel 'contents' permission set to 'read': .github/workflows/epic-rollup.yml:16`
- `topLevel 'contents' permission set to 'read': .github/workflows/ops.yml:9`
- `topLevel 'contents' permission set to 'read': .github/workflows/package-cleanup.yml:41`

</details>

**Documentation:** https://github.com/ossf/scorecard/blob/main/docs/checks.md#token-permissions

##### Branch-Protection (4/10)

**Reason:** branch protection is not maximal on development and all release branches

**Warnings:**

- `branch 'develop' does not require approvers`
- `codeowners review is not required on branch 'develop'`
- `'last push approval' is disabled on branch 'develop'`

<details><summary>Info details (7 items)</summary>

- `'allow deletion' disabled on branch 'develop'`
- `'force pushes' disabled on branch 'develop'`
- `'branch protection settings apply to administrators' is required to merge on branch 'develop'`
- `'stale review dismissal' is required to merge on branch 'develop'`
- `'up-to-date branches' is required to merge on branch 'develop'`
- `status check found to merge onto on branch 'develop'`
- `PRs are required in order to make changes on branch 'develop'`

</details>

**Documentation:** https://github.com/ossf/scorecard/blob/main/docs/checks.md#branch-protection

---

### 2026-05-19 (baseline)

**Aggregate score:** 4.7 / 10
**Commit:** `a6849a8e450c`
**Scorecard version:** v5.5.0
**Tracking issue:**
[vergil-project/vergil-tooling#828](https://github.com/vergil-project/vergil-tooling/issues/828)

> First captured snapshot, preserved from the tracking issue
> ([#244](https://github.com/vergil-project/vergil-containers/issues/244)).

#### Scores by check

| Score | Check | Reason |
|-------|-------|--------|
| ⚪ -1/10 | Packaging | packaging workflow not detected |
| ⚪ -1/10 | Signed-Releases | no releases found |
| 🔴 0/10 | CII-Best-Practices | no effort to earn an OpenSSF best practices badge detected |
| 🔴 0/10 | Code-Review | Found 0/10 approved changesets |
| 🔴 0/10 | Contributors | project has 0 contributing companies or organizations |
| 🔴 0/10 | Dependency-Update-Tool | no update tool detected |
| 🔴 0/10 | Fuzzing | project is not fuzzed |
| 🔴 0/10 | Maintained | project was created within the last 90 days. Please review its contents carefully |
| 🔴 0/10 | Token-Permissions | detected GitHub workflow tokens with excessive permissions |
| 🔴 1/10 | Pinned-Dependencies | dependency not pinned by hash detected |
| 🔴 4/10 | Branch-Protection | branch protection is not maximal on development and all release branches |
| 🟢 10/10 | Binary-Artifacts | no binaries found in the repo |
| 🟢 10/10 | CI-Tests | 12 out of 12 merged PRs checked by a CI test |
| 🟢 10/10 | Dangerous-Workflow | no dangerous workflow patterns detected |
| 🟢 10/10 | License | license file detected |
| 🟢 10/10 | SAST | SAST tool is run on all commits |
| 🟢 10/10 | Security-Policy | security policy file detected |
| 🟢 10/10 | Vulnerabilities | 0 existing vulnerabilities detected |

#### Detailed findings

##### Packaging (-1/10)

**Reason:** packaging workflow not detected

**Warnings:**

- `no GitHub/GitLab publishing workflow detected.`

**Documentation:** https://github.com/ossf/scorecard/blob/c395761df6afe1a69e476bc60a013a94bcbc153f/docs/checks.md#packaging

##### Signed-Releases (-1/10)

**Reason:** no releases found

**Documentation:** https://github.com/ossf/scorecard/blob/c395761df6afe1a69e476bc60a013a94bcbc153f/docs/checks.md#signed-releases

##### CII-Best-Practices (0/10)

**Reason:** no effort to earn an OpenSSF best practices badge detected

**Documentation:** https://github.com/ossf/scorecard/blob/c395761df6afe1a69e476bc60a013a94bcbc153f/docs/checks.md#cii-best-practices

##### Code-Review (0/10)

**Reason:** Found 0/10 approved changesets -- score normalized to 0

**Documentation:** https://github.com/ossf/scorecard/blob/c395761df6afe1a69e476bc60a013a94bcbc153f/docs/checks.md#code-review

##### Contributors (0/10)

**Reason:** project has 0 contributing companies or organizations -- score normalized to 0

**Documentation:** https://github.com/ossf/scorecard/blob/c395761df6afe1a69e476bc60a013a94bcbc153f/docs/checks.md#contributors

##### Dependency-Update-Tool (0/10)

**Reason:** no update tool detected

**Warnings:**

- `no dependency update tool configurations found`

**Documentation:** https://github.com/ossf/scorecard/blob/c395761df6afe1a69e476bc60a013a94bcbc153f/docs/checks.md#dependency-update-tool

##### Fuzzing (0/10)

**Reason:** project is not fuzzed

**Warnings:**

- `no fuzzer integrations found`

**Documentation:** https://github.com/ossf/scorecard/blob/c395761df6afe1a69e476bc60a013a94bcbc153f/docs/checks.md#fuzzing

##### Maintained (0/10)

**Reason:** project was created within the last 90 days. Please review its contents carefully

**Warnings:**

- `Repository was created within the last 90 days.`

**Documentation:** https://github.com/ossf/scorecard/blob/c395761df6afe1a69e476bc60a013a94bcbc153f/docs/checks.md#maintained

##### Token-Permissions (0/10)

**Reason:** detected GitHub workflow tokens with excessive permissions

**Warnings:**

- `jobLevel 'contents' permission set to 'write': .github/workflows/cd.yml:21`
- `jobLevel 'contents' permission set to 'write': .github/workflows/cd.yml:31`
- `jobLevel 'packages' permission set to 'write': .github/workflows/cd.yml:43`
- `jobLevel 'security-events' permission set to 'write': .github/workflows/cd.yml:45`
- `jobLevel 'security-events' permission set to 'write': .github/workflows/ci.yml:54`
- `jobLevel 'security-events' permission set to 'write': .github/workflows/ops.yml:30`
- `jobLevel 'packages' permission set to 'write': .github/workflows/ops.yml:28`
- `topLevel 'security-events' permission set to 'write': .github/workflows/cd-docker-publish.yml:14`
- `topLevel 'packages' permission set to 'write': .github/workflows/cd-docker-publish.yml:12`
- `topLevel 'contents' permission set to 'write': .github/workflows/cd.yml:10`
- `topLevel 'packages' permission set to 'write': .github/workflows/cd.yml:11`
- `topLevel 'security-events' permission set to 'write': .github/workflows/cd.yml:12`
- `topLevel 'packages' permission set to 'write': .github/workflows/ops.yml:11`
- `topLevel 'security-events' permission set to 'write': .github/workflows/ops.yml:12`

<details><summary>Info details (7 items)</summary>

- `jobLevel 'contents' permission set to 'read': .github/workflows/cd.yml:44`
- `jobLevel 'contents' permission set to 'read': .github/workflows/ci.yml:53`
- `jobLevel 'contents' permission set to 'read': .github/workflows/ops.yml:20`
- `jobLevel 'contents' permission set to 'read': .github/workflows/ops.yml:29`
- `topLevel 'contents' permission set to 'read': .github/workflows/cd-docker-publish.yml:13`
- `topLevel 'contents' permission set to 'read': .github/workflows/ci.yml:16`
- `topLevel 'contents' permission set to 'read': .github/workflows/ops.yml:9`

</details>

**Documentation:** https://github.com/ossf/scorecard/blob/c395761df6afe1a69e476bc60a013a94bcbc153f/docs/checks.md#token-permissions

##### Pinned-Dependencies (1/10)

**Reason:** dependency not pinned by hash detected -- score normalized to 1

Numerous GitHub Actions, pip, npm, and downloadThenRun dependencies were not
pinned by hash across `.github/workflows/*` and `docker/*`. The full per-line
warning list from the baseline run was captured in the tracking issue's edit
history and is not reproduced verbatim here; the 2026-08-12 snapshot above
carries the current, fully enumerated list.

**Documentation:** https://github.com/ossf/scorecard/blob/c395761df6afe1a69e476bc60a013a94bcbc153f/docs/checks.md#pinned-dependencies

##### Branch-Protection (4/10)

**Reason:** branch protection is not maximal on development and all release branches

**Warnings:**

- `branch 'develop' does not require approvers`
- `codeowners review is not required on branch 'develop'`
- `'last push approval' is disabled on branch 'develop'`

<details><summary>Info details (7 items)</summary>

- `'allow deletion' disabled on branch 'develop'`
- `'force pushes' disabled on branch 'develop'`
- `'branch protection settings apply to administrators' is required to merge on branch 'develop'`
- `'stale review dismissal' is required to merge on branch 'develop'`
- `'up-to-date branches' is required to merge on branch 'develop'`
- `status check found to merge onto on branch 'develop'`
- `PRs are required in order to make changes on branch 'develop'`

</details>

**Documentation:** https://github.com/ossf/scorecard/blob/c395761df6afe1a69e476bc60a013a94bcbc153f/docs/checks.md#branch-protection
