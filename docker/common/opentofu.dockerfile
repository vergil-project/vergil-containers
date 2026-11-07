# --- OpenTofu -----------------------------------------------------------------
# Pinned OpenTofu release binary for in-sandbox `tofu fmt -check` and
# `tofu init -backend=false && tofu validate` (syntax + type checking, no cloud
# credentials). OpenTofu's release artifacts name the architecture exactly as
# TARGETARCH (linux_amd64 / linux_arm64), so no arch translation is needed.
ARG TARGETARCH
ARG OPENTOFU_VERSION=1.13.9

# hadolint ignore=DL3003
RUN TOFU_TARBALL="tofu_${OPENTOFU_VERSION}_linux_${TARGETARCH}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/opentofu/opentofu/releases/download/v${OPENTOFU_VERSION}/${TOFU_TARBALL}" \
      -o "/tmp/${TOFU_TARBALL}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/opentofu/opentofu/releases/download/v${OPENTOFU_VERSION}/tofu_${OPENTOFU_VERSION}_SHA256SUMS" \
      -o /tmp/tofu_SHA256SUMS && \
    grep -F "${TOFU_TARBALL}" /tmp/tofu_SHA256SUMS | (cd /tmp && sha256sum -c) && \
    tar -xzf "/tmp/${TOFU_TARBALL}" -C /usr/local/bin/ tofu && \
    rm "/tmp/${TOFU_TARBALL}" /tmp/tofu_SHA256SUMS
