# Release Workflow, Image Naming Convention, and Nightly Rebuilds — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a dev/prod image naming convention, wire up the release workflow, and add nightly CVE rebuilds — across standard-tooling-docker, standard-tooling, and standard-actions.

**Architecture:** The existing monolithic `docker-publish.yml` becomes a reusable `cd-docker-publish.yml` (workflow_call with `image-prefix` input). A thin `cd.yml` orchestrates docs, release, and docker-publish with branch-conditional prefix. `ops.yml` calls the same reusable workflow nightly for dev images. Consumer-side changes in standard-tooling make the image prefix configurable via `standard-tooling.toml`.

**Tech Stack:** GitHub Actions (reusable workflows), Python (standard-tooling config/docker libraries), TOML (config schema)

**Spec:** `docs/superpowers/specs/2026-05-09-release-workflow-and-image-naming-design.md`

---

## Phase 1: standard-tooling-docker workflow restructuring

All files in this phase are in the `standard-tooling-docker` repo under `.github/workflows/`.

### Task 1: Create cd-docker-publish.yml

**Files:**
- Create: `.github/workflows/cd-docker-publish.yml`
- Reference: `.github/workflows/docker-publish.yml` (current source, will be deleted in Task 4)

This is the largest task. Extract the current `docker-publish.yml` into a reusable `workflow_call`, parameterized by `image-prefix`.

- [ ] **Step 1: Create cd-docker-publish.yml with workflow_call trigger and permissions**

```yaml
name: Publish dev container images

on:
  workflow_call:
    inputs:
      image-prefix:
        description: "Image name prefix (dev or prod)"
        type: string
        required: true

permissions:
  packages: write
  contents: read
  security-events: write
  attestations: write
  id-token: write

concurrency:
  group: docker-publish-${{ inputs.image-prefix }}
  cancel-in-progress: true
```

Note: The concurrency group includes `image-prefix` so dev and prod publishes don't cancel each other if they overlap.

- [ ] **Step 2: Add the hadolint job**

Copy the `hadolint` job from `docker-publish.yml` unchanged:

```yaml
jobs:
  hadolint:
    name: Lint Dockerfiles
    runs-on: ubuntu-latest
    container:
      image: ghcr.io/wphillipmoore/dev-base:latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v6

      - name: Generate Dockerfiles from templates
        run: docker/generate.sh

      - name: Run Hadolint
        run: hadolint docker/*/Dockerfile
```

Note: This job references `dev-base:latest` for the linting container. This is intentional — it is the CI tooling container, not one of the images being published. It will be updated to `prod-base:latest` in Phase 4 (fleet sweep) after prod images exist.

- [ ] **Step 3: Add the build-scan-push job with parameterized image names**

Copy the `build-scan-push` job from `docker-publish.yml`. Change these four env vars to use the input prefix:

```yaml
  build-scan-push:
    name: "publish: ${{ inputs.image-prefix }}-${{ matrix.language }}:${{ matrix.version }}"
    needs: [hadolint]
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        include:
          - language: ruby
            version: "3.2"
            build-arg: RUBY_VERSION
          - language: ruby
            version: "3.3"
            build-arg: RUBY_VERSION
          - language: ruby
            version: "3.4"
            build-arg: RUBY_VERSION
          - language: python
            version: "3.12"
            build-arg: PYTHON_VERSION
          - language: python
            version: "3.13"
            build-arg: PYTHON_VERSION
          - language: python
            version: "3.14"
            build-arg: PYTHON_VERSION
          - language: java
            version: "17"
            build-arg: JDK_VERSION
          - language: java
            version: "21"
            build-arg: JDK_VERSION
          - language: go
            version: "1.25"
            build-arg: GO_VERSION
          - language: go
            version: "1.26"
            build-arg: GO_VERSION
          - language: rust
            version: "1.92"
            build-arg: RUST_VERSION
          - language: rust
            version: "1.93"
            build-arg: RUST_VERSION

    env:
      IMAGE: "ghcr.io/wphillipmoore/${{ inputs.image-prefix }}-${{ matrix.language }}:${{ matrix.version }}"
      CANDIDATE: "ghcr.io/wphillipmoore/${{ inputs.image-prefix }}-${{ matrix.language }}:${{ matrix.version }}-candidate"
      CACHE_TAG: "ghcr.io/wphillipmoore/${{ inputs.image-prefix }}-${{ matrix.language }}:cache-${{ matrix.version }}"
```

