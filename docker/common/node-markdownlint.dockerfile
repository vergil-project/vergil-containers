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
RUN npm install -g npm@latest && \
    npm install -g markdownlint-cli && \
    npm cache clean --force
