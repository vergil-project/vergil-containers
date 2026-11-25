# --- Binary tools (no apt packages available) --------------------------------
# Architecture mapping: Docker buildx injects TARGETARCH (amd64 or arm64).
# Each tool uses different naming conventions for its release artifacts.
ARG TARGETARCH

ARG GIT_CLIFF_VERSION=2.14.2

# hadolint, actionlint, shellcheck and shfmt, verified against digests pinned
# in source, have their own fragments: common/hadolint.dockerfile
# (vergil-containers#945), common/actionlint.dockerfile (vergil-containers#974),
# common/shellcheck.dockerfile and common/shfmt.dockerfile
# (vergil-containers#994).
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
        GC_ARCH="x86_64-unknown-linux-gnu" ;; \
      arm64) \
        GC_ARCH="aarch64-unknown-linux-gnu" ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    GC_TARBALL="git-cliff-${GIT_CLIFF_VERSION}-${GC_ARCH}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/orhun/git-cliff/releases/download/v${GIT_CLIFF_VERSION}/${GC_TARBALL}" \
      -o "/tmp/${GC_TARBALL}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/orhun/git-cliff/releases/download/v${GIT_CLIFF_VERSION}/${GC_TARBALL}.sha512" \
      -o "/tmp/${GC_TARBALL}.sha512" && \
    (cd /tmp && sha512sum -c "${GC_TARBALL}.sha512") && \
    tar -xzf "/tmp/${GC_TARBALL}" --strip-components=1 -C /usr/local/bin/ "git-cliff-${GIT_CLIFF_VERSION}/git-cliff" && \
    rm "/tmp/${GC_TARBALL}" "/tmp/${GC_TARBALL}.sha512"
