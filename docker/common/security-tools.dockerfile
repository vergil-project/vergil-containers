# --- Trivy ----------------------------------------------------------------------
# Pinned trivy release binary. TRIVY_VERSION is auto-managed
# (docker/pins/pins.yml): the daily upstream refresh floats it, and the CI and
# publish Trivy gates run this same version (docker/pins/workflow_images.py).
# scorecard, the other security tool, has its own fragment,
# common/scorecard.dockerfile.
#
# Before extraction the tarball is verified against the per-architecture
# SHA-256 pinned here (TRIVY_SHA256_AMD64 and _ARM64; vergil-containers#945),
# never against a checksum downloaded beside it: sha256sum -c fails the build
# on any mismatch. The daily upstream refresh writes both digests from the
# tarball's line in the release's trivy_<version>_checksums.txt in the same
# run that floats the version (resolve_latest.py, TOOL_DIGESTS), so every
# digest change shows in its refresh PR. This fragment pins trivy alone, so
# the refresh's path fence ties the digests to this tool's version.
ARG TARGETARCH
ARG TRIVY_VERSION=0.76.2
ARG TRIVY_SHA256_AMD64=bc0fc726e017b8927a62b2d3531d7a84ee01769daf5c99ed866dced54089fdbf
ARG TRIVY_SHA256_ARM64=ab9d51f86e6a5fb936f605faff6b593ac51bc378fff4d3e8b9d58358b9c367c3

RUN case "${TARGETARCH}" in \
      amd64) TRIVY_ARCH=64bit; TRIVY_SHA256="${TRIVY_SHA256_AMD64}" ;; \
      arm64) TRIVY_ARCH=ARM64; TRIVY_SHA256="${TRIVY_SHA256_ARM64}" ;; \
      *) echo "trivy: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    : "${TRIVY_SHA256:?trivy: no pinned SHA-256 for this TARGETARCH}" && \
    TRIVY_TARBALL="trivy_${TRIVY_VERSION}_Linux-${TRIVY_ARCH}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/${TRIVY_TARBALL}" \
      -o "/tmp/${TRIVY_TARBALL}" && \
    echo "${TRIVY_SHA256}  /tmp/${TRIVY_TARBALL}" | sha256sum -c - && \
    tar -xzf "/tmp/${TRIVY_TARBALL}" -C /usr/local/bin/ trivy && \
    rm "/tmp/${TRIVY_TARBALL}"
