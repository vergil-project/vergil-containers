# --- Node.js via NodeSource apt repo -----------------------------------------
ARG NODE_MAJOR=22
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

RUN npm install -g markdownlint-cli@0.48.0 && \
    npm cache clean --force
