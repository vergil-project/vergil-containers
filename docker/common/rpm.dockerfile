# --- rpm ---------------------------------------------------------------------
# The distro's rpm, as the peer of the dpkg every Debian-family image already
# carries. Driver: package tests (vergil-tooling, vergil-python, …) verify .rpm
# version ordering for real via rpm.vercmp, not only .deb ordering via dpkg;
# without rpm those checks could only skip, hiding failures (issue #692). This
# is for inspection and version comparison only — packages are still built by
# nfpm (common/nfpm.dockerfile) with no rpmbuild host tooling.
#
# Unpinned by design: apt rpm floats cleanly by dropping the version, so it
# stays out of the docker/pins/ mechanism-pin set. See docker/pins/pins.yml.
#
# The image's own smoke check runs at build time, so every published image —
# every family, both platforms — is proven to carry a working rpm with its
# embedded Lua: `rpm --version` runs, and rpm.vercmp orders 1.0 before 1.1.
# Any failure, or any other output, fails the build loud.
RUN apt-get update && \
    apt-get install -y --no-install-recommends rpm && \
    rm -rf /var/lib/apt/lists/* && \
    rpm --version && \
    vercmp="$(rpm --eval '%{lua: print(rpm.vercmp("1.0", "1.1"))}')" && \
    if [ "${vercmp}" != "-1" ]; then \
      echo "rpm smoke check failed: rpm.vercmp(1.0, 1.1) printed '${vercmp}', want '-1'" >&2; \
      exit 1; \
    fi
