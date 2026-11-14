# --- apt mirror list and fail-fast config (amd64 and arm64) ------------------
# The package toolchain image pkg-ubuntu (epic vergil-project/.github#607) bakes
# in this apt configuration, so every apt call in a package job, install-test
# included, runs with it. This fragment is its only definition: vergil-actions'
# actions/package/setup, whose os-prereqs.sh once wrote it, has installed
# nothing since vergil-actions v2.1.62. vergil-tooling's
# lib/package/repo_setup.py passes the same fail-fast options on each apt
# command line (APT_FAIL_FAST); keep step 4 and it in step:
#
#   1. The archive the base image's sources name, read from the Ubuntu URIs
#      (http or https, with or without the trailing slash) on the active
#      lines of ubuntu.sources and the legacy sources.list, whichever exist.
#      The URIs choose the archive, not TARGETARCH, because the split moved:
#      ubuntu:24.04 on arm64 names ports.ubuntu.com/ubuntu-ports, while
#      ubuntu:26.04 serves arm64 from the main archive and names
#      archive.ubuntu.com and security.ubuntu.com, as amd64 always has
#      (vergil-project/vergil-containers#844):
#        ubuntu: the archive, security and azure.archive ubuntu.com/ubuntu
#                hosts, on amd64 and on arm64;
#        ports:  ports.ubuntu.com/ubuntu-ports, on arm64 only.
#      The build fails if the sources name any other ubuntu.com host, both
#      archives, or neither, or if they name ports on amd64. A URI outside
#      ubuntu.com (none in the base image) is left alone.
#   2. That archive's mirror list /etc/apt/apt-mirrors.txt, one
#      "<uri><TAB>priority:<n>" line per host, in priority order. Canonical's
#      own hosts come first, then fallbacks outside ubuntu.com, so one archive
#      host or a DNS failure of the whole ubuntu.com zone no longer breaks the
#      build (vergil-project/vergil-containers#837):
#        ubuntu: the in-region Azure mirror, archive.ubuntu.com and
#                security.ubuntu.com (GitHub's runner-images order), then
#                mirrors.edge.kernel.org and mirrors.dotsrc.org;
#        ports:  ports.ubuntu.com, then mirrors.dotsrc.org and mirrors.mit.edu
#                (ubuntu-ports, which none of the ubuntu hosts serve).
#      On 2026-11-12 every ubuntu host served resolute on both architectures
#      and noble on amd64 only, and every ports host served noble and
#      resolute on arm64, each suite current except the -updates and
#      -security of mirrors.edge.kernel.org (a day behind) and
#      mirrors.mit.edu (some hours behind). All are http: a fresh image has
#      no CA certificates until ca-certificates installs, and apt verifies
#      every index against the archive's signed InRelease, so a third-party
#      mirror cannot alter a package.
#      The APT_MIRROR build arg (docker/build.sh's VRG_APT_MIRROR) puts one
#      more http mirror first: for local builds near a faster mirror, of the
#      archive the sources name (on arm64, ubuntu-ports for 24.04 and ubuntu
#      for 26.04; apt fails over from one that serves neither). CI and
#      publish leave it empty.
#   3. Those URIs rewritten to mirror+file:/etc/apt/apt-mirrors.txt, so apt
#      fails over down the list instead of failing on one stalled host.
#   4. /etc/apt/apt.conf.d/80-vergil-fast-fail: 3 retries with no retry delay
#      (apt 2.4-2.8 deadlocks after a mirror-list failover with delayed
#      retries, https://bugs.launchpad.net/ubuntu/+source/apt/+bug/2003851),
#      20 s timeouts, a 60 s dpkg lock wait, and APT::Update::Error-Mode
#      "any" (apt-get update --error-on=any): an index that no mirror serves
#      fails apt-get update itself, where apt's default only warns and the
#      build fails later on a misleading "Unable to locate package". A host
#      that apt fails over from is not such an error.
#
# Any other architecture fails the build. The template's build-time check
# asserts the result on both. Include it before the first apt-get update.
ARG TARGETARCH
ARG APT_MIRROR=""

