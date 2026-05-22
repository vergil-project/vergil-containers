# Checksum verification for binary tool downloads

## Problem

Binary tools in `docker/common/validation-tools.dockerfile` and
`docker/common/security-tools.dockerfile` are downloaded from GitHub
releases without integrity verification. Downloads should be verified
against published checksums where available.

## Scope

Only tools whose upstream projects publish checksums are verified.
Tools without published checksums (shellcheck, shfmt) are left as-is —
a locally-computed checksum has no future verification event since the
only trigger for re-download is a version bump, which produces a new
artifact.

## Verification matrix

| Tool       | File                          | Checksums asset pattern                                      | Algorithm | Format                 |
| ---------- | ----------------------------- | ------------------------------------------------------------ | --------- | ---------------------- |
| actionlint | `validation-tools.dockerfile` | `actionlint_{ver}_checksums.txt` (consolidated)              | SHA-256   | `HASH  filename`       |
| git-cliff  | `validation-tools.dockerfile` | `git-cliff-{ver}-{arch}.tar.gz.sha512` (sidecar)            | SHA-512   | `HASH  filename`       |
| hadolint   | `validation-tools.dockerfile` | `hadolint-{platform}.sha256` (sidecar)                       | SHA-256   | `HASH *filename`       |
| scorecard  | `security-tools.dockerfile`   | `scorecard_checksums.txt` (consolidated)                     | SHA-256   | `HASH  filename`       |
| shellcheck | `validation-tools.dockerfile` | *none published*                                             | —         | —                      |
| shfmt      | `validation-tools.dockerfile` | *none published*                                             | —         | —                      |

## Download pattern

Each verified tool follows a three-step pattern:

1. **Download** artifact to `/tmp/<exact-release-filename>` — the
   filename must match the name in the checksums file for `sha256sum -c`
   / `sha512sum -c` to work.
2. **Verify** — for consolidated checksums files: `curl checksums |
   grep -F filename | (cd /tmp && sha256sum -c)`. For sidecar files:
   `curl sidecar | (cd /tmp && sha256sum -c)` (or `sha512sum -c`).
   Uses `grep -F` (fixed-string) to avoid regex interpretation of
   dots in filenames.
3. **Extract/install** from the verified temp file, then clean up.

Build fails immediately on mismatch because `sha256sum -c` returns
non-zero, propagated by `&&` chaining.

## Checksums file formats (verified)

### actionlint — `actionlint_1.7.12_checksums.txt`

```text
8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8  actionlint_1.7.12_linux_amd64.tar.gz
325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6  actionlint_1.7.12_linux_arm64.tar.gz
```

Standard `sha256sum` output — hash, two spaces, filename.

### git-cliff — per-artifact `.sha512`

```text
e716cce3a07dda41b1e370d6afbd7a59eb3d4739509fb7856aeec8da2be28c03...  git-cliff-2.13.1-x86_64-unknown-linux-gnu.tar.gz
```

Standard format but SHA-512 (128 hex characters). Verified with
`sha512sum -c`.

### hadolint — per-artifact `.sha256`

```text
6bf226944684f56c84dd014e8b979d27425c0148f61b3bd99bcc6f39e9dc5a47 *hadolint-linux-x86_64
```

Binary-mode `sha256sum -b` output — hash, space, asterisk-prefixed
filename. `sha256sum -c` handles this correctly.

### scorecard — `scorecard_checksums.txt`

```text
83b90a05c1540ef1390db1cd5711e5fd04be9c1d8537fb84d39d02092d6a8dff  scorecard_5.5.0_linux_amd64.tar.gz
```

Standard `sha256sum` output.

## Implementation — `validation-tools.dockerfile`

The single `RUN` block is preserved (minimizes layers). Unchanged
tools (shellcheck, shfmt) keep their existing download patterns.

