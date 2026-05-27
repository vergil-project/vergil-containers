# --- Security tools -----------------------------------------------------------
ARG TARGETARCH
ARG SCORECARD_VERSION=5.5.0
ARG TRIVY_VERSION=0.70.0

# hadolint ignore=DL3003
RUN SC_TARBALL="scorecard_${SCORECARD_VERSION}_linux_${TARGETARCH}.tar.gz" && \
    curl -fsSL "https://github.com/ossf/scorecard/releases/download/v${SCORECARD_VERSION}/${SC_TARBALL}" \
      -o "/tmp/${SC_TARBALL}" && \
    curl -fsSL "https://github.com/ossf/scorecard/releases/download/v${SCORECARD_VERSION}/scorecard_checksums.txt" \
      | grep -F "${SC_TARBALL}" | (cd /tmp && sha256sum -c) && \
    tar -xzf "/tmp/${SC_TARBALL}" -C /usr/local/bin/ scorecard && \
    rm "/tmp/${SC_TARBALL}"

# hadolint ignore=DL3003
RUN case "${TARGETARCH}" in \
      amd64) TRIVY_ARCH="64bit" ;; \
      arm64) TRIVY_ARCH="ARM64" ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    TRIVY_TARBALL="trivy_${TRIVY_VERSION}_Linux-${TRIVY_ARCH}.tar.gz" && \
    curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/${TRIVY_TARBALL}" \
      -o "/tmp/${TRIVY_TARBALL}" && \
    curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_checksums.txt" \
      | grep -F "${TRIVY_TARBALL}" | (cd /tmp && sha256sum -c) && \
    tar -xzf "/tmp/${TRIVY_TARBALL}" -C /usr/local/bin/ trivy && \
    rm "/tmp/${TRIVY_TARBALL}"
