# Trivy CVE Triage

When the docker-publish pipeline fails, it is almost always because
Trivy found new HIGH or CRITICAL vulnerabilities in the built images.
This runbook covers the end-to-end triage process: identifying the
CVEs, assessing each one, suppressing or escalating, and unblocking
the pipeline.

## How the pipeline gates on vulnerabilities

The `cd-docker-publish.yml` workflow scans each image on both platforms
(amd64 and arm64) using Trivy. Each scan step uses `continue-on-error:
true` so both platforms are scanned even if the first fails. A
subsequent "Fail if vulnerabilities found" step checks the outcomes
and fails the job if either scan found CRITICAL or HIGH vulnerabilities.

Scans filter against the `.trivyignore` file at the repository root.
CVEs listed there are excluded from the results. If all remaining
findings are below HIGH severity, the scan passes and the image is
promoted to the final tag.

When a scan fails, the candidate image is **not promoted** — the
consumer-facing tag still points to the last good build. Publishing is
blocked until the new CVEs are either suppressed or fixed.

## Step 1: Identify the failing CVEs

Pull the CVE IDs from the CI logs:

```bash
# List failed jobs and their log URLs
vrg-gh run view <run-id> --repo vergil-project/vergil-docker \
  | grep -E "X "

# Extract unique CVE IDs from the full run log
vrg-gh run view <run-id> --repo vergil-project/vergil-docker --log \
  | grep -oE "CVE-[0-9]+-[0-9]+" | sort -u

# Get package context for each CVE
vrg-gh run view <run-id> --repo vergil-project/vergil-docker --log \
  | grep "CVE-" | grep -v "^--$"
```

From the log output, extract for each CVE:

- **CVE ID**
- **Package name and version** (e.g., `libexpat1 2.7.1-2`)
- **Severity** (HIGH or CRITICAL)
- **Fix status** (`affected` = no fix, `fixed` = patch available)
- **Fixed version** (if applicable)
- **Which images are affected** (all, or a subset)

## Step 2: Check for duplicates

Verify which CVEs are already in `.trivyignore`:

```bash
for cve in CVE-XXXX-XXXXX CVE-YYYY-YYYYY; do
  echo -n "$cve: "
  grep -c "$cve" .trivyignore
done
```

If a CVE is already suppressed but still appearing, the ignore file
may have a formatting issue — check for trailing whitespace or
incorrect CVE IDs.

## Step 3: Assess each CVE

For each new CVE, determine the appropriate action:

### Suppress (add to .trivyignore)

Suppress when the vulnerability is not exploitable in the container
context. Common patterns:

| Pattern | Rationale |
|---------|-----------|
| **linux-libc-dev / kernel CVEs** | Containers use the host kernel, not the kernel headers in the image. These are always false positives. |
| **Library not exercised** | The vulnerable library is present but the affected code path is never invoked (e.g., DTLS in a TLS-only image, Kerberos in a container with no Kerberos services). |
| **No untrusted input** | The vulnerability requires attacker-controlled input, but the image only processes trusted data (e.g., XML parsing CVE in an image that never parses untrusted XML). |
| **No Debian fix available** | Status is `affected` with no fixed version. The vulnerability exists in the upstream Debian package and cannot be patched by the image build. |
| **Go binary transitive dependency** | A Go binary (scorecard, shfmt, etc.) includes a vulnerable dependency that the binary never exercises. |

### Fix (bump the dependency)

Fix when:

- A patched version exists in Debian and can be pulled by rebuilding
  the image (base image update).
- A tool version bump resolves the CVE and is low-risk.
- The vulnerability is in a package we install directly (not inherited
  from the base image).

Fixing typically means bumping a version pin in a common fragment and
rebuilding. This is a separate PR from the triage suppression.

### Escalate

Escalate when:

- The CVE is CRITICAL and affects a code path that containers exercise.
- You are unsure whether the vulnerability is exploitable.
- The fix requires a breaking change or major version bump.

Flag the CVE to the team with your assessment and wait for a decision.

## Step 4: Create the issue and PR

### Create a tracking issue

```bash
vrg-gh issue create --repo vergil-project/vergil-docker \
  --title "triage HIGH CVEs blocking docker-publish (YYYY-MM-DD)" \
  --body-file <body-file>
```

The issue body should include a table of CVEs with package, fix status,
and rationale for each decision.

### Add suppressions to .trivyignore

Each entry must include a comment block explaining why the CVE is
suppressed. Follow the existing format:

```text
# <package> (<distro>) — <brief description of the vulnerability>.
# <Why it is safe to suppress in this context>. <Fix status>.
# Issue #<N>.
CVE-XXXX-XXXXX
```

Place entries in the appropriate section of the file. If no existing
section fits, add a new comment header. Keep entries grouped by
package or category, not chronologically.

### Submit and verify

1. Commit the `.trivyignore` changes via `vrg-commit`
2. Submit the PR via `vrg-submit-pr` with `--linkage Ref`
3. Wait for CI to pass — the Trivy scan should now succeed with the
   new suppressions
4. After merge, verify the post-merge CD workflow publishes all images
   successfully

## Step 5: Post-triage hygiene

### Remove stale suppressions

When a Debian package ships a fix for a previously-suppressed CVE, the
entry should be removed from `.trivyignore` on the next triage pass.
Trivy will no longer flag the CVE (since the fixed package is pulled
during image build), so the suppression becomes dead weight.

### Track fixable CVEs

If a CVE has a fix available but suppressing is the expedient choice
(e.g., the fix requires a base image rebuild or a tool version bump),
note it in the `.trivyignore` comment. On the next dependency update
cycle, check whether the fix has been incorporated.

## Reference: exit codes and severity

The Trivy scan is configured to fail on **HIGH** and **CRITICAL**
findings only. MEDIUM and below pass silently. The pipeline exit codes:

- **0** — no HIGH/CRITICAL findings (after filtering `.trivyignore`)
- **1** — one or more HIGH/CRITICAL findings remain
