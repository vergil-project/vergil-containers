# --- shfmt ----------------------------------------------------------------------
# Pinned shfmt release binary (mvdan/sh), the shell script formatter. Its
# release binaries name the architecture exactly as TARGETARCH
# (shfmt_v<version>_linux_amd64 / _arm64), so no arch translation is needed.
# SHFMT_VERSION is auto-managed (docker/pins/pins.yml): the daily upstream
# refresh floats it.
#
# Before it is installed, the binary is verified against the per-architecture
# SHA-256 pinned here (SHFMT_SHA256_AMD64 and _ARM64; vergil-containers#994):
# sha256sum -c fails the build on any mismatch. Upstream publishes no
# checksums, so the daily upstream refresh downloads each binary and writes
# its SHA-256 in the same run that floats the version (resolve_latest.py,
# TOOL_DIGESTS, the `asset` layout). That is trust on first sight at refresh
# time: every digest change shows in its refresh PR, and any later change to a
# pinned binary fails the build. This fragment pins shfmt alone, so the
# refresh's path fence ties the digests to this tool's version.
ARG TARGETARCH
ARG SHFMT_VERSION=3.14.1
ARG SHFMT_SHA256_AMD64=76e77641faa025814b77f153b29796b8e6fa2fca03e0c76a691608b86c7ea7bf
ARG SHFMT_SHA256_ARM64=5f2db09dae91fca848f7adbdd014632e921a383863a2ad7e0450ad3aba0c6489

RUN case "${TARGETARCH}" in \
      amd64) SHFMT_SHA256="${SHFMT_SHA256_AMD64}" ;; \
      arm64) SHFMT_SHA256="${SHFMT_SHA256_ARM64}" ;; \
      *) echo "shfmt: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    : "${SHFMT_SHA256:?shfmt: no pinned SHA-256 for this TARGETARCH}" && \
    SHFMT_BIN="shfmt_v${SHFMT_VERSION}_linux_${TARGETARCH}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/mvdan/sh/releases/download/v${SHFMT_VERSION}/${SHFMT_BIN}" \
      -o "/tmp/${SHFMT_BIN}" && \
    echo "${SHFMT_SHA256}  /tmp/${SHFMT_BIN}" | sha256sum -c - && \
    install -m 0755 "/tmp/${SHFMT_BIN}" /usr/local/bin/shfmt && \
    rm "/tmp/${SHFMT_BIN}" && \
    shfmt --version
