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
# /usr/local/bin, but for semgrep's, which are wrappers (see the semgrep
# stack-limit wrapper below). UV_PYTHON_DOWNLOADS=never keeps uv from fetching a managed
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

# --- semgrep stack-limit wrapper ---------------------------------------------
# semgrep and pysemgrep on PATH are wrappers, not uv's links
# (vergil-project/vergil-containers#825). Before it starts semgrep-core, semgrep
# (setrlimits_preexec_fn) sets the child's stack soft limit to a third of the
# hard limit. On Python 3.15 an unlimited hard limit reads as 2**64 - 1, not -1,
# so a third of it is a finite limit of about 5 EiB, and semgrep-core segfaults
# (exit -11) on every scan. Each wrapper lowers the stack hard limit to 2929688
# KiB, so that a third of it is 1,000,000,000 bytes, the limit semgrep-core gets
# on Python 3.14, then execs the entry point in the tool environment. It lowers
# the hard limit only when it is unlimited or larger, since an unprivileged
# process cannot raise it again and a caller's own lower limit is kept, and it
# lowers a larger soft limit with it, since a soft limit above the hard one is
# refused. If the limit cannot be set it warns on stderr and still execs.
# Remove the wrappers once semgrep fixes setrlimits_preexec_fn upstream
# (vergil-project/vergil-containers#826).
# SC2016: the wrapper's $-expansions are the wrapper's, written literally by printf.
# hadolint ignore=SC2016
RUN for name in semgrep pysemgrep; do \
      wrapper="/usr/local/bin/${name}"; \
      rm -f "${wrapper}" || exit 1; \
      printf '%s\n' \
        '#!/bin/sh' \
        '# Lowers the stack hard limit for semgrep-core, then runs semgrep: see' \
        '# vergil-project/vergil-containers#825. Remove once semgrep fixes' \
        '# setrlimits_preexec_fn (vergil-project/vergil-containers#826).' \
        'max=2929688' \
        'over() { [ "$1" = unlimited ] || [ "$1" -gt "$max" ]; }' \
        'if over "$(ulimit -H -s)"; then' \
        '  if over "$(ulimit -S -s)"; then ulimit -S -s "$max"; fi' \
        '  ulimit -H -s "$max" ||' \
        '    echo "semgrep wrapper: cannot lower the stack hard limit to $max KiB; semgrep-core may crash (vergil-project/vergil-containers#825)" >&2' \
        'fi' > "${wrapper}" || exit 1; \
      printf 'exec /opt/vergil/uv/tools/semgrep/bin/%s "$@"\n' "${name}" >> "${wrapper}" || exit 1; \
      chmod 0755 "${wrapper}" || exit 1; \
    done && \
    semgrep --version