The steps within this job are identical to `docker-publish.yml` except the attestation `subject-name`:

```yaml
      - name: Attest build provenance
        uses: actions/attest-build-provenance@v4
        with:
          subject-name: "ghcr.io/wphillipmoore/${{ inputs.image-prefix }}-${{ matrix.language }}"
          subject-digest: ${{ steps.digest.outputs.digest }}
```

All other steps (checkout, generate, QEMU, Buildx, login, build-push-candidate, Trivy amd64, Trivy arm64, SARIF upload, fail-if-vulns, get-digest, promote, verify-digest) are copied verbatim from `docker-publish.yml`.

- [ ] **Step 4: Add the publish-base job with parameterized image names**

Copy the `publish-base` job from `docker-publish.yml`. Parameterize the env vars and attestation:

```yaml
  publish-base:
    name: "publish: ${{ inputs.image-prefix }}-base:latest"
    needs: [hadolint]
    runs-on: ubuntu-latest
    env:
      IMAGE: ghcr.io/wphillipmoore/${{ inputs.image-prefix }}-base:latest
      CANDIDATE: ghcr.io/wphillipmoore/${{ inputs.image-prefix }}-base:latest-candidate
      CACHE_TAG: ghcr.io/wphillipmoore/${{ inputs.image-prefix }}-base:cache-latest
```

And the attestation step:

```yaml
      - name: Attest build provenance
        uses: actions/attest-build-provenance@v4
        with:
          subject-name: ghcr.io/wphillipmoore/${{ inputs.image-prefix }}-base
          subject-digest: ${{ steps.digest.outputs.digest }}
```

All other steps are copied verbatim from the existing `publish-base` job.

- [ ] **Step 5: Validate the workflow syntax**

Run:
```bash
actionlint .github/workflows/cd-docker-publish.yml
yamllint .github/workflows/cd-docker-publish.yml
```

Expected: no errors. If `actionlint` is not installed locally, skip — CI will validate.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/cd-docker-publish.yml
st-commit --type feat --scope ci --message "add reusable cd-docker-publish workflow with image-prefix input" --agent claude
```

---

### Task 2: Extend cd.yml

**Files:**
- Modify: `.github/workflows/cd.yml`

The current `cd.yml` (created by #172) only calls `cd-docs`. Extend it with release and docker-publish jobs.

- [ ] **Step 1: Read the current cd.yml**

Current contents (from #172):

```yaml
# https://github.com/wphillipmoore/standard-actions/blob/develop/.github/workflows/README.md
name: CD

on:
  push:
    branches: [develop, main]
  workflow_dispatch:

permissions:
  contents: write

jobs:
  docs:
    uses: wphillipmoore/standard-actions/.github/workflows/cd-docs.yml@v1.5
    permissions:
      contents: write
```

- [ ] **Step 2: Extend permissions and add release + docker-publish jobs**

Replace the entire file with:

```yaml
# https://github.com/wphillipmoore/standard-actions/blob/develop/.github/workflows/README.md
name: CD

on:
  push:
    branches: [develop, main]
  workflow_dispatch:

permissions:
  contents: write
  packages: write
  security-events: write
  attestations: write
  id-token: write
  pull-requests: write

jobs:
  docs:
    uses: wphillipmoore/standard-actions/.github/workflows/cd-docs.yml@v1.5
    permissions:
      contents: write

  release:
    if: github.ref == 'refs/heads/main'
    uses: wphillipmoore/standard-actions/.github/workflows/cd-release.yml@v1.5
    with:
      language: base
      container-tag: latest
    secrets: inherit
    permissions:
      contents: write
      pull-requests: write
      id-token: write
      attestations: write

  docker-publish:
    needs: [release]
    if: always() && (needs.release.result == 'success' || needs.release.result == 'skipped')
    uses: ./.github/workflows/cd-docker-publish.yml
    with:
      image-prefix: ${{ github.ref == 'refs/heads/main' && 'prod' || 'dev' }}
    permissions:
      packages: write
      contents: read
      security-events: write
      attestations: write
      id-token: write
```

- [ ] **Step 3: Validate**

Run:
```bash
actionlint .github/workflows/cd.yml
yamllint .github/workflows/cd.yml
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/cd.yml
st-commit --type feat --scope ci --message "extend cd.yml with release and docker-publish orchestration" --agent claude
```

---

### Task 3: Create ops.yml

**Files:**
- Create: `.github/workflows/ops.yml`
- Reference: `../standard-tooling/.github/workflows/ops.yml` (pattern to follow)

- [ ] **Step 1: Create ops.yml**

```yaml
name: Ops

