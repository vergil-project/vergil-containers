# --- OpenTofu -----------------------------------------------------------------
# Pinned OpenTofu release binary for in-sandbox `tofu fmt -check` and
# `tofu init -backend=false && tofu validate` (syntax + type checking, no cloud
# credentials). OpenTofu's release artifacts name the architecture exactly as
# TARGETARCH (linux_amd64 / linux_arm64), so no arch translation is needed.
# OPENTOFU_VERSION is auto-managed (docker/pins/pins.yml): the daily upstream
# refresh floats it.
#
# Before extraction the tarball is verified against the per-architecture
# SHA-256 pinned here (OPENTOFU_SHA256_AMD64 and _ARM64;
# vergil-containers#945), never against a checksum downloaded beside it:
# sha256sum -c fails the build on any mismatch. The daily upstream refresh
# writes both digests from the tarball's line in the release's
# tofu_<version>_SHA256SUMS in the same run that floats the version
# (resolve_latest.py, TOOL_DIGESTS), so every digest change shows in its
# refresh PR.
ARG TARGETARCH
ARG OPENTOFU_VERSION=1.13.9
ARG OPENTOFU_SHA256_AMD64=b34b327cc1ef07178207b6f2cd1f5276537d3e5b7be316500f6dac50d4c0a857
ARG OPENTOFU_SHA256_ARM64=5dc196dde75b667e4806d358310ec96742774cd0993c54c1237efee5644b69b8

RUN case "${TARGETARCH}" in \
      amd64) TOFU_SHA256="${OPENTOFU_SHA256_AMD64}" ;; \
      arm64) TOFU_SHA256="${OPENTOFU_SHA256_ARM64}" ;; \
      *) echo "opentofu: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    : "${TOFU_SHA256:?opentofu: no pinned SHA-256 for this TARGETARCH}" && \
    TOFU_TARBALL="tofu_${OPENTOFU_VERSION}_linux_${TARGETARCH}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/opentofu/opentofu/releases/download/v${OPENTOFU_VERSION}/${TOFU_TARBALL}" \
      -o "/tmp/${TOFU_TARBALL}" && \
    echo "${TOFU_SHA256}  /tmp/${TOFU_TARBALL}" | sha256sum -c - && \
    tar -xzf "/tmp/${TOFU_TARBALL}" -C /usr/local/bin/ tofu && \
    rm "/tmp/${TOFU_TARBALL}"
