# --- Python + yamllint + uv (for non-Python base images) --------------------
ARG UV_VERSION=0.11.14
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3-minimal && \
    curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | UV_INSTALL_DIR=/usr/local/bin sh && \
    uv tool install yamllint==1.38.0 && \
    rm -rf /var/lib/apt/lists/*