```dockerfile
ARG TARGETARCH

ARG SHELLCHECK_VERSION=0.11.0
ARG SHFMT_VERSION=3.13.1
ARG ACTIONLINT_VERSION=1.7.12
ARG GIT_CLIFF_VERSION=2.13.1
ARG HADOLINT_VERSION=2.14.0

RUN case "${TARGETARCH}" in
      amd64)
        SC_ARCH="x86_64" ;
        SHFMT_ARCH="amd64" ;
        AL_ARCH="amd64" ;
        GC_ARCH="x86_64-unknown-linux-gnu" ;
        HL_ARCH="linux-x86_64" ;;
      arm64)
        SC_ARCH="aarch64" ;
        SHFMT_ARCH="arm64" ;
        AL_ARCH="arm64" ;
        GC_ARCH="aarch64-unknown-linux-gnu" ;
        HL_ARCH="linux-arm64" ;;
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;;
    esac && \
    # --- shellcheck (no published checksums) ---
    curl -fsSL "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.${SC_ARCH}.tar.xz" \
      | tar -xJ --strip-components=1 -C /usr/local/bin/ "shellcheck-v${SHELLCHECK_VERSION}/shellcheck" && \
    # --- shfmt (no published checksums) ---
    curl -fsSL "https://github.com/mvdan/sh/releases/download/v${SHFMT_VERSION}/shfmt_v${SHFMT_VERSION}_linux_${SHFMT_ARCH}" \
      -o /usr/local/bin/shfmt && chmod +x /usr/local/bin/shfmt && \
    # --- actionlint (SHA-256, consolidated checksums file) ---
    AL_TARBALL="actionlint_${ACTIONLINT_VERSION}_linux_${AL_ARCH}.tar.gz" && \
    curl -fsSL "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/${AL_TARBALL}" \
      -o "/tmp/${AL_TARBALL}" && \
    curl -fsSL "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_checksums.txt" \
      | grep -F "${AL_TARBALL}" | (cd /tmp && sha256sum -c) && \
    tar -xzf "/tmp/${AL_TARBALL}" -C /usr/local/bin/ actionlint && \
    rm "/tmp/${AL_TARBALL}" && \
    # --- git-cliff (SHA-512, per-artifact sidecar) ---
    GC_TARBALL="git-cliff-${GIT_CLIFF_VERSION}-${GC_ARCH}.tar.gz" && \
    curl -fsSL "https://github.com/orhun/git-cliff/releases/download/v${GIT_CLIFF_VERSION}/${GC_TARBALL}" \
      -o "/tmp/${GC_TARBALL}" && \
    curl -fsSL "https://github.com/orhun/git-cliff/releases/download/v${GIT_CLIFF_VERSION}/${GC_TARBALL}.sha512" \
      | (cd /tmp && sha512sum -c) && \
    tar -xzf "/tmp/${GC_TARBALL}" --strip-components=1 -C /usr/local/bin/ "git-cliff-${GIT_CLIFF_VERSION}/git-cliff" && \
    rm "/tmp/${GC_TARBALL}" && \
    # --- hadolint (SHA-256, per-artifact sidecar) ---
    curl -fsSL "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-${HL_ARCH}" \
      -o "/tmp/hadolint-${HL_ARCH}" && \
    curl -fsSL "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-${HL_ARCH}.sha256" \
      | (cd /tmp && sha256sum -c) && \
    mv "/tmp/hadolint-${HL_ARCH}" /usr/local/bin/hadolint && chmod +x /usr/local/bin/hadolint
```

## Implementation — `security-tools.dockerfile`

```dockerfile
ARG TARGETARCH
ARG SCORECARD_VERSION=5.5.0

RUN SC_TARBALL="scorecard_${SCORECARD_VERSION}_linux_${TARGETARCH}.tar.gz" && \
    curl -fsSL "https://github.com/ossf/scorecard/releases/download/v${SCORECARD_VERSION}/${SC_TARBALL}" \
      -o "/tmp/${SC_TARBALL}" && \
    curl -fsSL "https://github.com/ossf/scorecard/releases/download/v${SCORECARD_VERSION}/scorecard_checksums.txt" \
      | grep -F "${SC_TARBALL}" | (cd /tmp && sha256sum -c) && \
    tar -xzf "/tmp/${SC_TARBALL}" -C /usr/local/bin/ scorecard && \
    rm "/tmp/${SC_TARBALL}"
```

## Unverified tools

shellcheck and shfmt do not publish checksums. Their download
patterns are unchanged. If either project adds checksums in the
future, verification can be added at that time.

## Testing

- `docker/generate.sh` to expand templates
- `hadolint docker/*/Dockerfile` to lint
- `docker/build.sh` for a full multi-image build (verifies downloads
  succeed with checksum validation)
