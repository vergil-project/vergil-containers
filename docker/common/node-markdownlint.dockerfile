# --- Node.js via NodeSource apt repo -----------------------------------------
ARG NODE_MAJOR=22
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Upgrade the NodeSource-bundled npm to the latest release before installing
# tools. NodeSource node 22 ships an older npm whose own vendored deps
# (node-tar, brace-expansion) carry HIGH/CRITICAL CVEs; npm@latest vendors the
# patched versions (tar >= 7.5.19, brace-expansion >= 5.0.7). npm 12's engine
# floor (^22.22.2) is satisfied by the NodeSource node 22.x line, and npm is
# build-time-only tooling (not invoked at container runtime). Issue #461.
#
# Floor, not a pin: `^12.2.1` instead of `@latest`. npm 12.2.0 (the `latest`
# dist-tag as of 2026-10-16) bundles brace-expansion 5.0.9 and undici 6.28.0,
# which gate every image on CVE-2026-102276 / CVE-2026-102278 (brace-expansion
# < 5.0.11) and CVE-2026-19534 (undici < 6.28.1). npm 12.2.1 bundles
# brace-expansion 5.0.12 and undici 6.29.0 but is still on the `next-12` tag.
# A semver range that `latest` does not satisfy makes npm pick the highest
# matching release, so this resolves to 12.2.1 now and to `latest` once
# `latest` is >= 12.2.1. Revert to `npm@latest` once the `latest` dist-tag is
# >= 12.2.1, so a future npm major is not held back. Issue #605.
RUN npm install -g npm@^12.2.1 && \
    npm install -g markdownlint-cli && \
    npm cache clean --force
