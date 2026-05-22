# --- Binary tools (no apt packages available) --------------------------------
# Architecture mapping: Docker buildx injects TARGETARCH (amd64 or arm64).
# Each tool uses different naming conventions for its release artifacts.
ARG TARGETARCH

ARG SHELLCHECK_VERSION=0.11.0
ARG SHFMT_VERSION=3.13.1
ARG ACTIONLINT_VERSION=1.7.12
ARG GIT_CLIFF_VERSION=2.13.1
ARG HADOLINT_VERSION=2.14.0

RUN case "${TARGETARCH}" in \
      amd64) \
        SC_ARCH="x86_64" ; \
        SHFMT_ARCH="amd64" ; \
        AL_ARCH="amd64" ; \
        GC_ARCH="x86_64-unknown-linux-gnu" ; \
        HL_ARCH="linux-x86_64" ;; \
      arm64) \
        SC_ARCH="aarch64" ; \
        SHFMT_ARCH="arm64" ; \
        AL_ARCH="arm64" ; \
        GC_ARCH="aarch64-unknown-linux-gnu" ; \
        HL_ARCH="linux-arm64" ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.${SC_ARCH}.tar.xz" \
      | tar -xJ --strip-components=1 -C /usr/local/bin/ "shellcheck-v${SHELLCHECK_VERSION}/shellcheck" && \
    curl -fsSL "https://github.com/mvdan/sh/releases/download/v${SHFMT_VERSION}/shfmt_v${SHFMT_VERSION}_linux_${SHFMT_ARCH}" \
      -o /usr/local/bin/shfmt && chmod +x /usr/local/bin/shfmt && \
    AL_TARBALL="actionlint_${ACTIONLINT_VERSION}_linux_${AL_ARCH}.tar.gz" && \
    curl -fsSL "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/${AL_TARBALL}" \
      -o "/tmp/${AL_TARBALL}" && \
    curl -fsSL "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_checksums.txt" \
      | grep -F "${AL_TARBALL}" | (cd /tmp && sha256sum -c) && \
    tar -xzf "/tmp/${AL_TARBALL}" -C /usr/local/bin/ actionlint && \
    rm "/tmp/${AL_TARBALL}" && \
    GC_TARBALL="git-cliff-${GIT_CLIFF_VERSION}-${GC_ARCH}.tar.gz" && \
    curl -fsSL "https://github.com/orhun/git-cliff/releases/download/v${GIT_CLIFF_VERSION}/${GC_TARBALL}" \
      -o "/tmp/${GC_TARBALL}" && \
    curl -fsSL "https://github.com/orhun/git-cliff/releases/download/v${GIT_CLIFF_VERSION}/${GC_TARBALL}.sha512" \
      | (cd /tmp && sha512sum -c) && \
    tar -xzf "/tmp/${GC_TARBALL}" --strip-components=1 -C /usr/local/bin/ "git-cliff-${GIT_CLIFF_VERSION}/git-cliff" && \
    rm "/tmp/${GC_TARBALL}" && \
    curl -fsSL "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-${HL_ARCH}" \
      -o "/tmp/hadolint-${HL_ARCH}" && \
    curl -fsSL "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-${HL_ARCH}.sha256" \
      | (cd /tmp && sha256sum -c) && \
    mv "/tmp/hadolint-${HL_ARCH}" /usr/local/bin/hadolint && chmod +x /usr/local/bin/hadolint
