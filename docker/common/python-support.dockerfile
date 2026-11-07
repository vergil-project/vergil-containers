# --- Python + yamllint + ansible-lint + uv (for non-Python base images) ------
# uv, yamllint and ansible-lint float on their leading edge (spec §3, Tenet 1).
# astral.sh serves a version-less `install.sh` that resolves the latest uv.
#
# Fetch retries (issue #743): the script is downloaded to a file with curl's
# own retries, never piped to sh, so a dropped connection cannot run a
# truncated script and a failed download fails the RUN. The installer then
# fetches the uv release itself with no retry of its own, so it runs up to 3
# times (re-running it is idempotent); the third failure fails the RUN.
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3-minimal && \
    curl -LsSf --retry 5 --retry-all-errors --retry-delay 2 \
      "https://astral.sh/uv/install.sh" -o /tmp/uv-install.sh && \
    for attempt in 1 2 3; do \
      if UV_INSTALL_DIR=/usr/local/bin sh /tmp/uv-install.sh; then break; fi; \
      if [ "${attempt}" -eq 3 ]; then \
        echo "ERROR: the uv installer failed 3 times" >&2; \
        exit 1; \
      fi; \
      echo "uv installer attempt ${attempt} failed; retrying in 5s" >&2; \
      sleep 5; \
    done && \
    rm /tmp/uv-install.sh && \
    uv tool install yamllint && \
    uv tool install ansible-lint && \
    rm -rf /var/lib/apt/lists/*
