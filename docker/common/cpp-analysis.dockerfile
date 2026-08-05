# --- Shared C++ analysis toolset (compiler-agnostic) -------------------------
# The compiler-agnostic analysis layer every C++ image carries, regardless of
# which compiler family (clang/gcc) it ships (spec vergil-project/.github#207
# §3.6, §4). It is the "shared base layer" of plan T1, expressed in this repo's
# established @include-fragment idiom rather than a separate FROM-chained base
# image (language images here never FROM one another — they compose fragments).
# Both docker/cpp-clang and the future docker/cpp-gcc include this fragment.
#
# Pinning: these tools follow the repo-wide floating doctrine (epic
# vergil-project/.github#155). cmake/cppcheck are fixed by the Debian release of
# the base image; clang-format/clang-tidy are fixed by the LLVM apt channel
# major (CLANG_TOOLS_VERSION); conan/gcovr float on their leading edge like
# every other uv-installed tool — none of those is an exact x.y.z pin, so this
# fragment carries no docker/pins/pins.yml entry.
ARG CLANG_TOOLS_VERSION=20

# clang-format / clang-tidy come from the official LLVM apt channel so the
# lint/format tools track a known-stable, prebuilt major (never built from
# source — spec §3.5). The snapshot GPG key signs every llvm-toolchain channel.
# update-alternatives also exposes the unversioned run-clang-tidy driver (shipped
# by the clang-tidy package as run-clang-tidy-${CLANG_TOOLS_VERSION}) so the LINT
# command resolves `run-clang-tidy` without a version suffix (issue #487).
RUN curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key \
      -o /etc/apt/trusted.gpg.d/apt.llvm.org.asc && \
    echo "deb http://apt.llvm.org/trixie/ llvm-toolchain-trixie-${CLANG_TOOLS_VERSION} main" \
      > "/etc/apt/sources.list.d/llvm-toolchain-${CLANG_TOOLS_VERSION}.list" && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      "clang-format-${CLANG_TOOLS_VERSION}" \
      "clang-tidy-${CLANG_TOOLS_VERSION}" \
      cppcheck \
      cmake \
      make \
      ninja-build \
      pkg-config && \
    update-alternatives --install /usr/bin/clang-format clang-format \
      "/usr/bin/clang-format-${CLANG_TOOLS_VERSION}" 100 && \
    update-alternatives --install /usr/bin/clang-tidy clang-tidy \
      "/usr/bin/clang-tidy-${CLANG_TOOLS_VERSION}" 100 && \
    update-alternatives --install /usr/bin/run-clang-tidy run-clang-tidy \
      "/usr/bin/run-clang-tidy-${CLANG_TOOLS_VERSION}" 100 && \
    rm -rf /var/lib/apt/lists/*

# Conan 2 (build/dependency manager) and gcovr (coverage) are Python tools; they
# float on their leading edge via uv, landing console scripts on the default
# PATH (see common/path-defaults.dockerfile).
RUN uv tool install conan && \
    uv tool install gcovr

# CONAN_HOME fixes Conan's home to a stable, HOME-independent path so the default
# profile baked in by each compiler image (via `conan profile detect`, issue #487)
# is found at runtime regardless of HOME. GitHub Actions forces HOME=/github/home
# in container jobs while local runs use /root (see common/path-defaults.dockerfile),
# so a profile under ~/.conan2 would be invisible in one context or the other;
# pinning CONAN_HOME makes `conan install` resolve the same baked profile in both.
ENV CONAN_HOME=/opt/conan2