on:
  schedule:
    - cron: '15 6 * * *'
  workflow_dispatch:

permissions:
  contents: read
  issues: write
  packages: write
  security-events: write
  attestations: write
  id-token: write

jobs:
  github-config:
    uses: wphillipmoore/standard-actions/.github/workflows/ops-github-config.yml@v1.5
    permissions:
      contents: read
      issues: write

  nightly-rebuild:
    uses: ./.github/workflows/cd-docker-publish.yml
    with:
      image-prefix: dev
    permissions:
      packages: write
      contents: read
      security-events: write
      attestations: write
      id-token: write
```

- [ ] **Step 2: Validate**

Run:
```bash
actionlint .github/workflows/ops.yml
yamllint .github/workflows/ops.yml
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ops.yml
st-commit --type feat --scope ci --message "add ops.yml with github-config audit and nightly dev image rebuild" --agent claude
```

---

### Task 4: Delete docker-publish.yml and update standard-tooling.toml

**Files:**
- Delete: `.github/workflows/docker-publish.yml`
- Modify: `standard-tooling.toml`

- [ ] **Step 1: Delete docker-publish.yml**

```bash
git rm .github/workflows/docker-publish.yml
```

- [ ] **Step 2: Update standard-tooling.toml**

The `[workflows.post-merge]` section currently references the old workflow:

```toml
[workflows.post-merge]
docker-publish = "docker-publish.yml"
```

Update to reference the new orchestrator and add the missing `[ci]` section:

```toml
[ci]
versions = ["latest"]

[workflows.post-merge]
docker-publish = "cd.yml"
```

Also add the `[publish]` release flag since this repo now has a release workflow:

```toml
[publish]
release = true
docs = true
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/docker-publish.yml standard-tooling.toml
st-commit --type feat --scope ci --message "remove docker-publish.yml and update config for new workflow structure" --agent claude
```

---

### Task 5: Update documentation

**Files:**
- Modify: `docs/site/docs/architecture/index.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update architecture docs**

In `docs/site/docs/architecture/index.md`, update the GHCR Publishing section to describe:
- The dev/prod image naming convention
- That `dev-` images are built on develop pushes and nightly via ops.yml
- That `prod-` images are built on main pushes after a release
- That the release workflow generates changelogs and version tags
- Update the "Image naming" line from `dev-{language}:{version}` to describe both prefixes
- Update the "Publishing prerequisites" section to mention both `dev-` and `prod-` packages

Read the current file first, then make targeted edits to the relevant sections.

- [ ] **Step 2: Update CLAUDE.md**

In `CLAUDE.md`, update:
- The "GHCR Publishing" section: mention both `dev-` and `prod-` prefixes
- The "Image naming" line
- The "Publishing prerequisites" section to cover both prefix sets
- Add a note about the release workflow

Read the current file first, then make targeted edits.

- [ ] **Step 3: Run markdownlint**

```bash
markdownlint docs/site/docs/architecture/index.md CLAUDE.md
```

- [ ] **Step 4: Commit**

```bash
git add docs/site/docs/architecture/index.md CLAUDE.md
st-commit --type docs --scope images --message "document dev/prod image naming convention and release workflow" --agent claude
```

---

## Phase 2: standard-tooling consumer-side changes

All files in this phase are in the `standard-tooling` repo. These changes should be developed on a feature branch but **must not merge until after the first release publishes prod images** (Phase 1 step 3 of the migration sequence in the spec).

### Task 6: Add DockerConfig to config.py with tests

**Files:**
- Modify: `src/standard_tooling/lib/config.py`
- Modify: `tests/standard_tooling/test_config.py`

- [ ] **Step 1: Write failing tests for DockerConfig**

Add to `tests/standard_tooling/test_config.py`:

