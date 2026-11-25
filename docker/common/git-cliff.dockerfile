# --- git-cliff ------------------------------------------------------------------
# Pinned git-cliff release tarball, the changelog generator.
# GIT_CLIFF_VERSION is auto-managed (docker/pins/pins.yml): the daily upstream
# refresh floats it.
#
# Before it is unpacked, the tarball is verified against the per-architecture
# SHA-256 pinned here (GIT_CLIFF_SHA256_AMD64 and _ARM64; vergil-containers#995),
# never against a checksum downloaded beside it: sha256sum -c fails the build
# on any mismatch. The release publishes only a SHA-512 per tarball, so the
# daily upstream refresh downloads each tarball, checks it against that
# <tarball>.sha512, and writes the tarball's SHA-256 in the same run that
# floats the version (resolve_latest.py, TOOL_DIGESTS, the `asset` layout with
# its SHA-512 cross-check). Every digest change shows in its refresh PR. This
# fragment pins git-cliff alone, so the refresh's path fence ties the digests
# to this tool's version.
ARG TARGETARCH
ARG GIT_CLIFF_VERSION=2.14.2
ARG GIT_CLIFF_SHA256_AMD64=24f397c733add5390fdceee3a2088588ab0d5f944ce00d34cb7029b888cf2db4
ARG GIT_CLIFF_SHA256_ARM64=69e208f6e4baef3a0f9b759d5f44223aa9336b86c691072a3d0c98d35a816e69

RUN case "${TARGETARCH}" in \
      amd64) GC_ARCH=x86_64-unknown-linux-gnu; GC_SHA256="${GIT_CLIFF_SHA256_AMD64}" ;; \
      arm64) GC_ARCH=aarch64-unknown-linux-gnu; GC_SHA256="${GIT_CLIFF_SHA256_ARM64}" ;; \
      *) echo "git-cliff: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    : "${GC_SHA256:?git-cliff: no pinned SHA-256 for this TARGETARCH}" && \
    GC_TARBALL="git-cliff-${GIT_CLIFF_VERSION}-${GC_ARCH}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/orhun/git-cliff/releases/download/v${GIT_CLIFF_VERSION}/${GC_TARBALL}" \
      -o "/tmp/${GC_TARBALL}" && \
    echo "${GC_SHA256}  /tmp/${GC_TARBALL}" | sha256sum -c - && \
    tar -xzf "/tmp/${GC_TARBALL}" --strip-components=1 -C /usr/local/bin/ "git-cliff-${GIT_CLIFF_VERSION}/git-cliff" && \
    rm "/tmp/${GC_TARBALL}" && \
    git-cliff --version
