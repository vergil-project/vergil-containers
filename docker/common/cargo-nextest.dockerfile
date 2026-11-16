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
# https://nexte.st/docs/installation/release-urls/) redirects to. Before
# extraction it is verified against the per-architecture SHA-256 pinned here
# (CARGO_NEXTEST_SHA256_AMD64 and _ARM64; epic vergil-project/.github#1165,
# spec §6.3), never against a checksum downloaded beside it: sha256sum -c
# fails the build on any mismatch. The daily upstream refresh writes both
# digests from the release's per-asset .sha256 in the same run that floats the
# version (resolve_latest.py, TOOL_DIGESTS), so every digest change shows in
# its refresh PR. The tarball holds the single cargo-nextest binary (owned by
# the build user that packed it, hence --no-same-owner), which lands in cargo's
# bin directory beside the other cargo tools.
ARG TARGETARCH
ARG CARGO_NEXTEST_VERSION=0.9.152
ARG CARGO_NEXTEST_SHA256_AMD64=d039b43c3e0958441b6ad0a39c8884d018b3d2e8fb9928f209074b1100b5e17a
ARG CARGO_NEXTEST_SHA256_ARM64=ca1f81a5b86533eb45ab97e0064aa88e925e53aab9a698ca6331a7cad1f85f07

# hadolint ignore=DL3003
RUN case "${TARGETARCH}" in \
      amd64) NEXTEST_TRIPLE=x86_64-unknown-linux-gnu; NEXTEST_SHA256="${CARGO_NEXTEST_SHA256_AMD64}" ;; \
      arm64) NEXTEST_TRIPLE=aarch64-unknown-linux-gnu; NEXTEST_SHA256="${CARGO_NEXTEST_SHA256_ARM64}" ;; \
      *) echo "cargo-nextest: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    : "${NEXTEST_SHA256:?cargo-nextest: no pinned SHA-256 for this TARGETARCH}" && \
    NEXTEST_TAG="cargo-nextest-${CARGO_NEXTEST_VERSION}" && \
    NEXTEST_TARBALL="${NEXTEST_TAG}-${NEXTEST_TRIPLE}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/nextest-rs/nextest/releases/download/${NEXTEST_TAG}/${NEXTEST_TARBALL}" \
      -o "/tmp/${NEXTEST_TARBALL}" && \
    echo "${NEXTEST_SHA256}  /tmp/${NEXTEST_TARBALL}" | sha256sum -c - && \
    tar -xzf "/tmp/${NEXTEST_TARBALL}" --no-same-owner -C "${CARGO_HOME:?}/bin/" cargo-nextest && \
    rm "/tmp/${NEXTEST_TARBALL}" && \
    cargo nextest --version