```python
# -- [docker] section ----------------------------------------------------------

_DOCKER_PREFIX_TOML = (
    _VALID_TOML
    + """
[docker]
image-prefix = "dev"
"""
)


def test_read_config_docker_prefix(tmp_path: Path) -> None:
    (tmp_path / "standard-tooling.toml").write_text(_DOCKER_PREFIX_TOML)
    cfg = read_config(tmp_path)
    assert cfg.docker.image_prefix == "dev"


def test_read_config_docker_prefix_defaults_to_prod(tmp_path: Path) -> None:
    (tmp_path / "standard-tooling.toml").write_text(_VALID_TOML)
    cfg = read_config(tmp_path)
    assert cfg.docker.image_prefix == "prod"


def test_read_config_docker_empty_section(tmp_path: Path) -> None:
    toml = _VALID_TOML + "[docker]\n"
    (tmp_path / "standard-tooling.toml").write_text(toml)
    cfg = read_config(tmp_path)
    assert cfg.docker.image_prefix == "prod"


def test_read_config_docker_invalid_prefix(tmp_path: Path) -> None:
    toml = _VALID_TOML + '[docker]\nimage-prefix = "staging"\n'
    (tmp_path / "standard-tooling.toml").write_text(toml)
    with pytest.raises(ConfigError, match="image-prefix.*staging"):
        read_config(tmp_path)
```

Also update the import at the top of the test file to include `DockerConfig`:

```python
from standard_tooling.lib.config import (
    CiConfig,
    ConfigError,
    DockerConfig,
    GithubOverrides,
    MarkdownlintConfig,
    read_config,
    st_install_tag,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /path/to/standard-tooling
uv run pytest tests/standard_tooling/test_config.py -v -k "docker"
```

Expected: ImportError for `DockerConfig` or AttributeError for `cfg.docker`.

- [ ] **Step 3: Implement DockerConfig**

In `src/standard_tooling/lib/config.py`:

Add the dataclass after `PublishConfig`:

```python
@dataclass
class DockerConfig:
    image_prefix: str
```

Add `docker` to `StConfig`:

```python
@dataclass
class StConfig:
    project: ProjectConfig
    dependencies: dict[str, str]
    markdownlint: MarkdownlintConfig
    ci: CiConfig
    github: GithubOverrides
    publish: PublishConfig
    docker: DockerConfig
```

Add validation enum:

```python
_ENUMS: dict[str, set[str]] = {
    ...existing entries...,
    "image-prefix": {"dev", "prod"},
}
```

Add parsing in `_parse_raw_config()`, after the `publish` section:

```python
    docker_raw = raw.get("docker", {})
    docker_prefix = docker_raw.get("image-prefix", "prod")
    if docker_prefix not in _ENUMS["image-prefix"]:
        allowed = ", ".join(sorted(_ENUMS["image-prefix"]))
        msg = f"{CONFIG_FILE}: invalid image-prefix '{docker_prefix}' (allowed: {allowed})"
        raise ConfigError(msg)
    docker = DockerConfig(image_prefix=docker_prefix)
```

Update the `StConfig` constructor call:

```python
    return StConfig(
        project=project,
        dependencies=dict(deps),
        markdownlint=markdownlint,
        ci=ci,
        github=github_overrides,
        publish=publish,
        docker=docker,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
uv run pytest tests/standard_tooling/test_config.py -v
```

Expected: all tests pass, including the new docker tests.

- [ ] **Step 5: Commit**

```bash
git add src/standard_tooling/lib/config.py tests/standard_tooling/test_config.py
st-commit --type feat --scope config --message "add [docker] image-prefix field to standard-tooling.toml schema" --agent claude
```

---

### Task 7: Update docker.py with prefix support and tests

**Files:**
- Modify: `src/standard_tooling/lib/docker.py`
- Modify: `tests/standard_tooling/test_docker.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/standard_tooling/test_docker.py`:

```python
# -- prefix-aware default_image -----------------------------------------------


def test_default_image_prod_prefix() -> None:
    img = default_image("python", prefix="prod")
    assert "prod-python" in img
    assert "dev-python" not in img


def test_default_image_dev_prefix() -> None:
    img = default_image("python", prefix="dev")
    assert "dev-python" in img


def test_default_image_default_prefix_is_prod() -> None:
    img = default_image("python")
    assert "prod-python" in img


def test_default_image_fallback_respects_prefix() -> None:
    img = default_image("unknown", fallback=True, prefix="prod")
    assert "prod-base" in img


def test_default_image_fallback_dev_prefix() -> None:
    img = default_image("unknown", fallback=True, prefix="dev")
    assert "dev-base" in img
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
uv run pytest tests/standard_tooling/test_docker.py -v -k "prefix"
```

Expected: TypeError — `default_image()` does not accept `prefix` parameter.

