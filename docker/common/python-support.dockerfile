# --- Python + yamllint + ansible-lint + uv (for non-Python base images) ------
# uv, yamllint and ansible-lint float on their leading edge (spec §3, Tenet 1).
# astral.sh serves a version-less `install.sh` that resolves the latest uv.
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3-minimal && \
    curl -LsSf "https://astral.sh/uv/install.sh" | UV_INSTALL_DIR=/usr/local/bin sh && \
    uv tool install yamllint && \
    uv tool install ansible-lint && \
    rm -rf /var/lib/apt/lists/*
