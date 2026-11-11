"""The python image's template on base (epic vergil-project/.github#649, plan
Task 8; spec §5.3 and §5.3.1). Structural facts about the live template and
manifest, not version lists, so a lifecycle PR never changes them (#654)."""
import re

import frozen
import generate as g
import includes
import manifest as mf
import resolve_toolchains as rt

LIVE_ROOT = frozen.LIVE_ROOT
TEMPLATE = LIVE_ROOT / "docker" / "python" / "Dockerfile.template"
_PIP_INSTALL_RE = re.compile(r"\bpip3?\s+install\b")


def _code_lines() -> list[str]:
    return [line for line in TEMPLATE.read_text().splitlines() if not line.lstrip().startswith("#")]


def test_python_parent_is_base():
    live = mf.load_manifest(LIVE_ROOT / "docker/versions/manifest.yml")
    (python,) = [f for f in live.families if f.key == "python"]
    assert python.parent == mf.Parent(mf.BASE_KEY, mf.BASE_VERSION)
    assert mf.entry_depths(live)["python"] == 2


def test_python_template_is_from_its_parent():
    instructions = [line for line in _code_lines() if re.match(r"^[A-Z]+ ", line)]
    assert instructions[:3] == ["ARG PARENT_IMAGE", "FROM ${PARENT_IMAGE}",
                                'SHELL ["/bin/bash", "-o", "pipefail", "-c"]']


def test_python_includes_nothing_base_installs():
    # base brings the common tooling and the core runtimes; the python image
    # adds only the family Python, so it includes no fragment at all.
    assert includes.fragments_of(TEMPLATE) == frozenset()


def test_python_installs_nothing_with_pip():
    found = [line for line in _code_lines() if _PIP_INSTALL_RE.search(line)]
    assert found == [], f"the python template runs pip install: {found}"
    assert "pytest-xdist" not in "\n".join(_code_lines())


def test_python_declares_every_toolchain_arg():
    # Every build arg generate.py emits for a python series is one the template
    # declares, so a pin always reaches the build.
    declared = set(re.findall(r"^ARG ([A-Z0-9_]+)", TEMPLATE.read_text(), re.MULTILINE))
    (series, *_) = frozen.PINS.series["python"]
    assert set(rt.build_args(frozen.PINS, "python", series)) <= declared
    assert {"PYTHON_VERSION", "TARGETARCH"} <= declared


def test_python_unpacks_at_opt_python_and_checks_the_hash():
    text = TEMPLATE.read_text()
    assert 'py_dir="/opt/python/${PYTHON_VERSION}"' in text
    assert 'sha256sum -c -' in text
    assert "uv python install" not in "\n".join(_code_lines())


def test_python_runs_its_checks_last():
    text = TEMPLATE.read_text()
    assert re.search(r'^RUN --mount=type=bind,source=checks.sh,.*\n\s+bash /tmp/vergil-checks.sh "\$\{PYTHON_VERSION\}"$',
                     text, re.MULTILINE)
    assert (TEMPLATE.parent / "checks.sh").stat().st_mode & 0o111, "checks.sh is not executable"
    checks = (TEMPLATE.parent / "checks.sh").read_text()
    # base's invariants and the one default the family keeps; python changes
    # python3 and pip, so it never reruns those defaults.
    assert '"${dir}/checks-invariants.sh"' in checks
    assert '"${dir}/checks-defaults.sh" check_no_node ' in checks
    assert "check_python3_is_core" not in checks.split("set -uo pipefail", 1)[1]
    assert "check_no_pip" not in checks.split("set -uo pipefail", 1)[1]


def test_python_doc_row_names_base():
    # The generated docs tables name the manifest parent as the image's base.
    live = mf.load_manifest(LIVE_ROOT / "docker/versions/manifest.yml")
    rows = g.render_doc_table(live, LIVE_ROOT)
    (row,) = [r for r in rows if r.startswith("| `dev-python`")]
    assert row.rstrip(" |").endswith("`base:latest`")
