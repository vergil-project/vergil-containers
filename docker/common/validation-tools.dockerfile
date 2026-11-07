# --- Binary tools (no apt packages available) --------------------------------
# Architecture mapping: Docker buildx injects TARGETARCH (amd64 or arm64).
# Each tool uses different naming conventions for its release artifacts.
ARG TARGETARCH

ARG SHELLCHECK_VERSION=0.11.0
ARG SHFMT_VERSION=3.14.1
ARG ACTIONLINT_VERSION=1.7.12
ARG GIT_CLIFF_VERSION=2.14.2
ARG HADOLINT_VERSION=2.15.1

# hadolint >= 2.15.1 publishes a single checksums.sha256 (`<sha> *<asset>`)
# instead of a per-binary .sha256 (issue #602). The grep is anchored on the
# whole line (-x) so only the exact `hadolint-${HL_ARCH}` asset is selected;
# no match fails the build (grep exits 1 under pipefail, and `sha256sum -c`
# also exits 1 on empty input), so verification is never silently skipped.
#
# Fetch retries (issue #743): every build-time curl carries
# `--retry 5 --retry-all-errors --retry-delay 2` so a transient reset or 5xx
# is retried, and a download that still fails after the last attempt fails the
# RUN (-f). Every download goes to a file (-o), never to a pipe: curl discards
# a partial transfer's output before retrying only when it writes to a file, so
# a retried pipe could feed duplicated bytes downstream.
# docker/pins/test_fetch_retries.py enforces both rules on every fragment.
# hadolint ignore=DL3003
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
    SC_TARBALL="shellcheck-v${SHELLCHECK_VERSION}.linux.${SC_ARCH}.tar.xz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/${SC_TARBALL}" \
      -o "/tmp/${SC_TARBALL}" && \
    tar -xJf "/tmp/${SC_TARBALL}" --strip-components=1 -C /usr/local/bin/ "shellcheck-v${SHELLCHECK_VERSION}/shellcheck" && \
    rm "/tmp/${SC_TARBALL}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/mvdan/sh/releases/download/v${SHFMT_VERSION}/shfmt_v${SHFMT_VERSION}_linux_${SHFMT_ARCH}" \
      -o /usr/local/bin/shfmt && chmod +x /usr/local/bin/shfmt && \
    AL_TARBALL="actionlint_${ACTIONLINT_VERSION}_linux_${AL_ARCH}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/${AL_TARBALL}" \
      -o "/tmp/${AL_TARBALL}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_checksums.txt" \
      -o /tmp/actionlint_checksums.txt && \
    grep -F "${AL_TARBALL}" /tmp/actionlint_checksums.txt | (cd /tmp && sha256sum -c) && \
    tar -xzf "/tmp/${AL_TARBALL}" -C /usr/local/bin/ actionlint && \
    rm "/tmp/${AL_TARBALL}" /tmp/actionlint_checksums.txt && \
    GC_TARBALL="git-cliff-${GIT_CLIFF_VERSION}-${GC_ARCH}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/orhun/git-cliff/releases/download/v${GIT_CLIFF_VERSION}/${GC_TARBALL}" \
      -o "/tmp/${GC_TARBALL}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/orhun/git-cliff/releases/download/v${GIT_CLIFF_VERSION}/${GC_TARBALL}.sha512" \
      -o "/tmp/${GC_TARBALL}.sha512" && \
    (cd /tmp && sha512sum -c "${GC_TARBALL}.sha512") && \
    tar -xzf "/tmp/${GC_TARBALL}" --strip-components=1 -C /usr/local/bin/ "git-cliff-${GIT_CLIFF_VERSION}/git-cliff" && \
    rm "/tmp/${GC_TARBALL}" "/tmp/${GC_TARBALL}.sha512" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-${HL_ARCH}" \
      -o "/tmp/hadolint-${HL_ARCH}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/checksums.sha256" \
      -o /tmp/hadolint_checksums.sha256 && \
    grep -x -E "[0-9a-f]{64} [ *]hadolint-${HL_ARCH}" /tmp/hadolint_checksums.sha256 \
      | (cd /tmp && sha256sum -c) && \
    mv "/tmp/hadolint-${HL_ARCH}" /usr/local/bin/hadolint && chmod +x /usr/local/bin/hadolint && \
    rm /tmp/hadolint_checksums.sha256
