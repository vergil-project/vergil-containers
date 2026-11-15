# --- yq -------------------------------------------------------------------------
# mikefarah/yq, the Go YAML processor the GitHub-hosted runners carry, so the
# suites that use it in CI also run under `vrg-container-run -- vrg-validate`
# (vergil-containers#884). Its release binaries name the architecture exactly
# as TARGETARCH (yq_linux_amd64 / yq_linux_arm64), so no arch translation is
# needed.
#
# The release's `checksums` file has one line per asset, `<asset>` and then one
# column per hash algorithm, in the order `checksums_hashes_order` lists them.
# The SHA-256 column is found from that order file, not hard-coded, so a
# reordered release fails or still verifies, never checks the wrong hash. No
# SHA-256 entry, or no line (or more than one) for the asset, fails the build:
# grep exits 1 under pipefail, and the line-count test refuses anything but one
# line, so verification is never silently skipped.
ARG TARGETARCH
ARG YQ_VERSION=4.54.3

RUN YQ_BIN="yq_linux_${TARGETARCH}" && \
    YQ_URL="https://github.com/mikefarah/yq/releases/download/v${YQ_VERSION}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "${YQ_URL}/${YQ_BIN}" -o "/tmp/${YQ_BIN}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "${YQ_URL}/checksums" -o /tmp/yq_checksums && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "${YQ_URL}/checksums_hashes_order" -o /tmp/yq_checksums_hashes_order && \
    YQ_SHA_COL="$(grep -n -x 'SHA-256' /tmp/yq_checksums_hashes_order | cut -d: -f1)" && \
    awk -v asset="${YQ_BIN}" -v col="$((YQ_SHA_COL + 1))" \
      '$1 == asset { print $col "  /tmp/" asset }' /tmp/yq_checksums >/tmp/yq.sha256 && \
    test "$(grep -c . /tmp/yq.sha256)" = 1 && \
    sha256sum -c /tmp/yq.sha256 && \
    install -m 0755 "/tmp/${YQ_BIN}" /usr/local/bin/yq && \
    rm "/tmp/${YQ_BIN}" /tmp/yq_checksums /tmp/yq_checksums_hashes_order /tmp/yq.sha256