RUN mirror_list=/etc/apt/apt-mirrors.txt && \
    ubuntu_uri='https?://(azure\.archive|archive|security)\.ubuntu\.com/ubuntu/?' && \
    ports_uri='https?://(ports)\.ubuntu\.com/ubuntu-ports/?' && \
    case "${TARGETARCH}" in \
      amd64|arm64) ;; \
      *) echo "apt-mirror: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
    esac && \
    uris=/tmp/apt-mirror-uris && \
    for sources in /etc/apt/sources.list.d/ubuntu.sources /etc/apt/sources.list; do \
      if [ -f "${sources}" ]; then \
        sed -E 's/#.*//' "${sources}" | { grep -oE 'https?://[^[:space:]]+' || test $? -eq 1; } || exit 1; \
      fi; \
    done > "${uris}" && \
    other=$({ grep -vxE "${ubuntu_uri}|${ports_uri}" "${uris}" || test $? -eq 1; } | \
      { grep -iE '^https?://([^/]*\.)?ubuntu\.com\.?([:/]|$)' || test $? -eq 1; }) && \
    if [ -n "${other}" ]; then \
      echo "apt-mirror: the sources name an Ubuntu host with no mirror list: ${other}" >&2; exit 1; \
    fi && \
    archive='' && \
    if grep -qxE "${ubuntu_uri}" "${uris}"; then archive=ubuntu; fi && \
    if grep -qxE "${ports_uri}" "${uris}"; then \
      if [ -n "${archive}" ]; then \
        echo "apt-mirror: the sources name both the ubuntu and the ports archive; one mirror list serves one" >&2; exit 1; \
      fi; \
      archive=ports; \
    fi && \
    rm -f "${uris}" && \
    case "${archive}:${TARGETARCH}" in \
      ubuntu:*) \
        from="${ubuntu_uri}" && \
        set -- \
          'http://azure.archive.ubuntu.com/ubuntu/' \
          'http://archive.ubuntu.com/ubuntu/' \
          'http://security.ubuntu.com/ubuntu/' \
          'http://mirrors.edge.kernel.org/ubuntu/' \
          'http://mirrors.dotsrc.org/ubuntu/' ;; \
      ports:arm64) \
        from="${ports_uri}" && \
        set -- \
          'http://ports.ubuntu.com/ubuntu-ports/' \
          'http://mirrors.dotsrc.org/ubuntu-ports/' \
          'http://mirrors.mit.edu/ubuntu-ports/' ;; \
      ports:*) echo "apt-mirror: the sources name ports.ubuntu.com, which serves no ${TARGETARCH}" >&2; exit 1 ;; \
      *) echo "apt-mirror: no source names an Ubuntu archive host, so there is nothing to rewrite" >&2; exit 1 ;; \
    esac && \
    if [ -n "${APT_MIRROR}" ]; then \
      case "${APT_MIRROR}" in \
        *[[:space:]]*) echo "apt-mirror: APT_MIRROR '${APT_MIRROR}' contains whitespace" >&2; exit 1 ;; \
        http://?*) ;; \
        *) echo "apt-mirror: APT_MIRROR '${APT_MIRROR}' is not an http:// URI (no CA certificates yet for https)" >&2; exit 1 ;; \
      esac && \
      set -- "${APT_MIRROR%/}/" "$@"; \
    fi && \
    n=0 && \
    for uri in "$@"; do \
      n=$((n + 1)); \
      printf '%s\tpriority:%s\n' "${uri}" "${n}" || exit 1; \
    done > "${mirror_list}" && \
    for sources in /etc/apt/sources.list.d/ubuntu.sources /etc/apt/sources.list; do \
      if [ -f "${sources}" ]; then \
        sed -E -i "s#${from}([[:space:]]|\$)#mirror+file:${mirror_list}\\2#g" "${sources}" || exit 1; \
      fi; \
    done && \
    mkdir -p /etc/apt/apt.conf.d && \
    printf '%s\n' \
      'Acquire::Retries "3";' \
      'Acquire::Retries::Delay "false";' \
      'Acquire::http::Timeout "20";' \
      'Acquire::https::Timeout "20";' \
      'DPkg::Lock::Timeout "60";' \
      'APT::Update::Error-Mode "any";' \
      > /etc/apt/apt.conf.d/80-vergil-fast-fail
