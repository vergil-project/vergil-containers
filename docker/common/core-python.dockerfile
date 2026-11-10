# --- core Python -------------------------------------------------------------
# The core Python base's own tools run on (epic vergil-project/.github#649,
# spec §5.2 and §5.2.1): the vergil-python<CORE_PYTHON> package from the vergil
# apt repository (include common/vergil-apt.dockerfile first), installed at
# /opt/vergil/python/<CORE_PYTHON>/. CORE_PYTHON is the manifest's core.python
# series, a build arg generate.py emits; within the series the image takes the
# package vergil-python publishes, and the build fails if it publishes none.
# Nothing is pip-installed into it: the directory belongs to the package.
#
# /usr/local/bin/python3 links to it and promises the standard library only
# (spec §5.5): the python family replaces the link, every other image keeps it.
ARG CORE_PYTHON

RUN if [ -z "${CORE_PYTHON}" ]; then echo "core-python: the CORE_PYTHON build arg is not set" >&2; exit 1; fi && \
    apt-get update && \
    apt-get install -y --no-install-recommends "vergil-python${CORE_PYTHON}" && \
    rm -rf /var/lib/apt/lists/* && \
    core="/opt/vergil/python/${CORE_PYTHON}/bin/python${CORE_PYTHON}" && \
    got="$("${core}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')" && \
    if [ "${got}" != "${CORE_PYTHON}" ]; then echo "core-python: ${core} is Python ${got}, want ${CORE_PYTHON}" >&2; exit 1; fi && \
    ln -s "${core}" /usr/local/bin/python3 && \
    /usr/local/bin/python3 --version
