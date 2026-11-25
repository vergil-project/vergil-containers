# --- actionlint -----------------------------------------------------------------
# Pinned actionlint release tarball, the GitHub Actions workflow linter.
# ACTIONLINT_VERSION is auto-managed (docker/pins/pins.yml): the daily upstream
# refresh floats it.
#
# Before it is unpacked, the tarball is verified against the per-architecture
# SHA-256 pinned here (ACTIONLINT_SHA256_AMD64 and _ARM64; vergil-containers#974),
# never against a checksum downloaded beside it: sha256sum -c fails the build
# on any mismatch. The daily upstream refresh writes both digests from the
# tarball's line in the release's actionlint_<version>_checksums.txt in the same
# run that floats the version (resolve_latest.py, TOOL_DIGESTS), so every
# digest change shows in its refresh PR. This fragment pins actionlint alone, so
# the refresh's path fence ties the digests to this tool's version.
ARG TARGETARCH
ARG ACTIONLINT_VERSION=1.7.12
ARG ACTIONLINT_SHA256_AMD64=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
ARG ACTIONLINT_SHA256_ARM64=325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6

RUN case "${TARGETARCH}" in \
      amd64) AL_SHA256="${ACTIONLINT_SHA256_AMD64}" ;; \
      arm64) AL_SHA256="${ACTIONLINT_SHA256_ARM64}" ;; \
      *) echo "actionlint: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    : "${AL_SHA256:?actionlint: no pinned SHA-256 for this TARGETARCH}" && \
    AL_TARBALL="actionlint_${ACTIONLINT_VERSION}_linux_${TARGETARCH}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/${AL_TARBALL}" \
      -o "/tmp/${AL_TARBALL}" && \
    echo "${AL_SHA256}  /tmp/${AL_TARBALL}" | sha256sum -c - && \
    tar -xzf "/tmp/${AL_TARBALL}" -C /usr/local/bin/ actionlint && \
    rm "/tmp/${AL_TARBALL}" && \
    actionlint --version
