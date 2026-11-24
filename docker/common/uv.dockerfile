# --- uv ----------------------------------------------------------------------
# Pinned uv release binary for the package toolchain images (pkg-ubuntu,
# pkg-rhel; epic vergil-project/.github#607), which carry no Python to
# `pip install` it from. UV_VERSION is auto-managed (docker/pins/pins.yml): the
# daily upstream refresh floats it. uv tags its releases with a bare `x.y.z`.
#
# Before extraction the tarball is verified against the per-architecture
# SHA-256 pinned here (UV_SHA256_AMD64 and _ARM64; vergil-containers#945),
# never against a checksum downloaded beside it: sha256sum -c fails the build
# on any mismatch. The daily upstream refresh writes both digests from the
# release's per-asset .sha256 in the same run that floats the version
# (resolve_latest.py, TOOL_DIGESTS), so every digest change shows in its
# refresh PR.
#
# It needs only curl, sha256sum and tar, so both distro families can include it.
# The tarball holds a uv-<triple>/ directory with uv and uvx; both land in
# /usr/local/bin.
ARG TARGETARCH
ARG UV_VERSION=0.13.10
ARG UV_SHA256_AMD64=bf65ac1a0af10f92c522d91ac096c7c0a39657647b155577e7836c2cbbb4526c
ARG UV_SHA256_ARM64=14590f644805a6234ffe071154340669e38137f38e60aa9629690119704107d2

RUN case "${TARGETARCH}" in \
      amd64) UV_TRIPLE=x86_64-unknown-linux-gnu; UV_SHA256="${UV_SHA256_AMD64}" ;; \
      arm64) UV_TRIPLE=aarch64-unknown-linux-gnu; UV_SHA256="${UV_SHA256_ARM64}" ;; \
      *) echo "uv: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    : "${UV_SHA256:?uv: no pinned SHA-256 for this TARGETARCH}" && \
    UV_TARBALL="uv-${UV_TRIPLE}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${UV_TARBALL}" \
      -o "/tmp/${UV_TARBALL}" && \
    echo "${UV_SHA256}  /tmp/${UV_TARBALL}" | sha256sum -c - && \
    tar -xzf "/tmp/${UV_TARBALL}" -C /usr/local/bin/ --strip-components=1 \
      "uv-${UV_TRIPLE}/uv" "uv-${UV_TRIPLE}/uvx" && \
    rm "/tmp/${UV_TARBALL}" && \
    uv --version
