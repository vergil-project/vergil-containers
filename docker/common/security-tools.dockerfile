# --- Security tools -----------------------------------------------------------
ARG TARGETARCH
ARG SCORECARD_VERSION=5.6.0
ARG TRIVY_VERSION=0.76.2

# hadolint ignore=DL3003
RUN SC_TARBALL="scorecard_${SCORECARD_VERSION}_linux_${TARGETARCH}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/ossf/scorecard/releases/download/v${SCORECARD_VERSION}/${SC_TARBALL}" \
      -o "/tmp/${SC_TARBALL}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/ossf/scorecard/releases/download/v${SCORECARD_VERSION}/scorecard_checksums.txt" \
      -o /tmp/scorecard_checksums.txt && \
    grep -F "${SC_TARBALL}" /tmp/scorecard_checksums.txt | (cd /tmp && sha256sum -c) && \
    tar -xzf "/tmp/${SC_TARBALL}" -C /usr/local/bin/ scorecard && \
    rm "/tmp/${SC_TARBALL}" /tmp/scorecard_checksums.txt

# hadolint ignore=DL3003
RUN case "${TARGETARCH}" in \
      amd64) TRIVY_ARCH="64bit" ;; \
      arm64) TRIVY_ARCH="ARM64" ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    TRIVY_TARBALL="trivy_${TRIVY_VERSION}_Linux-${TRIVY_ARCH}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/${TRIVY_TARBALL}" \
      -o "/tmp/${TRIVY_TARBALL}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_checksums.txt" \
      -o /tmp/trivy_checksums.txt && \
    grep -F "${TRIVY_TARBALL}" /tmp/trivy_checksums.txt | (cd /tmp && sha256sum -c) && \
    tar -xzf "/tmp/${TRIVY_TARBALL}" -C /usr/local/bin/ trivy && \
    rm "/tmp/${TRIVY_TARBALL}" /tmp/trivy_checksums.txt
