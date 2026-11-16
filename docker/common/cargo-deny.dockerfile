# --- cargo-deny ----------------------------------------------------------------
# Pinned cargo-deny release binary for the rust image (epic
# vergil-project/.github#1165, spec §6.3): the dependency checker that decides
# whether a Rust repo's advisories, licenses, bans and sources pass its gate. It
# is a validation tool, so it is pinned and verified like the toolchain, and is
# installed from cargo-deny's prebuilt release, never built with
# `cargo install`. CARGO_DENY_VERSION is auto-managed (docker/pins/pins.yml):
# the daily upstream refresh floats it. cargo-deny tags its releases with a
# bare `x.y.z`.
#
# The tarball is the release's statically linked
# `<arch>-unknown-linux-musl` asset. Before extraction it is verified against
# the per-architecture SHA-256 pinned here (CARGO_DENY_SHA256_AMD64 and
# _ARM64), never against a checksum downloaded beside it: sha256sum -c fails
# the build on any mismatch. The daily upstream refresh writes both digests
# from the release's per-asset .tar.gz.sha256 in the same run that floats the
# version (resolve_latest.py, TOOL_DIGESTS), so every digest change shows in
# its refresh PR. The tarball holds a `cargo-deny-<version>-<triple>/`
# directory (owned by the build user that packed it, hence --no-same-owner);
# only its cargo-deny binary is kept, in cargo's bin directory beside the other
# cargo tools.
ARG TARGETARCH
ARG CARGO_DENY_VERSION=0.21.0
ARG CARGO_DENY_SHA256_AMD64=a2170b854ff697e79e39c4c538981c9c1bdd803addbae6719a4cb66b4585a903
ARG CARGO_DENY_SHA256_ARM64=47cc5d88d43cd568028080fece02d729f56f0ff8e6c168563ce6589e3c0f4738

RUN case "${TARGETARCH}" in \
      amd64) DENY_TRIPLE=x86_64-unknown-linux-musl; DENY_SHA256="${CARGO_DENY_SHA256_AMD64}" ;; \
      arm64) DENY_TRIPLE=aarch64-unknown-linux-musl; DENY_SHA256="${CARGO_DENY_SHA256_ARM64}" ;; \
      *) echo "cargo-deny: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    : "${DENY_SHA256:?cargo-deny: no pinned SHA-256 for this TARGETARCH}" && \
    DENY_DIR="cargo-deny-${CARGO_DENY_VERSION}-${DENY_TRIPLE}" && \
    DENY_TARBALL="${DENY_DIR}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/EmbarkStudios/cargo-deny/releases/download/${CARGO_DENY_VERSION}/${DENY_TARBALL}" \
      -o "/tmp/${DENY_TARBALL}" && \
    echo "${DENY_SHA256}  /tmp/${DENY_TARBALL}" | sha256sum -c - && \
    tar -xzf "/tmp/${DENY_TARBALL}" --no-same-owner --strip-components=1 \
      -C "${CARGO_HOME:?}/bin/" "${DENY_DIR}/cargo-deny" && \
    rm "/tmp/${DENY_TARBALL}" && \
    cargo deny --version
