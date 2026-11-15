# --- apt-get for steps that fetch from apt.llvm.org ---------------------------
# Installs /usr/local/libexec/vergil/llvm-apt-get, the apt-get every C++ image
# step runs once an apt.llvm.org source is configured (common/cpp-analysis
# includes this fragment before it adds that source; the compiler steps of
# cpp-clang and cpp-gcc come after it). Those steps fetched from apt.llvm.org
# unreliably on the arm64 runners (vergil-project/vergil-containers#904):
#   - apt connected to apt.llvm.org's IPv6 address, which the runners cannot
#     route ("connect (101: Network is unreachable)"), and failed the fetch;
#   - "Could not resolve 'apt.llvm.org'" failed both the index and the package
#     fetches.
# The 80-vergil-fast-fail config the image inherits (common/apt-mirror, through
# the pkg-ubuntu parent) does apply to these steps, but its "Acquire::Retries
# 3" retries with no delay, which it must keep for the mirror+file sources
# (apt 2.4-2.8 deadlocks after a mirror-list failover with delayed retries), so
# all its retries of a DNS failure land within a second, and each IPv6
# connection attempt fails the same way again.
#
# The wrapper therefore:
#   1. forces IPv4 (Acquire::ForceIPv4) and raises apt's own immediate retries
#      to 5 (Acquire::Retries), on that command line only, so the image's apt
#      configuration is unchanged;
#   2. reruns the whole apt-get command after 15 s and then 30 s, up to 3
#      attempts, to outlast a DNS outage of some seconds without delaying
#      apt's own retries. apt-get update and install are safe to rerun.
# When the last attempt fails, it prints the command and apt-get's exit status
# and exits with that status, so the build fails as loudly as plain apt-get.

# SC2016: the single-quoted lines are the wrapper's own script text, for its
# shell to expand when it runs, not this step's.
# hadolint ignore=SC2016
RUN install -d -m 0755 /usr/local/libexec/vergil && \
    printf '%s\n' \
      '#!/bin/sh' \
      '# apt-get for apt.llvm.org fetches: IPv4 only, with retries.' \
      '# Installed by vergil-containers docker/common/llvm-apt.dockerfile.' \
      'attempts=3' \
      'n=1' \
      'while :; do' \
      '  if apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=5 "$@"; then exit 0; else status=$?; fi' \
      '  if [ "${n}" -ge "${attempts}" ]; then' \
      '    echo "llvm-apt-get: apt-get $* failed on all ${attempts} attempts (exit ${status})" >&2' \
      '    exit "${status}"' \
      '  fi' \
      '  delay=$((15 * n))' \
      '  echo "llvm-apt-get: apt-get $* failed (exit ${status}), attempt ${n} of ${attempts}; retrying in ${delay} s" >&2' \
      '  sleep "${delay}"' \
      '  n=$((n + 1))' \
      'done' \
      > /usr/local/libexec/vergil/llvm-apt-get && \
    chmod 0755 /usr/local/libexec/vergil/llvm-apt-get