- [ ] **Step 3: Implement prefix support in docker.py**

Replace the hardcoded image dictionaries and `default_image()` function:

```python
_GHCR = "ghcr.io/wphillipmoore"

_DEFAULT_VERSIONS: dict[str, str] = {
    "ruby": "3.4",
    "python": "3.14",
    "go": "1.26",
    "rust": "1.93",
    "java": "21",
}

_DEFAULT_PREFIX = "prod"
```

Replace `_FALLBACK_IMAGE`:

```python
def _fallback_image(prefix: str) -> str:
    return f"{_GHCR}/{prefix}-base:latest"
```

Replace `default_image()`:

```python
def default_image(lang: str, *, fallback: bool = False, prefix: str = _DEFAULT_PREFIX) -> str:
    """Return the default Docker image for a language.

    When *fallback* is True, return the base image if no language
    matches instead of returning an empty string.
    """
    version = _DEFAULT_VERSIONS.get(lang, "")
    if not version and fallback:
        return _fallback_image(prefix)
    if not version:
        return ""
    return f"{_GHCR}/{prefix}-{lang}:{version}"
```

Remove the old `_DEFAULT_IMAGES` dict and `_FALLBACK_IMAGE` constant.

- [ ] **Step 4: Update existing tests that reference the old constants**

The test file imports `_FALLBACK_IMAGE`. Update:

```python
from standard_tooling.lib.docker import (
    assert_docker_available,
    build_docker_args,
    default_image,
    detect_language,
    docker_platform,
    worktree_parent_gitdir,
)
```

Remove the `_FALLBACK_IMAGE` import. Update `test_default_image_unknown_with_fallback` and `test_default_image_empty_with_fallback`:

```python
def test_default_image_unknown_with_fallback() -> None:
    assert default_image("unknown", fallback=True) == "ghcr.io/wphillipmoore/prod-base:latest"


def test_default_image_empty_with_fallback() -> None:
    assert default_image("", fallback=True) == "ghcr.io/wphillipmoore/prod-base:latest"
```

Update `test_default_image_known_lang`:

```python
def test_default_image_known_lang() -> None:
    assert "prod-python" in default_image("python")
```

- [ ] **Step 5: Run all docker tests**

Run:
```bash
uv run pytest tests/standard_tooling/test_docker.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/standard_tooling/lib/docker.py tests/standard_tooling/test_docker.py
st-commit --type feat --scope docker --message "make image prefix configurable in docker.py, default to prod" --agent claude
```

---

### Task 8: Update st_docker_run.py and st_docker_docs.py with tests

**Files:**
- Modify: `src/standard_tooling/bin/st_docker_run.py`
- Modify: `src/standard_tooling/bin/st_docker_docs.py`
- Modify: `tests/standard_tooling/test_st_docker_run.py`
- Modify: `tests/standard_tooling/test_st_docker_docs.py`

- [ ] **Step 1: Write failing tests for st_docker_run prefix behavior**

Add to `tests/standard_tooling/test_st_docker_run.py`:

```python
def test_uses_prod_prefix_by_default(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    env = {"GH_TOKEN": "tok"}
    with (
        patch("standard_tooling.bin.st_docker_run.git.repo_root", return_value=tmp_path),
        patch("standard_tooling.bin.st_docker_run.assert_docker_available"),
        patch("standard_tooling.bin.st_docker_run.ensure_cached_image") as mock_cache,
        patch("standard_tooling.bin.st_docker_run.os.execvp") as mock_exec,
        patch("standard_tooling.bin.st_docker_run._image_prefix", return_value="prod"),
        patch.dict("os.environ", env, clear=True),
    ):
        mock_cache.return_value = "ghcr.io/wphillipmoore/prod-python:3.14"
        main(["--", "echo", "hi"])
    args = mock_exec.call_args[0][1]
    assert "ghcr.io/wphillipmoore/prod-python:3.14" in args


def test_uses_dev_prefix_from_config(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    env = {"GH_TOKEN": "tok"}
    with (
        patch("standard_tooling.bin.st_docker_run.git.repo_root", return_value=tmp_path),
        patch("standard_tooling.bin.st_docker_run.assert_docker_available"),
        patch("standard_tooling.bin.st_docker_run.ensure_cached_image") as mock_cache,
        patch("standard_tooling.bin.st_docker_run.os.execvp") as mock_exec,
        patch("standard_tooling.bin.st_docker_run._image_prefix", return_value="dev"),
        patch.dict("os.environ", env, clear=True),
    ):
        mock_cache.return_value = "ghcr.io/wphillipmoore/dev-python:3.14"
        main(["--", "echo", "hi"])
    args = mock_exec.call_args[0][1]
    assert "ghcr.io/wphillipmoore/dev-python:3.14" in args
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
uv run pytest tests/standard_tooling/test_st_docker_run.py -v -k "prefix"
```

