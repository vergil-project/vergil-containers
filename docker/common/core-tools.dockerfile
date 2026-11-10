# --- core Python tools -------------------------------------------------------
# base's Python CLI tools as uv tools on the core Python (epic
# vergil-project/.github#649, spec §5.2 and §5.2.1; include
# common/core-python.dockerfile first). Each is created with the core Python by
# its versioned path, in its own environment, so the tools' dependencies never
# meet each other or any family's interpreter. uv comes from the parent image
# (pkg-ubuntu). No pip install anywhere: nothing goes into any interpreter's own
# site-packages.
#   - yamllint, ansible-lint, semgrep: one environment each;
#   - mkdocs with mkdocs-material and mike in one environment, since mike must
#     see the material theme and its extensions. `--with` alone links no mike
#     executable, so `--with-executables-from mike` links it too.
# The environments live under /opt/vergil/uv/tools, beside the core runtimes,
# rather than in root's home: a consumer's own `uv tool install` (HOME is
# /github/home in GitHub's container jobs) never touches them. The path keeps
# uv's own `uv/tools` suffix, which ansible-lint recognises as a uv tool
# environment: it then adds its environment's bin to its own PATH without
# warning that the setup is broken. Their entry points are linked into
# /usr/local/bin. UV_PYTHON_DOWNLOADS=never keeps uv from fetching a managed
# interpreter in place of the core one.
#
# semgrep's dependency ruamel.yaml.clib publishes no wheel for the core 3.15, so
# it compiles: build-essential is installed for that install alone and purged in
# the same layer. vergil-python's sysconfig names clang as its compiler, so
# CC=gcc points the build at the gcc build-essential brings. Neither is needed
# once a wheel for the core series ships.
ARG CORE_PYTHON

RUN if [ -z "${CORE_PYTHON}" ]; then echo "core-tools: the CORE_PYTHON build arg is not set" >&2; exit 1; fi && \
    export UV_TOOL_DIR=/opt/vergil/uv/tools UV_TOOL_BIN_DIR=/usr/local/bin \
      UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1 && \
    core="/opt/vergil/python/${CORE_PYTHON}/bin/python${CORE_PYTHON}" && \
    uv tool install --python "${core}" yamllint && \
    uv tool install --python "${core}" ansible-lint && \
    uv tool install --python "${core}" mkdocs --with mkdocs-material --with-executables-from mike && \
    apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    CC=gcc uv tool install --python "${core}" semgrep && \
    apt-get purge -y --auto-remove build-essential && \
    rm -rf /var/lib/apt/lists/*
