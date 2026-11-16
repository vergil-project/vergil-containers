# --- cargo-llvm-cov ------------------------------------------------------------
# Pinned cargo-llvm-cov for the rust image (epic vergil-project/.github#1165,
# spec §6.3): the coverage tool that decides whether a Rust repo meets its
# coverage gate. It is a validation tool, so its version is pinned in source
# like the toolchain's. CARGO_LLVM_COV_VERSION is auto-managed
# (docker/pins/pins.yml): the daily upstream refresh floats it from
# taiki-e/cargo-llvm-cov's `vX.Y.Z` release tags.
#
# It is built from crates.io, not taken from a release binary: its release
# assets carry no checksum files and their names carry no version, so there is
# no versioned asset to pin a digest for. Cargo verifies the crate's checksum
# against the crates.io index, and --locked builds it from the lockfile it
# publishes, so its dependencies are the versions upstream released with
# rather than whatever resolves on the day. The registry cache is removed
# afterwards, so the image keeps only the installed binary.
ARG CARGO_LLVM_COV_VERSION=0.9.1

RUN cargo install --locked "cargo-llvm-cov@${CARGO_LLVM_COV_VERSION}" && \
    rm -rf "${CARGO_HOME:?}/registry" && \
    cargo llvm-cov --version
