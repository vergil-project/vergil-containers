# --- nfpm --------------------------------------------------------------------
# Pinned nfpm release binary — builds .deb and .rpm from one declarative config,
# no rpmbuild/dpkg host tooling. Base-image tool: package publishing is a
# cross-cutting need across the component family (the MQ family ships precompiled
# .rpm/.deb). nfpm release assets are named with x86_64/arm64, so amd64 needs
# arch translation (unlike OpenTofu). nfpm's checksums.txt lists a .sbom.json
# entry alongside each tarball, so we select the checksum line by exact filename
# field (awk) rather than a substring grep, which would match both. sha256sum -c
# fails loud on any mismatch, so a wrong pin can't slip through silently.
ARG TARGETARCH
ARG NFPM_VERSION=2.47.0

# hadolint ignore=DL3003
RUN NFPM_ARCH="$([ "${TARGETARCH}" = "amd64" ] && echo x86_64 || echo "${TARGETARCH}")" && \
    NFPM_TARBALL="nfpm_${NFPM_VERSION}_Linux_${NFPM_ARCH}.tar.gz" && \
    curl -fsSL "https://github.com/goreleaser/nfpm/releases/download/v${NFPM_VERSION}/${NFPM_TARBALL}" \
      -o "/tmp/${NFPM_TARBALL}" && \
    curl -fsSL "https://github.com/goreleaser/nfpm/releases/download/v${NFPM_VERSION}/checksums.txt" \
      | awk -v f="${NFPM_TARBALL}" '$2 == f' | (cd /tmp && sha256sum -c) && \
    tar -xzf "/tmp/${NFPM_TARBALL}" -C /usr/local/bin/ nfpm && \
    rm "/tmp/${NFPM_TARBALL}"
