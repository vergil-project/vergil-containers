# --- nfpm --------------------------------------------------------------------
# Pinned nfpm release binary — builds .deb and .rpm from one declarative config,
# no rpmbuild/dpkg host tooling. Base-image tool: package publishing is a
# cross-cutting need across the component family (the MQ family ships precompiled
# .rpm/.deb). nfpm release assets are named with x86_64/arm64, so amd64 needs
# arch translation (unlike OpenTofu). NFPM_VERSION is auto-managed
# (docker/pins/pins.yml): the daily upstream refresh floats it.
#
# Before extraction the tarball is verified against the per-architecture
# SHA-256 pinned here (NFPM_SHA256_AMD64 and _ARM64; vergil-containers#945),
# never against a checksum downloaded beside it: sha256sum -c fails the build
# on any mismatch. The daily upstream refresh writes both digests from the
# tarball's line in the release's checksums.txt (selected by exact file name,
# since it also lists a .sbom.json beside each tarball) in the same run that
# floats the version (resolve_latest.py, TOOL_DIGESTS), so every digest change
# shows in its refresh PR.
ARG TARGETARCH
ARG NFPM_VERSION=2.49.0
ARG NFPM_SHA256_AMD64=2afaa5ffb5e3493402e31e7c67a5a1fb42133e3f66fc315ca0051934125561c7
ARG NFPM_SHA256_ARM64=d4eee71839e92c68cbd3b101640bad32d2856fc551acae0635be9118e48c9d9c

RUN case "${TARGETARCH}" in \
      amd64) NFPM_ARCH=x86_64; NFPM_SHA256="${NFPM_SHA256_AMD64}" ;; \
      arm64) NFPM_ARCH=arm64; NFPM_SHA256="${NFPM_SHA256_ARM64}" ;; \
      *) echo "nfpm: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    : "${NFPM_SHA256:?nfpm: no pinned SHA-256 for this TARGETARCH}" && \
    NFPM_TARBALL="nfpm_${NFPM_VERSION}_Linux_${NFPM_ARCH}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/goreleaser/nfpm/releases/download/v${NFPM_VERSION}/${NFPM_TARBALL}" \
      -o "/tmp/${NFPM_TARBALL}" && \
    echo "${NFPM_SHA256}  /tmp/${NFPM_TARBALL}" | sha256sum -c - && \
    tar -xzf "/tmp/${NFPM_TARBALL}" -C /usr/local/bin/ nfpm && \
    rm "/tmp/${NFPM_TARBALL}"
