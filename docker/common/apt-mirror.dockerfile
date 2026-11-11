# --- apt mirror list and fail-fast config (amd64 and arm64) ------------------
# The package toolchain image pkg-ubuntu (epic vergil-project/.github#607) bakes
# in this apt configuration, so every apt call in a package job, install-test
# included, runs with it. This fragment is its only definition: vergil-actions'
# actions/package/setup, whose os-prereqs.sh once wrote it, has installed
# nothing since vergil-actions v2.1.62. vergil-tooling's
# lib/package/repo_setup.py passes the same fail-fast options on each apt
# command line (APT_FAIL_FAST); keep step 3 and it in step (its error mode is
# step 3's newest option, which APT_FAIL_FAST does not carry yet):
#
#   1. The mirror list /etc/apt/apt-mirrors.txt, one "<uri><TAB>priority:<n>"
#      line per host, in priority order. Canonical's own hosts come first,
#      then fallbacks outside ubuntu.com, so one archive host or a DNS failure
#      of the whole ubuntu.com zone no longer breaks the build
#      (vergil-project/vergil-containers#837):
#        amd64: the in-region Azure mirror, archive.ubuntu.com and
#               security.ubuntu.com (GitHub's runner-images order), then
#               mirrors.edge.kernel.org and mirrors.dotsrc.org;
#        arm64: ports.ubuntu.com, then mirrors.dotsrc.org and mirrors.mit.edu
#               (ubuntu-ports, which none of the amd64 hosts serve).
#      Each fallback served both architectures' noble and resolute -updates
#      and -security suites current (mirrors.mit.edu's -updates some hours
#      behind) on 2026-11-11, while ubuntu.com did not resolve. All are http:
#      a fresh image has no CA certificates until ca-certificates installs,
#      and apt verifies every index against the archive's signed InRelease,
#      so a third-party mirror cannot alter a package.
#      The APT_MIRROR build arg (docker/build.sh's VRG_APT_MIRROR) puts one
#      more http mirror, for the target architecture's archive, first: for
#      local builds near a faster mirror. CI and publish leave it empty.
#   2. The architecture's Ubuntu URIs (http or https, with or without the
#      trailing slash) in ubuntu.sources and the legacy sources.list,
#      whichever exist, rewritten to mirror+file:/etc/apt/apt-mirrors.txt, so
#      apt fails over down the list instead of failing on one stalled host:
#      the archive and security URIs on amd64, ports.ubuntu.com/ubuntu-ports
#      on arm64.
#   3. /etc/apt/apt.conf.d/80-vergil-fast-fail: 3 retries with no retry delay
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
    case "${TARGETARCH}" in \
      amd64) \
        from='https?://(azure\.archive|archive|security)\.ubuntu\.com/ubuntu/?([[:space:]]|$)' && \
        set -- \
          'http://azure.archive.ubuntu.com/ubuntu/' \
          'http://archive.ubuntu.com/ubuntu/' \
          'http://security.ubuntu.com/ubuntu/' \
          'http://mirrors.edge.kernel.org/ubuntu/' \
          'http://mirrors.dotsrc.org/ubuntu/' ;; \
      arm64) \
        from='https?://(ports)\.ubuntu\.com/ubuntu-ports/?([[:space:]]|$)' && \
        set -- \
          'http://ports.ubuntu.com/ubuntu-ports/' \
          'http://mirrors.dotsrc.org/ubuntu-ports/' \
          'http://mirrors.mit.edu/ubuntu-ports/' ;; \
      *) echo "apt-mirror: unsupported TARGETARCH '${TARGETARCH}'" >&2; exit 1 ;; \
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
        sed -E -i "s#${from}#mirror+file:${mirror_list}\\2#g" "${sources}" || exit 1; \
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
