# --- OSV-Scanner ---------------------------------------------------------------
# Dependency vulnerability scanner for the Java AUDIT stage (issue #689,
# vergil-project/vergil-tooling#3554): Maven writes a CycloneDX SBOM and
# `osv-scanner scan source --lockfile=target/bom.json` checks it against OSV.
# Upstream ships a bare binary per platform plus one osv-scanner_SHA256SUMS
# (`<sha>  <asset>`). The grep is anchored on the whole line (-x) so only the
# exact `osv-scanner_linux_${TARGETARCH}` asset is selected; no match fails the
# build (grep exits 1 under pipefail, and `sha256sum -c` also exits 1 on empty
# input), so verification is never silently skipped.
ARG TARGETARCH
ARG OSV_SCANNER_VERSION=2.7.0

# hadolint ignore=DL3003
RUN case "${TARGETARCH}" in \
      amd64|arm64) ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    OSV_ASSET="osv-scanner_linux_${TARGETARCH}" && \
    curl -fsSL "https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/${OSV_ASSET}" \
      -o "/tmp/${OSV_ASSET}" && \
    curl -fsSL "https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_SHA256SUMS" \
      | grep -x -E "[0-9a-f]{64} [ *]${OSV_ASSET}" \
      | (cd /tmp && sha256sum -c) && \
    mv "/tmp/${OSV_ASSET}" /usr/local/bin/osv-scanner && \
    chmod +x /usr/local/bin/osv-scanner && \
    osv-scanner --version