Expected: AttributeError — `_image_prefix` does not exist.

- [ ] **Step 3: Implement _image_prefix in st_docker_run.py**

Add import:

```python
from standard_tooling.lib.config import ConfigError, read_config
```

Add helper function:

```python
def _image_prefix(repo_root: Path) -> str:
    """Read image prefix from config, defaulting to prod."""
    try:
        cfg = read_config(repo_root)
        return cfg.docker.image_prefix
    except (FileNotFoundError, ConfigError):
        return "prod"
```

Update `main()` to pass prefix to `default_image()`:

```python
    prefix = _image_prefix(repo_root)

    env_image = os.environ.get("DOCKER_DEV_IMAGE")
    if env_image:
        image = env_image
        image_source = "env"
    else:
        base = default_image(lang, fallback=True, prefix=prefix)
        image = ensure_cached_image(repo_root, lang, base)
        image_source = "cached" if image != base else "default"
```

Also add the `Path` import if not already present:

```python
from pathlib import Path
```

- [ ] **Step 4: Run st_docker_run tests**

Run:
```bash
uv run pytest tests/standard_tooling/test_st_docker_run.py -v
```

Expected: all tests pass. Some existing tests may need `prod-` instead of `dev-` in assertions since the default prefix changed. Update these:

- `test_fallback_image_no_language`: change `dev-base` to `prod-base` in the mock return value and assertion
- `test_language_detected_image`: change `dev-python` to `prod-python` in the assertion

Review each existing test and update the expected image names from `dev-` to `prod-` where the test does not explicitly set a prefix.

- [ ] **Step 5: Update st_docker_docs.py**

In `src/standard_tooling/bin/st_docker_docs.py`, change the default image:

```python
from standard_tooling.lib.config import ConfigError, read_config


def _docs_image(repo_root: Path) -> str:
    """Return the docs container image, respecting config prefix."""
    env_image = os.environ.get("DOCKER_DOCS_IMAGE")
    if env_image:
        return env_image
    try:
        cfg = read_config(repo_root)
        prefix = cfg.docker.image_prefix
    except (FileNotFoundError, ConfigError):
        prefix = "prod"
    return f"ghcr.io/wphillipmoore/{prefix}-base:latest"
```

Update `main()` to use this function after `repo_root` is determined:

```python
    repo_root = git.repo_root()
    image = _docs_image(repo_root)
```

Remove the old `image = os.environ.get(...)` line.

Update the help text to show `prod-base:latest` as the default.

- [ ] **Step 6: Update st_docker_docs tests**

Read `tests/standard_tooling/test_st_docker_docs.py` and update any assertions that reference `dev-base:latest` to use `prod-base:latest`.

- [ ] **Step 7: Run all affected tests**

Run:
```bash
uv run pytest tests/standard_tooling/test_st_docker_run.py tests/standard_tooling/test_st_docker_docs.py tests/standard_tooling/test_docker.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/standard_tooling/bin/st_docker_run.py src/standard_tooling/bin/st_docker_docs.py tests/standard_tooling/test_st_docker_run.py tests/standard_tooling/test_st_docker_docs.py
st-commit --type feat --scope docker --message "read image prefix from config in st-docker-run and st-docker-docs" --agent claude
```

---

## Phase 3: standard-actions CI workflow updates

All files in this phase are in the `standard-actions` repo. Like Phase 2, these changes **must not merge until prod images exist**.

### Task 9: Update all CI/CD workflow container image references

**Files (all under `.github/workflows/`):**
- Modify: `ci-quality.yml` (3 locations)
- Modify: `ci-test.yml` (1 location)
- Modify: `ci-audit.yml` (1 location)
- Modify: `ci-security.yml` (2 locations)
- Modify: `ci-version-bump.yml` (1 location)
- Modify: `cd-docs.yml` (1 location)
- Modify: `cd-release.yml` (1 location)
- Modify: `cd.yml` (1 location)

