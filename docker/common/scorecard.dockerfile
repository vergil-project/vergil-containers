# --- OpenSSF Scorecard ------------------------------------------------------------
# Pinned scorecard release binary. SCORECARD_VERSION is auto-managed
# (docker/pins/pins.yml): the daily upstream refresh floats it. Its release
# tarballs name the architecture exactly as TARGETARCH (linux_amd64 /
# linux_arm64).
#
# Before extraction the tarball is verified against the per-architecture
# SHA-256 pinned here (SCORECARD_SHA256_AMD64 and _ARM64;
# vergil-containers#945), never against a checksum downloaded beside it:
# sha256sum -c fails the build on any mismatch. The daily upstream refresh
# writes both digests from the tarball's line in the release's
# scorecard_checksums.txt in the same run that floats the version
# (resolve_latest.py, TOOL_DIGESTS), so every digest change shows in its
# refresh PR. This fragment pins scorecard alone, so the refresh's path fence
# ties the digests to this tool's version.
ARG TARGETARCH
ARG SCORECARD_VERSION=5.6.0
ARG SCORECARD_SHA256_AMD64=19bde07129450cb65a95c6e3b9f34e034341579e6f0e241546ec3ae6efb2dd9a
ARG SCORECARD_SHA256_ARM64=3eacaceb3fdee6d0ba5df6ede45d1ada73321949029921bb63633802e8ec5951

RUN case "${TARGETARCH}" in \
      amd64) SC_SHA256="${SCORECARD_SHA256_AMD64}" ;; \
      arm64) SC_SHA256="${SCORECARD_SHA256_ARM64}" ;; \
      *) echo "scorecard: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    : "${SC_SHA256:?scorecard: no pinned SHA-256 for this TARGETARCH}" && \
    SC_TARBALL="scorecard_${SCORECARD_VERSION}_linux_${TARGETARCH}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/ossf/scorecard/releases/download/v${SCORECARD_VERSION}/${SC_TARBALL}" \
      -o "/tmp/${SC_TARBALL}" && \
    echo "${SC_SHA256}  /tmp/${SC_TARBALL}" | sha256sum -c - && \
    tar -xzf "/tmp/${SC_TARBALL}" -C /usr/local/bin/ scorecard && \
    rm "/tmp/${SC_TARBALL}"
