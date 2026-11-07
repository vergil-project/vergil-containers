"""Shape of .github/workflows/package-cache-warm.yml (issue #700).

The workflow keeps package-cleanup.yml's manifest cache from being evicted by
restoring it mid-week. It only works while its cache path and key match the
internal scheme of the ghcr-cleanup-action version the cleanup uses, and it must
never delete anything. These tests pin both, plus the schedule spacing, and run
the report and fail steps for real.
"""

import os
import subprocess

import pytest
import yaml

import frozen

WORKFLOWS = frozen.LIVE_ROOT / ".github" / "workflows"
WARM = WORKFLOWS / "package-cache-warm.yml"
CLEANUP = WORKFLOWS / "package-cleanup.yml"
RESTORE = "actions/cache/restore@v6"
# ghcr-cleanup-action v1.2.2, src/manifest-cache.ts: the cache directory is
# $RUNNER_TEMP/ghcr-cleanup-manifest-cache/<owner>-<package>, the key is
# ghcr-manifest-v1-<owner>-<package>-<run id>, restored by prefix.
CACHE_PATH = "${{ runner.temp }}/ghcr-cleanup-manifest-cache/vergil-project-${{ matrix.package }}"
KEY_PREFIX = "ghcr-manifest-v1-vergil-project-${{ matrix.package }}-"
MISS = "steps.touch.outputs.cache-matched-key == ''"
MAX_PARALLEL_CEILING = 4  # as in test_package_cleanup.py
# GitHub evicts a cache entry not accessed for 7 days; the scheduler starts
# runs hours late, so each gap must leave a wide margin.
MAX_GAP_DAYS = 4


def _load(path) -> dict:
    return yaml.safe_load(path.read_text())


def _job() -> dict:
    return _load(WARM)["jobs"]["warm"]


def _step(*, step_id: str | None = None, name: str | None = None) -> dict:
    for step in _job()["steps"]:
        if (step_id and step.get("id") == step_id) or (name and step.get("name") == name):
            return step
    raise AssertionError(f"no step id={step_id!r} name={name!r}")


def _run(script: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "PACKAGE": "dev-python", **extra_env}
    return subprocess.run(["bash", "-e", "-c", script], env=env, capture_output=True, text=True, check=False)


def _weekday(path) -> int:
    # PyYAML reads the bare `on:` key as boolean True.
    crons = _load(path)[True]["schedule"]
    assert len(crons) == 1, crons
    return int(crons[0]["cron"].split()[4])


def test_steps_in_order():
    ids_or_names = [s.get("id", s["name"]) for s in _job()["steps"]]
    assert ids_or_names == [
        "touch",
        "Report the cache state",
        "Rebuild the manifest cache (preview only)",
        "verify",
        "Fail if the cache is still cold",
    ]


@pytest.mark.parametrize("step_id", ["touch", "verify"])
def test_restores_match_the_action_cache_scheme(step_id):
    step = _step(step_id=step_id)
    assert step["uses"] == RESTORE
    assert step["with"] == {
        "path": CACHE_PATH,
        "key": KEY_PREFIX + "${{ github.run_id }}",
        "restore-keys": KEY_PREFIX,
    }


def test_touch_always_runs_and_rebuild_only_on_a_miss():
    assert "if" not in _step(step_id="touch")
    assert _step(name="Rebuild the manifest cache (preview only)")["if"] == MISS
    assert _step(step_id="verify")["if"] == MISS
    assert _step(name="Fail if the cache is still cold")["if"] == (
        f"{MISS} && steps.verify.outputs.cache-matched-key == ''"
    )


def test_rebuild_uses_the_cleanup_action_version_and_never_deletes():
    rebuild = _step(name="Rebuild the manifest cache (preview only)")
    cleanup_step = _load(CLEANUP)["jobs"]["cleanup"]["steps"][0]
    # Same version, so the cache scheme above is the one the cleanup uses.
    assert rebuild["uses"] == cleanup_step["uses"]
    inputs = rebuild["with"]
    assert inputs["owner"] == cleanup_step["with"]["owner"] == "vergil-project"
    assert inputs["packages"] == "${{ matrix.package }}"
    # A literal true, not an arming expression.
    assert inputs["dry-run"] is True
    # A selector that names one tag and no wildcard, so nothing is selected
    # and no fetched manifest is pruned from the saved cache.
    assert "*" not in inputs["delete-tags"] and "," not in inputs["delete-tags"]
    for selector in ("delete-untagged", "use-regex", "keep-n-untagged", "keep-n-tagged", "older-than"):
        assert selector not in inputs


def test_permissions_are_read_only():
    assert _load(WARM)["permissions"] == {"packages": "read", "contents": "read"}


def test_concurrency_group_is_its_own():
    # Sharing package-cleanup's group could cancel a pending cleanup run.
    assert _load(WARM)["concurrency"]["group"] != _load(CLEANUP)["concurrency"]["group"]


def test_matrix_covers_every_cleanup_package_with_a_capped_fan_out():
    strategy = _job()["strategy"]
    assert strategy["fail-fast"] is False
    assert 1 <= strategy["max-parallel"] <= MAX_PARALLEL_CEILING
    cleanup = _load(CLEANUP)["jobs"]["cleanup"]["strategy"]["matrix"]["package"]
    assert strategy["matrix"]["package"] == cleanup


def test_schedule_sits_between_cleanup_runs():
    warm, cleanup = _weekday(WARM), _weekday(CLEANUP)
    after_cleanup = (warm - cleanup) % 7
    before_cleanup = (cleanup - warm) % 7
    assert 0 < after_cleanup <= MAX_GAP_DAYS
    assert 0 < before_cleanup <= MAX_GAP_DAYS


def test_report_says_warm_on_a_hit():
    script = _step(name="Report the cache state")["run"]
    result = _run(script, {"MATCHED_KEY": "ghcr-manifest-v1-vergil-project-dev-python-123"})
    assert result.returncode == 0, result.stderr
    assert "::warning" not in result.stdout
    assert "dev-python is warm" in result.stdout
    assert "ghcr-manifest-v1-vergil-project-dev-python-123" in result.stdout


def test_report_warns_on_a_miss():
    script = _step(name="Report the cache state")["run"]
    result = _run(script, {"MATCHED_KEY": ""})
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("::warning title=Manifest cache cold::")
    assert "dev-python" in result.stdout


def test_still_cold_fails_loudly():
    script = _step(name="Fail if the cache is still cold")["run"]
    result = _run(script, {})
    assert result.returncode != 0
    line = result.stdout.strip()
    assert line.startswith("::error title=Manifest cache not found::")
    assert "dev-python" in line
    assert "#700" in line
