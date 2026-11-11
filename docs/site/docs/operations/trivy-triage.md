# Trivy CVE Triage

When the docker-publish pipeline fails at the Trivy gate, it is usually
because Trivy found new HIGH or CRITICAL vulnerabilities in the built
images. Check the gate's message first: `Trivy scan errored (no report
produced)` means a scan failed before it could report (a dropped image-layer
or vulnerability-DB download) and found nothing. Re-run the job; there is
nothing to triage. This runbook covers the end-to-end triage process: identifying the
CVEs, assessing each one, suppressing or escalating, and unblocking
the pipeline.

For which Trivy scans run on pull requests versus on publish, and why
pull requests show a "configurations not found" code-scanning warning, see
[Trivy Scanning](../architecture/trivy-scanning.md).

## How the pipeline gates on vulnerabilities

The `cd-docker-publish.yml` workflow scans each image on both platforms
(amd64 and arm64) using Trivy. Each scan step uses `continue-on-error:
true` so both platforms are scanned even if the first fails. A
subsequent "Trivy gate" step (`scripts/bin/trivy-gate`) checks each
platform and fails the job with one of two messages:

- `Trivy found CRITICAL/HIGH vulnerabilities in <image> (<platform>)` — the
  scan finished and wrote its report, and it has unsuppressed findings.
  Triage them as described below.
- `Trivy scan errored (no report produced) for <image> (<platform>)` — the
  scan wrote no report, even after retries. Both scans retry a scan that
  writes no report up to three times with backoff (the amd64 shared action
  since vergil-actions#1079, the arm64 `scripts/bin/trivy-image-scan`), so this
  means a persistent download or registry error, not a finding. The scan
  step's log has the Trivy error. A platform with no report never passes the
  gate (issue #721).

Scans filter against the `.trivyignore` file at the repository root.
CVEs listed there are excluded from the results. If all remaining
findings are below HIGH severity, the scan passes and the image is
promoted to the final tag.

When a scan fails, the candidate image is **not promoted** — the
consumer-facing tag still points to the last good build. Publishing is
blocked until the new CVEs are either suppressed or fixed.

## What the gate ignores automatically (`trivy.yaml`)

Both scan paths auto-load `trivy.yaml` from the repository root (they run
with the checkout mounted at `/workspace`), so a single config governs the
gate on both platforms without touching the shared `vergil-actions` Trivy
action. It applies two categorical filters so the gate only fires on
**actionable** findings:

- **`ignore-unfixed: true`** — the gate blocks only on CVEs that have an
  upstream fix (ones a rebuild or version bump can resolve). CVEs with
  `status=affected` and no fix are unactionable — blocking the publish does
  not make the image safer, since the last-good image carries the same
  unfixed CVE. They still appear in scan output; they just do not gate.
- **`ignore-policy: .trivy/ignore-policy.rego`** — drops all `linux-libc-dev`
  (kernel header) findings, which are always false positives (containers use
  the host kernel, not the baked-in headers), including the rare one that
  carries a distribution fix.

**Consequence for triage:** with these filters, a gate failure now means a
**fixed, non-kernel** CVE that is not yet in `.trivyignore`. That is either
something to actually fix (bump the pin / rebuild to pick up the patch) or,
if the fix is not yet reachable, a deliberate `.trivyignore` entry. The
old pattern of hand-adding every unfixed kernel/OS-library CVE nightly is no
longer necessary — those are filtered before they reach the gate. Many
existing `.trivyignore` entries for unfixed CVEs are now redundant and can be
pruned in a future cleanup pass.

## Step 1: Identify the failing CVEs

Pull the CVE IDs from the CI logs:

```bash
# List failed jobs and their log URLs
vrg-gh run view <run-id> --repo vergil-project/vergil-containers \
  | grep -E "X "

# Extract unique CVE IDs from the full run log
vrg-gh run view <run-id> --repo vergil-project/vergil-containers --log \
  | grep -oE "CVE-[0-9]+-[0-9]+" | sort -u

