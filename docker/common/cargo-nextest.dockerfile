# --- cargo-nextest -----------------------------------------------------------
# Pinned cargo-nextest release binary for the rust image (vergil-containers#885):
# the Rust test runner that writes JUnit reports on stable Rust, which
# `cargo test` cannot. It is installed from nextest's prebuilt binary
# (https://nexte.st/docs/installation/pre-built-binaries/), never built with
# `cargo install`. CARGO_NEXTEST_VERSION is auto-managed (docker/pins/pins.yml):
# the daily upstream refresh floats it.
#
# The tarball is the GitHub release asset that nextest's versioned download URL
# (https://get.nexte.st/<version>/linux, linux-arm for aarch64;
# https://nexte.st/docs/installation/release-urls/) redirects to. It is verified
# against the release's own per-asset .sha256 before extraction: sha256sum -c
# fails loud on any mismatch, so a wrong pin can't slip through silently. The
# tarball holds the single cargo-nextest binary (owned by the build user that
# packed it, hence --no-same-owner), which lands in cargo's bin directory
# beside the other cargo tools.
ARG TARGETARCH
ARG CARGO_NEXTEST_VERSION=0.9.152

# hadolint ignore=DL3003
RUN case "${TARGETARCH}" in \
      amd64) NEXTEST_TRIPLE=x86_64-unknown-linux-gnu ;; \
      arm64) NEXTEST_TRIPLE=aarch64-unknown-linux-gnu ;; \
      *) echo "cargo-nextest: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    NEXTEST_TAG="cargo-nextest-${CARGO_NEXTEST_VERSION}" && \
    NEXTEST_TARBALL="${NEXTEST_TAG}-${NEXTEST_TRIPLE}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/nextest-rs/nextest/releases/download/${NEXTEST_TAG}/${NEXTEST_TARBALL}" \
      -o "/tmp/${NEXTEST_TARBALL}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/nextest-rs/nextest/releases/download/${NEXTEST_TAG}/${NEXTEST_TAG}-${NEXTEST_TRIPLE}.sha256" \
      -o /tmp/cargo-nextest.sha256 && \
    (cd /tmp && sha256sum -c cargo-nextest.sha256) && \
    tar -xzf "/tmp/${NEXTEST_TARBALL}" --no-same-owner -C "${CARGO_HOME:?}/bin/" cargo-nextest && \
    rm "/tmp/${NEXTEST_TARBALL}" /tmp/cargo-nextest.sha256 && \
    cargo nextest --version
