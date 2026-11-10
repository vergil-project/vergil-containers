# --- core Node and markdownlint-cli ------------------------------------------
# The core Node base's one Node tool runs on (epic vergil-project/.github#649,
# spec §5.2 and §5.2.1): the nodejs.org prebuilt tarball pinned in
# docker/pins/toolchains.yml for the manifest's core.node major, unpacked at
# /opt/vergil/node/<CORE_NODE_MAJOR> after its SHA-256 for TARGETARCH is
# checked. generate.py emits the four CORE_NODE_* build args; a missing one, a
# version outside the major or a hash mismatch fails the build.
#
# No node, npm or npx goes on PATH: only the ts-node images have a default Node
# (spec §5.3). npm is itself an `#!/usr/bin/env node` script, so the one RUN
# that uses it puts the core Node's bin on PATH for that command alone.
# markdownlint on PATH is a wrapper that runs the tool with the core node by
# path, because npm's generated bin link starts with `#!/usr/bin/env node` and
# would pick up whatever node is on PATH, or fail where there is none.
#
# The bundled npm is the runtime's and is never upgraded in place (spec §5.8):
# a finding in it is fixed by moving the core Node pin, and until a fixed
# release exists it is a .trivyignore entry.
ARG TARGETARCH
ARG CORE_NODE_MAJOR
ARG CORE_NODE_VERSION
ARG CORE_NODE_SHA256_AMD64
ARG CORE_NODE_SHA256_ARM64

# SC2016: the wrapper's "$@" is the wrapper's, written literally by printf.
# hadolint ignore=SC2016
RUN : "${CORE_NODE_MAJOR:?core-node: the CORE_NODE_MAJOR build arg is not set}" && \
    : "${CORE_NODE_VERSION:?core-node: the CORE_NODE_VERSION build arg is not set}" && \
    : "${CORE_NODE_SHA256_AMD64:?core-node: the CORE_NODE_SHA256_AMD64 build arg is not set}" && \
    : "${CORE_NODE_SHA256_ARM64:?core-node: the CORE_NODE_SHA256_ARM64 build arg is not set}" && \
    case "${CORE_NODE_VERSION}" in \
      "${CORE_NODE_MAJOR}".*) ;; \
      *) echo "core-node: CORE_NODE_VERSION ${CORE_NODE_VERSION} is not a release of Node ${CORE_NODE_MAJOR}" >&2; exit 1 ;; \
    esac && \
    case "${TARGETARCH}" in \
      amd64) node_arch=x64; sha256="${CORE_NODE_SHA256_AMD64}" ;; \
      arm64) node_arch=arm64; sha256="${CORE_NODE_SHA256_ARM64}" ;; \
      *) echo "core-node: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    node_dir="/opt/vergil/node/${CORE_NODE_MAJOR}" && \
    tarball="node-v${CORE_NODE_VERSION}-linux-${node_arch}.tar.gz" && \
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      "https://nodejs.org/dist/v${CORE_NODE_VERSION}/${tarball}" -o "/tmp/${tarball}" && \
    echo "${sha256}  /tmp/${tarball}" | sha256sum -c - && \
    mkdir -p "${node_dir}" && \
    tar -xzf "/tmp/${tarball}" --strip-components=1 --no-same-owner -C "${node_dir}" && \
    rm "/tmp/${tarball}" && \
    got="$("${node_dir}/bin/node" --version)" && \
    if [ "${got}" != "v${CORE_NODE_VERSION}" ]; then echo "core-node: ${node_dir}/bin/node is ${got}, want v${CORE_NODE_VERSION}" >&2; exit 1; fi && \
    PATH="${node_dir}/bin:${PATH}" npm install -g markdownlint-cli && \
    PATH="${node_dir}/bin:${PATH}" npm cache clean --force && \
    printf '#!/bin/sh\nexec %s/bin/node %s/lib/node_modules/markdownlint-cli/markdownlint.js "$@"\n' \
      "${node_dir}" "${node_dir}" > /usr/local/bin/markdownlint && \
    chmod 0755 /usr/local/bin/markdownlint && \
    markdownlint --version
