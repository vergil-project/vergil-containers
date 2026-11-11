# --- vergil apt repository ---------------------------------------------------
# The vergil org's apt repository (epic vergil-project/.github#649, spec §5.2),
# set up as vergil-tooling's `lib/package/repo_setup.bootstrap` and the
# vergil-actions setup action (actions/shared/setup/vergil/install-tooling.sh)
# do on a host, in one layer and without sudo:
#   1. remove any bootstrap source or key an earlier step left;
#   2. if vergil-archive-keyring is already installed with its source and key,
#      check the installed key's primary fingerprint and stop there;
#   3. read the suite from the image's own /etc/os-release (noble);
#   4. download the signing key and fail unless it holds exactly one primary
#      key whose fingerprint is VERGIL_APT_FINGERPRINT, before any apt source
#      is written;
#   5. write a bootstrap source signed by that key;
#   6. install vergil-archive-keyring from the bootstrap source alone, then
#      remove the bootstrap source and key;
#   7. check that the keyring package left its permanent source
#      (/etc/apt/sources.list.d/vergil.sources) and a key with the pinned
#      fingerprint.
# A mismatch anywhere fails the build. The fingerprint is the one vergil-tooling
# pins in `lib/package/orgs.py`; a key rotation changes both in reviewed PRs.
# VERGIL_APT_URL is the repository root, overridden only to build this step
# against a test key.
ARG VERGIL_APT_FINGERPRINT=B3A1D804DC03AB036566A4E367861822166ECABE
ARG VERGIL_APT_URL=https://vergil-project.github.io/packages

# SC2016: the single-quoted awk program and dpkg-query format are not the
# shell's to expand.
# hadolint ignore=SC2016
RUN bootstrap_source=/etc/apt/sources.list.d/vergil-bootstrap.sources && \
    bootstrap_key=/etc/apt/keyrings/vergil-bootstrap.asc && \
    permanent_source=/etc/apt/sources.list.d/vergil.sources && \
    installed_key=/usr/share/keyrings/vergil-archive-keyring.asc && \
    fpr_awk='$1 == "pub" { n++; expecting = 1; next } $1 == "fpr" && expecting { fp = $10; expecting = 0 } END { if (n != 1 || fp == "") { print "primary keys: " n + 0; exit 1 } print fp }' && \
    tmp="$(mktemp -d)" && \
    export GNUPGHOME="${tmp}/gnupg" && \
    install -d -m 0700 "${GNUPGHOME}" && \
    rm -f "${bootstrap_source}" "${bootstrap_key}" && \
    if dpkg-query -W -f='${Status}' vergil-archive-keyring 2>/dev/null | grep -qx 'install ok installed' && \
       [ -e "${permanent_source}" ] && [ -e "${installed_key}" ]; then \
      echo "vergil-apt: vergil-archive-keyring is already installed; checking its key"; \
    else \
      codename=$(sed -n 's/^VERSION_CODENAME=//p' /etc/os-release | tr -d '"') && \
      if [ -z "${codename}" ]; then echo "vergil-apt: no VERSION_CODENAME in /etc/os-release" >&2; exit 1; fi && \
      curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
        "${VERGIL_APT_URL}/keys/vergil.asc" -o "${tmp}/vergil.asc" && \
      if ! got="$(gpg --show-keys --with-colons "${tmp}/vergil.asc" | awk -F: "${fpr_awk}")"; then \
        echo "vergil-apt: ${VERGIL_APT_URL}/keys/vergil.asc must hold exactly one primary key (${got})" >&2; exit 1; \
      fi && \
      if [ "${got}" != "${VERGIL_APT_FINGERPRINT}" ]; then \
        echo "vergil-apt: key fingerprint mismatch: published ${got}, pinned ${VERGIL_APT_FINGERPRINT}" >&2; exit 1; \
      fi && \
      echo "vergil-apt: ${VERGIL_APT_URL}/keys/vergil.asc: one primary key, fingerprint ${got}" && \
      install -D -m 0644 "${tmp}/vergil.asc" "${bootstrap_key}" && \
      printf 'Types: deb\nURIs: %s/deb\nSuites: %s\nComponents: main\nSigned-By: %s\n' \
        "${VERGIL_APT_URL}" "${codename}" "${bootstrap_key}" > "${bootstrap_source}" && \
      if apt-get -o "Dir::Etc::sourcelist=${bootstrap_source}" -o Dir::Etc::sourceparts=- update && \
         apt-get -o "Dir::Etc::sourcelist=${bootstrap_source}" -o Dir::Etc::sourceparts=- \
           install -y --no-install-recommends vergil-archive-keyring; then rc=0; else rc=$?; fi && \
      rm -f "${bootstrap_source}" "${bootstrap_key}" && \
      if [ "${rc}" -ne 0 ]; then echo "vergil-apt: installing vergil-archive-keyring failed (exit ${rc})" >&2; exit 1; fi && \
      if [ ! -e "${permanent_source}" ] || [ ! -e "${installed_key}" ]; then \
        echo "vergil-apt: vergil-archive-keyring left no ${permanent_source} or ${installed_key}" >&2; exit 1; \
      fi; \
    fi && \
    if ! got="$(gpg --show-keys --with-colons "${installed_key}" | awk -F: "${fpr_awk}")"; then \
      echo "vergil-apt: ${installed_key} must hold exactly one primary key (${got})" >&2; exit 1; \
    fi && \
    if [ "${got}" != "${VERGIL_APT_FINGERPRINT}" ]; then \
      echo "vergil-apt: installed key ${installed_key} has fingerprint ${got}, pinned ${VERGIL_APT_FINGERPRINT}" >&2; exit 1; \
    fi && \
    echo "vergil-apt: ${installed_key}: fingerprint ${got}; source ${permanent_source}" && \
    rm -rf "${tmp}" /var/lib/apt/lists/*
