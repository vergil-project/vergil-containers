# --- package toolchain marker ------------------------------------------------
# /etc/vergil/package-toolchain marks a package toolchain image (epic
# vergil-project/.github#607). The vergil-actions package setup action has
# installed no toolchain of its own since vergil-actions v2.1.62: it requires
# the marker, failing the job when it is missing, and checks every tool the
# marker lists against it (actions/package/setup/check-toolchain.sh). The
# contract, which that script reads:
#   - one "<tool> <version>" line per tool, separated by a single space;
#   - <tool> is a command name, looked up on PATH;
#   - <version> is the first [0-9]+(\.[0-9]+)+ token of `<tool> --version`'s
#     standard output;
#   - it always lists uv, nfpm, curl, git, gpg, tar and gzip.
# Each version is read here exactly as check-toolchain.sh reads it (stdout
# only, the same bash regex), so the marker cannot disagree with the check.
# A tool that is missing or prints no version fails the build. Include it last,
# after every tool it lists is installed. Needs bash (the template's SHELL).
# SC3054 (arrays undefined in POSIX sh) does not apply: this RUN runs under
# the template's bash SHELL, and BASH_REMATCH is what check-toolchain.sh reads.
# hadolint ignore=SC3054
RUN mkdir -p /etc/vergil && \
    version_re='[0-9]+(\.[0-9]+)+' && \
    : > /etc/vergil/package-toolchain && \
    for tool in uv nfpm curl git gpg tar gzip; do \
      output="$("${tool}" --version 2>/dev/null)" || { echo "marker: '${tool} --version' failed" >&2; exit 1; }; \
      [[ "${output}" =~ ${version_re} ]] || { echo "marker: '${tool} --version' printed no version" >&2; exit 1; }; \
      echo "${tool} ${BASH_REMATCH[0]}" >> /etc/vergil/package-toolchain; \
    done && \
    cat /etc/vergil/package-toolchain
