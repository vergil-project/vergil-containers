# --- apt mirror (amd64 only) and fail-fast config (every arch) ---------------
# The package toolchain image pkg-ubuntu (epic vergil-project/.github#607) bakes
# in this apt configuration, so every apt call in a package job, install-test
# included, runs with it. This fragment is its only definition: vergil-actions'
# actions/package/setup, whose os-prereqs.sh once wrote it, has installed
# nothing since vergil-actions v2.1.62. vergil-tooling's
# lib/package/repo_setup.py passes the same fail-fast options on each apt
# command line (APT_FAIL_FAST); keep step 3 and it in step:
#
#   1. The mirror list /etc/apt/apt-mirrors.txt, one "<uri><TAB>priority:<n>"
#      line per host, in GitHub's runner-images order and priorities: the
#      in-region Azure mirror first, then archive.ubuntu.com, then
#      security.ubuntu.com. All three are http: a fresh image has no CA
#      certificates until ca-certificates installs, and apt verifies every
#      index against the archive's signed InRelease anyway.
#   2. The Ubuntu archive and security URIs (http or https, with or without
#      the trailing slash) in ubuntu.sources and the legacy sources.list,
#      whichever exist, rewritten to mirror+file:/etc/apt/apt-mirrors.txt, so
#      apt fails over down the list instead of failing on one stalled host.
#   3. /etc/apt/apt.conf.d/80-vergil-fast-fail: 3 retries with no retry delay
#      (apt 2.4-2.8 deadlocks after a mirror-list failover with delayed
#      retries, https://bugs.launchpad.net/ubuntu/+source/apt/+bug/2003851),
#      20 s timeouts and a 60 s dpkg lock wait.
#
# Steps 1 and 2 are amd64 only: arm64 uses ports.ubuntu.com, which none of
# these mirrors serve, so a rewrite there would break apt. Step 3 runs on every
# architecture. The template's build-time check
# asserts both cases. Include it before the first apt-get update.
ARG TARGETARCH

RUN if [ "${TARGETARCH}" = "amd64" ]; then \
      mirror_list=/etc/apt/apt-mirrors.txt && \
      printf '%s\tpriority:%s\n' \
        'http://azure.archive.ubuntu.com/ubuntu/' 1 \
        'http://archive.ubuntu.com/ubuntu/' 2 \
        'http://security.ubuntu.com/ubuntu/' 3 \
        > "${mirror_list}" && \
      for sources in /etc/apt/sources.list.d/ubuntu.sources /etc/apt/sources.list; do \
        if [ -f "${sources}" ]; then \
          sed -E -i \
            's#https?://((azure\.)?archive|security)\.ubuntu\.com/ubuntu/?([[:space:]]|$)#mirror+file:/etc/apt/apt-mirrors.txt\3#g' \
            "${sources}" || exit 1; \
        fi; \
      done; \
    fi && \
    mkdir -p /etc/apt/apt.conf.d && \
    printf '%s\n' \
      'Acquire::Retries "3";' \
      'Acquire::Retries::Delay "false";' \
      'Acquire::http::Timeout "20";' \
      'Acquire::https::Timeout "20";' \
      'DPkg::Lock::Timeout "60";' \
      > /etc/apt/apt.conf.d/80-vergil-fast-fail
