# --- shellcheck -----------------------------------------------------------------
# Pinned ShellCheck release tarball, the shell script linter.
# SHELLCHECK_VERSION is auto-managed (docker/pins/pins.yml): the daily upstream
# refresh floats it.
#
# Before it is unpacked, the tarball is verified against the per-architecture
# SHA-256 pinned here (SHELLCHECK_SHA256_AMD64 and _ARM64; vergil-containers#994):
# sha256sum -c fails the build on any mismatch. Upstream publishes no
# checksums, so the daily upstream refresh downloads each tarball and writes
# its SHA-256 in the same run that floats the version (resolve_latest.py,
# TOOL_DIGESTS, the `asset` layout). That is trust on first sight at refresh
# time: every digest change shows in its refresh PR, and any later change to a
# pinned tarball fails the build. This fragment pins shellcheck alone, so the
# refresh's path fence ties the digests to this tool's version.
ARG TARGETARCH
ARG SHELLCHECK_VERSION=0.11.0
ARG SHELLCHECK_SHA256_AMD64=8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198
ARG SHELLCHECK_SHA256_ARM64=12b331c1d2db6b9eb13cfca64306b1b157a86eb69db83023e261eaa7e7c14588

RUN case "${TARGETARCH}" in \
      amd64) SC_ARCH=x86_64; SC_SHA256="${SHELLCHECK_SHA256_AMD64}" ;; \
      arm64) SC_ARCH=aarch64; SC_SHA256="${SHELLCHECK_SHA256_ARM64}" ;; \
      *) echo "shellcheck: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    : "${SC_SHA256:?shellcheck: no pinned SHA-256 for this TARGETARCH}" && \
    SC_TARBALL="shellcheck-v${SHELLCHECK_VERSION}.linux.${SC_ARCH}.tar.xz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/${SC_TARBALL}" \
      -o "/tmp/${SC_TARBALL}" && \
    echo "${SC_SHA256}  /tmp/${SC_TARBALL}" | sha256sum -c - && \
    tar -xJf "/tmp/${SC_TARBALL}" --strip-components=1 -C /usr/local/bin/ "shellcheck-v${SHELLCHECK_VERSION}/shellcheck" && \
    rm "/tmp/${SC_TARBALL}" && \
    shellcheck --version
