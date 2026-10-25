# --- Node.js from the NodeSource apt repo (fail-loud) ------------------------
# Requires NODE_MAJOR in scope (declare `ARG NODE_MAJOR` before including).
#
# Configures the NodeSource apt repo directly (keyring, sources.list.d entry,
# preferences pin) rather than piping setup_<major>.x to bash. That script
# exits 0 even when its own `apt update` fails, which once let Ubuntu's distro
# nodejs (no npm) stand in for NodeSource's Node (issue #657). Here:
#  - `apt-get update` fails on any index error (APT::Update::Error-Mode=any),
#    so a mirror caught mid-sync fails this step instead of leaving stale or
#    partial indexes;
#  - the pin gives NodeSource's nodejs priority 1000 and every other origin's
#    nodejs -1 (never installable), so a missing NodeSource index fails the
#    install rather than falling back to the distro package;
#  - the post-install check fails the build unless `node` is major NODE_MAJOR
#    and `npm` exists. The distro nodejs can share the major (Ubuntu ships a
#    22.x), so the pin and the npm check are what rule it out.
RUN install -d -m 0755 /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      -o /etc/apt/keyrings/nodesource.asc && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.asc] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list && \
    printf '%s\n' \
      'Package: nodejs' 'Pin: origin deb.nodesource.com' 'Pin-Priority: 1000' '' \
      'Package: nodejs' 'Pin: release *' 'Pin-Priority: -1' \
      > /etc/apt/preferences.d/nodesource && \
    apt-get update -o APT::Update::Error-Mode=any && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/* && \
    node_major="$(node --version | sed -E 's/^v([0-9]+)\..*/\1/')" && \
    if [ "${node_major}" != "${NODE_MAJOR}" ]; then \
      echo "ERROR: installed Node major is '${node_major}', expected '${NODE_MAJOR}' from NodeSource" >&2; \
      exit 1; \
    fi && \
    if ! command -v npm >/dev/null 2>&1; then \
      echo "ERROR: npm is missing after the NodeSource Node ${NODE_MAJOR} install" >&2; \
      exit 1; \
    fi
