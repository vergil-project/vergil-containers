"""The rust image's template (epic vergil-project/.github#1095, plan Task 3;
spec §6.3 and §6.6). Structural facts about the live template, not version
lists, so a lifecycle PR never changes them."""
import re
import subprocess

import pytest

import frozen

TEMPLATE = frozen.LIVE_ROOT / "docker" / "rust" / "Dockerfile.template"
_CASE_START = 'case "${TOOLCHAIN_VERSION}" in'
_CONTINUATION_RE = re.compile(r"\s*(&&\s*)?\\$")


def _series_check() -> str:
    """The template's `case "${TOOLCHAIN_VERSION}" in` block, read from the
    file (never copied), as a bash script: each continuation line with its
    trailing `\\` (and a closing `&&`) removed."""
    lines = TEMPLATE.read_text().splitlines()
    (start,) = [i for i, line in enumerate(lines) if _CASE_START in line]
    end = next(i for i in range(start, len(lines)) if lines[i].strip().startswith("esac"))
    return "\n".join(_CONTINUATION_RE.sub("", line) for line in lines[start:end + 1]) + "\n"


def _run_series_check(series: str, release: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", _series_check()],
                          env={"RUST_VERSION": series, "TOOLCHAIN_VERSION": release},
                          capture_output=True, text=True, check=False)


@pytest.mark.parametrize(("series", "release"), [
    ("1.100", "1.100.0"),
    ("1.99", "1.99.1"),
])
def test_rust_series_check_accepts_a_release_of_its_series(series, release):
    result = _run_series_check(series, release)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("series", "release"), [
    ("1.10", "1.100.0"),
    ("1.100", "1.10.0"),
    ("1.99", "1.100.0"),
])
def test_rust_series_check_three_digit_minor(series, release):
    # A three-digit minor is never taken for a two-digit one, either way: the
    # check compares whole components, not a string prefix.
    result = _run_series_check(series, release)
    assert result.returncode == 1
    assert f"TOOLCHAIN_VERSION {release} is not a release of Rust {series}" in result.stderr


def test_rust_pins_rustup_to_its_own_release():
    # Set after the install, from the exact release, with auto-install off: a
    # repo's rust-toolchain.toml or a request for another toolchain can neither
    # change the toolchain nor download one (spec §6.3).
    text = TEMPLATE.read_text()
    env = re.search(r"^ENV RUST_VERSION=\$\{TOOLCHAIN_VERSION\} \\\n"
                    r"\s+RUSTUP_TOOLCHAIN=\$\{TOOLCHAIN_VERSION\} \\\n"
                    r"\s+RUSTUP_AUTO_INSTALL=0$", text, re.MULTILINE)
    assert env, "the template does not set RUSTUP_TOOLCHAIN and RUSTUP_AUTO_INSTALL with RUST_VERSION"
    assert text.index("rustup-init -y") < env.start()
