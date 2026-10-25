# --- Node.js via NodeSource apt repo -----------------------------------------
ARG NODE_MAJOR=22
# @include common/nodesource-node.dockerfile

# Upgrade the NodeSource-bundled npm to the latest release before installing
# tools. NodeSource node 22 ships an older npm whose own vendored deps
# (node-tar, brace-expansion) carry HIGH/CRITICAL CVEs; npm@latest vendors the
# patched versions (tar >= 7.5.19, brace-expansion >= 5.0.7). npm 12's engine
# floor (^22.22.2) is satisfied by the NodeSource node 22.x line, and npm is
# build-time-only tooling (not invoked at container runtime). Issue #461.
#
# The `latest` dist-tag is npm 12.2.1 (checked 2026-10-24), which bundles
# brace-expansion 5.0.12 and undici 6.29.0 and so clears CVE-2026-102276 /
# CVE-2026-102278 / CVE-2026-19534. Issue #605 held the install at `^12.2.1`
# while `latest` was still 12.2.0; issue #678 returned it to `@latest`, so the
# nightly rebuild takes each new npm release, including a future major.
RUN npm install -g npm@latest && \
    npm install -g markdownlint-cli && \
    npm cache clean --force
