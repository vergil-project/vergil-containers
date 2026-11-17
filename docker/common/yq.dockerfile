# --- yq -------------------------------------------------------------------------
# mikefarah/yq, the Go YAML processor the GitHub-hosted runners carry, so the
# suites that use it in CI also run under `vrg-container-run -- vrg-validate`
# (vergil-containers#884). Its release binaries name the architecture exactly
# as TARGETARCH (yq_linux_amd64 / yq_linux_arm64), so no arch translation is
# needed. YQ_VERSION is auto-managed (docker/pins/pins.yml): the daily upstream
# refresh floats it.
#
# Before it is installed, the binary is verified against the per-architecture
# SHA-256 pinned here (YQ_SHA256_AMD64 and _ARM64; vergil-containers#945),
# never against a checksum downloaded beside it: sha256sum -c fails the build
# on any mismatch. The daily upstream refresh writes both digests in the same
# run that floats the version (resolve_latest.py, TOOL_DIGESTS), so every
# digest change shows in its refresh PR. It reads them from the release's
# `checksums` file, one line per asset with one column per hash algorithm,
# finding the SHA-256 column from `checksums_hashes_order`, never by a
# hard-coded position, so a reordered release fails the refresh or still
# yields the SHA-256, never another algorithm's hash.
ARG TARGETARCH
ARG YQ_VERSION=4.54.3
ARG YQ_SHA256_AMD64=129534601871538efe0ba4c5e62a34fb1d5f469bcb975c4fddeb467d82974973
ARG YQ_SHA256_ARM64=89f69310b61b68d1245065a1241d1fc843f7a36cd6103ffd77ad987613bd1b67

RUN case "${TARGETARCH}" in \
      amd64) YQ_SHA256="${YQ_SHA256_AMD64}" ;; \
      arm64) YQ_SHA256="${YQ_SHA256_ARM64}" ;; \
      *) echo "yq: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    : "${YQ_SHA256:?yq: no pinned SHA-256 for this TARGETARCH}" && \
    YQ_BIN="yq_linux_${TARGETARCH}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/mikefarah/yq/releases/download/v${YQ_VERSION}/${YQ_BIN}" \
      -o "/tmp/${YQ_BIN}" && \
    echo "${YQ_SHA256}  /tmp/${YQ_BIN}" | sha256sum -c - && \
    install -m 0755 "/tmp/${YQ_BIN}" /usr/local/bin/yq && \
    rm "/tmp/${YQ_BIN}"