- [ ] **Step 1: Replace all `dev-` prefixes with `prod-`**

This is a mechanical find-and-replace. In every file listed above, replace:

```
ghcr.io/wphillipmoore/dev-
```

with:

```
ghcr.io/wphillipmoore/prod-
```

11 replacements total across 8 files. The specific lines:

| File | Line | Before | After |
|------|------|--------|-------|
| `ci-quality.yml` | 30 | `dev-${{ inputs.container-suffix \|\| 'base' }}` | `prod-${{ inputs.container-suffix \|\| 'base' }}` |
| `ci-quality.yml` | 44 | `dev-${{ inputs.container-suffix \|\| inputs.language }}` | `prod-${{ inputs.container-suffix \|\| inputs.language }}` |
| `ci-quality.yml` | 65 | `dev-${{ inputs.container-suffix \|\| inputs.language }}` | `prod-${{ inputs.container-suffix \|\| inputs.language }}` |
| `ci-test.yml` | 24 | `dev-${{ inputs.container-suffix \|\| inputs.language }}` | `prod-${{ inputs.container-suffix \|\| inputs.language }}` |
| `ci-audit.yml` | 24 | `dev-${{ inputs.container-suffix \|\| inputs.language }}` | `prod-${{ inputs.container-suffix \|\| inputs.language }}` |
| `ci-security.yml` | 46 | `dev-${{ inputs.container-suffix \|\| 'base' }}` | `prod-${{ inputs.container-suffix \|\| 'base' }}` |
| `ci-security.yml` | 91 | `dev-base:latest` | `prod-base:latest` |
| `ci-version-bump.yml` | 30 | `dev-${{ inputs.container-suffix \|\| 'base' }}` | `prod-${{ inputs.container-suffix \|\| 'base' }}` |
| `cd-docs.yml` | 26 | `dev-base:latest` | `prod-base:latest` |
| `cd-release.yml` | 72 | `dev-${{ inputs.language }}` | `prod-${{ inputs.language }}` |
| `cd.yml` | 21 | `dev-base:latest` | `prod-base:latest` |

- [ ] **Step 2: Validate all modified workflows**

Run:
```bash
actionlint .github/workflows/*.yml
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/
st-commit --type feat --scope ci --message "switch all CI/CD container images from dev- to prod- prefix" --agent claude
```

---

## Phase 4: Migration coordination

These are manual/coordination steps, not code tasks. They are documented here for completeness and sequencing.

### Task 10: First release and fleet sweep

- [ ] **Step 1: Merge Phase 1 changes to develop**

Submit PR from the feature branch in standard-tooling-docker. Once merged, the CD workflow will build `dev-` images using the new `cd-docker-publish.yml`. Verify the workflow runs successfully.

- [ ] **Step 2: Merge develop to main — first release**

This triggers:
1. `cd-release.yml` — creates changelog, git tag, GitHub release, version-bump PR
2. `cd-docker-publish.yml` with `prod` prefix — builds and publishes the first set of `prod-` images

Verify both jobs complete successfully.

- [ ] **Step 3: Configure GHCR package permissions**

For each new package (`prod-base`, `prod-python`, `prod-java`, `prod-go`, `prod-ruby`, `prod-rust`):

1. Navigate to `https://github.com/users/wphillipmoore/packages/container/package/<package-name>/settings`
2. Set **Visibility** to Public
3. Under **Manage Actions access**, click **Add Repository**
4. Select `standard-tooling-docker`
5. Set role to **Write**

- [ ] **Step 4: Merge Phase 2 changes (standard-tooling)**

Submit PR and merge. The `st-docker-run` and `st-docker-docs` commands now default to `prod-` images.

- [ ] **Step 5: Merge Phase 3 changes (standard-actions)**

Submit PR and merge. All reusable CI/CD workflows now reference `prod-` images.

- [ ] **Step 6: Fleet sweep — update consuming repos**

For every managed repo, update any hardcoded `dev-` image references to `prod-`. This includes:

- `standard-tooling-docker` itself: `ci.yml` line 27 (`dev-base:latest` → `prod-base:latest`)
- Any other managed repo with hardcoded container image references in their workflows

Use `grep -r "dev-base\|dev-python\|dev-ruby\|dev-java\|dev-go\|dev-rust" .github/workflows/` in each repo to find references.

- [ ] **Step 7: Close issues**

Close #152, #139, #65, and #61 as completed by this work.
