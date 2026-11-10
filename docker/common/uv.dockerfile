# --- uv ----------------------------------------------------------------------
# Pinned uv release binary for the package toolchain images (pkg-ubuntu,
# pkg-rhel; epic vergil-project/.github#607), which carry no Python to
# `pip install` it from. The release tarball is verified against the release's
# own per-asset .sha256 before extraction: sha256sum -c fails loud on any
# mismatch, so a wrong pin can't slip through silently. UV_VERSION is
# auto-managed (docker/pins/pins.yml): the daily upstream refresh floats it.
#
# It needs only curl, sha256sum and tar, so both distro families can include it.
# The tarball holds a uv-<triple>/ directory with uv and uvx; both land in
# /usr/local/bin.
ARG TARGETARCH
ARG UV_VERSION=0.13.7

# hadolint ignore=DL3003
RUN case "${TARGETARCH}" in \
      amd64) UV_TRIPLE=x86_64-unknown-linux-gnu ;; \
      arm64) UV_TRIPLE=aarch64-unknown-linux-gnu ;; \
      *) echo "uv: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    UV_TARBALL="uv-${UV_TRIPLE}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${UV_TARBALL}" \
      -o "/tmp/${UV_TARBALL}" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${UV_TARBALL}.sha256" \
      -o "/tmp/${UV_TARBALL}.sha256" && \
    (cd /tmp && sha256sum -c "${UV_TARBALL}.sha256") && \
    tar -xzf "/tmp/${UV_TARBALL}" -C /usr/local/bin/ --strip-components=1 \
      "uv-${UV_TRIPLE}/uv" "uv-${UV_TRIPLE}/uvx" && \
    rm "/tmp/${UV_TARBALL}" "/tmp/${UV_TARBALL}.sha256" && \
    uv --version
