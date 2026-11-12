"""docker/build.sh's UPGRADE_DATE build argument (vergil-containers#845): one
UTC date per run, passed to every image whose Dockerfile declares it (the pkg-
images, before their OS upgrade) and to no other. build.sh runs for real on a
copy of docker/, with the container runtime stubbed."""
import json
import os
import shutil
import stat
import subprocess
from datetime import datetime, timezone

import pytest

import frozen

STUB_RUNTIME = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$STUB_LOG"
"""


def _build_sh(tmp_path, env=None):
    docker = tmp_path / "docker"
    shutil.copytree(frozen.LIVE_ROOT / "docker", docker,
                    ignore=shutil.ignore_patterns("Dockerfile", "__pycache__", ".pytest_cache"))
    live = json.loads((frozen.LIVE_ROOT / "docker" / "versions" / "matrix.json").read_text())["include"]
    rhel = next(e for e in live if e["language"] == "pkg-rhel")
    go = {**next(e for e in live if e["language"] == "go"), "parent": None, "depth": 0}
    (docker / "versions" / "matrix.json").write_text(json.dumps({"include": [rhel, go]}))
    stub = tmp_path / "bin" / "runtime"
    stub.parent.mkdir()
    stub.write_text(STUB_RUNTIME)
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "log"
    log.write_text("")
    run_env = {**os.environ, "VRG_CONTAINER_RUNTIME": str(stub), "STUB_LOG": str(log), **(env or {})}
    run_env.pop("VRG_APT_MIRROR", None)
    if env is None or "VRG_UPGRADE_DATE" not in env:
        run_env.pop("VRG_UPGRADE_DATE", None)
    result = subprocess.run([str(docker / "build.sh"), "pkg-rhel", "go"], env=run_env,
                            capture_output=True, text=True, check=False)
    builds = [line for line in log.read_text().splitlines() if line.startswith("build ")]
    return result, builds, rhel, go


def test_the_runs_utc_date_goes_only_to_an_image_that_declares_it(tmp_path):
    before = datetime.now(timezone.utc).date().isoformat()
    result, builds, rhel, go = _build_sh(tmp_path)
    after = datetime.now(timezone.utc).date().isoformat()
    assert result.returncode == 0, result.stdout + result.stderr
    rhel_build, go_build = builds
    assert rhel_build.startswith(f"build --build-arg RHEL_VERSION={rhel['version']} --build-arg UPGRADE_DATE=")
    assert any(f"--build-arg UPGRADE_DATE={d} " in rhel_build for d in (before, after))
    assert f"-t dev-pkg-rhel:{rhel['version']} " in rhel_build
    assert "UPGRADE_DATE" not in go_build
    assert f"-t dev-go:{go['version']} " in go_build


def test_vrg_upgrade_date_overrides_the_date(tmp_path):
    result, builds, _, _ = _build_sh(tmp_path, {"VRG_UPGRADE_DATE": "2026-01-31"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert " --build-arg UPGRADE_DATE=2026-01-31 " in builds[0]


@pytest.mark.parametrize("date", ["20260131", "2026-1-31", "2026-01-31 x"])
def test_a_malformed_vrg_upgrade_date_builds_nothing(tmp_path, date):
    result, builds, _, _ = _build_sh(tmp_path, {"VRG_UPGRADE_DATE": date})
    assert result.returncode == 2
    assert f"VRG_UPGRADE_DATE '{date}' is not a YYYY-MM-DD date" in result.stderr
    assert builds == []
