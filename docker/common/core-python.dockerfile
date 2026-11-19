# --- core Python -------------------------------------------------------------
# The core Python base's own tools run on (epic vergil-project/.github#649,
# spec §5.2 and §5.2.1): a uv-managed python-build-standalone install of the
# CORE_PYTHON series (epic vergil-project/.github#1350, spec §4.4), in the
# directory base publishes as VERGIL_CORE_PYTHON_DIR. CORE_PYTHON is the
# manifest's core.python series, a build arg generate.py emits; the patch is
# the newest release of the series that the parent's pinned uv offers, and the
# build log records it. The build fails unless it is a final release.
#
# The vergil-tooling installs (the cache build, the setup action in container
# jobs) read VERGIL_CORE_PYTHON_DIR and use it as UV_PYTHON_INSTALL_DIR with
# downloads off, so they run on this interpreter and never download one.
# UV_PYTHON_INSTALL_DIR is set for this install alone, never image-wide: a
# project's own uv commands see no managed interpreter. --no-bin leaves no
# python3.X link in root's ~/.local/bin. Nothing is pip-installed into it.
#
# /usr/local/bin/python3 links to it and promises the standard library only
# (spec §5.5): the python family replaces the link, every other image keeps it.
ARG CORE_PYTHON

RUN if [ -z "${CORE_PYTHON}" ]; then echo "core-python: the CORE_PYTHON build arg is not set" >&2; exit 1; fi && \
    if [ -z "${VERGIL_CORE_PYTHON_DIR}" ]; then echo "core-python: VERGIL_CORE_PYTHON_DIR is not set" >&2; exit 1; fi && \
    export UV_PYTHON_INSTALL_DIR="${VERGIL_CORE_PYTHON_DIR}" UV_NO_CACHE=1 && \
    unset UV_PYTHON UV_PYTHON_PREFERENCE UV_NO_MANAGED_PYTHON && \
    uv python install --no-config --no-bin "${CORE_PYTHON}" && \
    core="$(UV_PYTHON_DOWNLOADS=never uv python find --no-config --managed-python "${CORE_PYTHON}")" && \
    got="$("${core}" -c 'import sys; v = sys.version_info; print("%d.%d %s" % (v.major, v.minor, v.releaselevel))')" && \
    if [ "${got}" != "${CORE_PYTHON} final" ]; then echo "core-python: ${core} is Python ${got}, want a final ${CORE_PYTHON}" >&2; exit 1; fi && \
    ln -s "${core}" /usr/local/bin/python3 && \
    echo "core-python: $(/usr/local/bin/python3 --version) at ${core}"
