# --- hadolint -------------------------------------------------------------------
# Pinned hadolint release binary, the Dockerfile linter. HADOLINT_VERSION is
# auto-managed (docker/pins/pins.yml): the daily upstream refresh floats it.
#
# Before it is installed, the binary is verified against the per-architecture
# SHA-256 pinned here (HADOLINT_SHA256_AMD64 and _ARM64; vergil-containers#945),
# never against a checksum downloaded beside it: sha256sum -c fails the build
# on any mismatch. The daily upstream refresh writes both digests from the
# asset's line in the release's checksums.sha256 in the same run that floats
# the version (resolve_latest.py, TOOL_DIGESTS), so every digest change shows
# in its refresh PR. This fragment pins hadolint alone, so the refresh's path
# fence ties the digests to this tool's version.
ARG TARGETARCH
ARG HADOLINT_VERSION=2.15.1
ARG HADOLINT_SHA256_AMD64=c7187db94eeeeca956519a6af171adc31453941a1e777961f6e680f697c8c507
ARG HADOLINT_SHA256_ARM64=f6198ef8090f404dbb771abfee086eb8c48ac177f30da7fd3510aca35b344b5d

RUN case "${TARGETARCH}" in \
      amd64) HL_ARCH=linux-x86_64; HL_SHA256="${HADOLINT_SHA256_AMD64}" ;; \
      arm64) HL_ARCH=linux-arm64; HL_SHA256="${HADOLINT_SHA256_ARM64}" ;; \
      *) echo "hadolint: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    : "${HL_SHA256:?hadolint: no pinned SHA-256 for this TARGETARCH}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-${HL_ARCH}" \
      -o "/tmp/hadolint-${HL_ARCH}" && \
    echo "${HL_SHA256}  /tmp/hadolint-${HL_ARCH}" | sha256sum -c - && \
    install -m 0755 "/tmp/hadolint-${HL_ARCH}" /usr/local/bin/hadolint && \
    rm "/tmp/hadolint-${HL_ARCH}" && \
    hadolint --version