# Get package context for each CVE
vrg-gh run view <run-id> --repo vergil-project/vergil-containers --log \
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
| **No fixed release of the carrier** | The fix exists upstream, but no release of the binary or runtime that carries the vulnerable code ships it yet, so neither a rebuild nor a bump can reach it. The entry's removal condition names the release that will. |
| **Go binary transitive dependency** | A Go binary (scorecard, shfmt, etc.) includes a vulnerable dependency that the binary never exercises. |

A finding with no fix at all (`affected`) needs no entry: `ignore-unfixed`
already keeps it from gating.

### Fix (bump the dependency)

Fix when:

- A patched Ubuntu package exists and a rebuild picks it up: `base` and
  the package toolchain images run `apt-get upgrade` when they are built,
  and every image is rebuilt nightly.
- A finding is inside a runtime and a fixed release of that runtime exists:
  move the runtime as
  [Findings inside a runtime](#findings-inside-a-runtime) says, never
  patch it in place.
- A tool version bump resolves the CVE and is low-risk.
- The vulnerability is in a package we install directly (not inherited
  from the base image).

Fixing typically means bumping a version pin in a common fragment and
rebuilding. This is a separate PR from the triage suppression.

### Findings inside a runtime

A runtime in an image belongs to one owner, and a finding inside it, including
in the `npm` or `pip` the runtime bundles, is fixed only by that owner
(spec §5.8 of epic
[vergil-project/.github#649](https://github.com/vergil-project/.github/issues/649)).
vergil-containers never patches or upgrades anything inside a runtime: no
`npm install -g npm`, no `pip install --upgrade pip`, no edit of a bundled
`node_modules` or `site-packages`. Find the owner by the path Trivy reports:

| Path | Runtime | Fixed by |
| ---- | ------- | -------- |
| `/opt/vergil/python/<core>/` | The core Python, the `vergil-python<core>` package (`base` and every image built on it) | A vergil-python release, triaged in [vergil-python](https://github.com/vergil-project/vergil-python) |
| `/opt/vergil/node/<core-major>/` | The core Node, a pinned nodejs.org tarball (`base` and every image built on it) | Moving the core Node pin: the `node` entry for the manifest's `core.node` major in `docker/pins/toolchains.yml`, or the `core.node` major itself in a reviewed PR |
| `/opt/vergil/vergil-tooling/venv` | vergil-tooling's package venv, installed when a repo's container cache is built, so not in a published image | A vergil-tooling release |
| `/opt/python/<series>/` | A python family runtime, a pinned python-build-standalone release (`dev-python:<series>`) | Moving that series' pin in `docker/pins/toolchains.yml` |
| `/opt/node/<major>/` | A ts-node family runtime, a pinned nodejs.org tarball (`dev-ts-node:<major>`) | Moving that major's pin in `docker/pins/toolchains.yml` |

The daily upstream refresh moves each pin in `docker/pins/toolchains.yml` to
the newest release of its series or major, so a fix in a newer release
usually arrives as that refresh's PR. When no fixed release of the runtime
exists yet, the finding gets a `.trivyignore` entry under that file's rules: a
carrier group naming the runtime and its path, why the vulnerable code is not
exercised, and the removal condition (the release that fixes it). The groups
for the `npm` bundled in the Node tarballs are the model.

### Escalate

Escalate when:

- The CVE is CRITICAL and affects a code path that containers exercise.
- You are unsure whether the vulnerability is exploitable.
- The fix requires a breaking change or major version bump.

Flag the CVE to the team with your assessment and wait for a decision.

## Step 4: Create the issue and PR

### Create a tracking issue

```bash
vrg-gh issue create --repo vergil-project/vergil-containers \
  --title "triage HIGH CVEs blocking docker-publish (YYYY-MM-DD)" \
  --body-file <body-file>
```

The issue body should include a table of CVEs with package, fix status,
and rationale for each decision.

### Add suppressions to .trivyignore

Each entry must include a comment block explaining why the CVE is
suppressed. Follow the existing format:

```text
# <package> (<carrier>) — <brief description of the vulnerability>.
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

When the carrier of a previously-suppressed CVE ships a fix (a new tool
release, a runtime release its pin moves to, or an Ubuntu package update), the
entry should be removed from `.trivyignore` on the next triage pass.
Trivy will no longer flag the CVE once the image is built with the fixed
carrier, so the suppression becomes dead weight.

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
