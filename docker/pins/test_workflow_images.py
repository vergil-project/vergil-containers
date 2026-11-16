"""The workflows' tool images (workflow_images.py, vergil-containers#855): the
CI and publish Trivy gates run the images' own, auto-managed Trivy, and the
gate fails on any image a workflow pins where no update mechanism moves it."""
from pathlib import Path

import pytest

import workflow_images as wi

DOCKER = Path(__file__).resolve().parent.parent
WORKFLOWS = DOCKER.parent / ".github" / "workflows"


def _workflows(tmp_path: Path, text: str) -> Path:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "w.yml").write_text(text)
    return workflows


def test_trivy_image_is_the_images_auto_managed_trivy():
    fragment = (DOCKER / "common" / "security-tools.dockerfile").read_text()
    version = wi.trivy_version(DOCKER)
    assert f"ARG TRIVY_VERSION={version}\n" in fragment
    assert wi.trivy_image(DOCKER) == f"ghcr.io/aquasecurity/trivy:{version}"


def test_trivy_image_follows_an_upstream_refresh_bump(tmp_path):
    # The refresh rewrites the fragment's ARG; the workflows' image moves with it.
    (tmp_path / "common").mkdir()
    (tmp_path / "common" / "security-tools.dockerfile").write_text("ARG TRIVY_VERSION=0.99.1\n")
    assert wi.trivy_image(tmp_path) == "ghcr.io/aquasecurity/trivy:0.99.1"


def test_trivy_image_fails_loud_without_the_pin(tmp_path):
    (tmp_path / "common").mkdir()
    (tmp_path / "common" / "security-tools.dockerfile").write_text("ARG SCORECARD_VERSION=5.6.0\n")
    with pytest.raises(wi.WorkflowImageError, match="TRIVY_VERSION"):
        wi.trivy_image(tmp_path)


def test_cli_prints_the_trivy_image(capsys):
    assert wi.main(["trivy-image"]) == 0
    assert capsys.readouterr().out == f"{wi.trivy_image(DOCKER)}\n"


def test_registry_image_is_its_managed_pin():
    pins = (DOCKER / "pins" / "workflow-images.txt").read_text()
    image = wi.registry_image(DOCKER)
    assert image.startswith("registry:")
    assert f"\nREGISTRY_VERSION={image.removeprefix('registry:')}\n" in pins


def test_registry_image_follows_an_upstream_refresh_bump(tmp_path):
    (tmp_path / "pins").mkdir()
    (tmp_path / "pins" / "workflow-images.txt").write_text("# c\nREGISTRY_VERSION=3.9.4\n")
    assert wi.registry_image(tmp_path) == "registry:3.9.4"


@pytest.mark.parametrize("text", [
    None, "", "REGISTRY_VERSION=3.1\n", "REGISTRY_VERSION=v3.1.2\n", "# REGISTRY_VERSION=3.1.2\n",
    "REGISTRY_VERSION=3.1.2\nREGISTRY_VERSION=3.1.3\n",
])
def test_registry_image_fails_loud_without_one_pin(tmp_path, text):
    (tmp_path / "pins").mkdir()
    if text is not None:
        (tmp_path / "pins" / "workflow-images.txt").write_text(text)
    with pytest.raises(wi.WorkflowImageError, match="workflow-images.txt"):
        wi.registry_image(tmp_path)


def test_cli_prints_the_registry_image(capsys):
    assert wi.main(["registry-image"]) == 0
    assert capsys.readouterr().out == f"{wi.registry_image(DOCKER)}\n"


def test_cli_refuses_an_unknown_command(capsys):
    assert wi.main(["bogus"]) == 2
    assert "usage" in capsys.readouterr().err


def test_live_workflows_pin_only_the_declared_images():
    assert wi.errors(WORKFLOWS) == []
    assert wi.main(["check"]) == 0
    # No workflow names a Trivy version: every gate derives it.
    assert not [p for p in wi.extract(WORKFLOWS) if "trivy" in p.repo]
    # Nor a registry version: PR CI's service derives it (vergil-containers#914).
    assert not [p for p in wi.extract(WORKFLOWS) if p.repo == "registry"]
    # Every workflow tool image is managed: nothing is declared as a gap.
    assert wi.UNMANAGED == {}


@pytest.mark.parametrize("line", [
    "          TRIVY_IMAGE: aquasec/trivy:0.72.0",
    """          tools: '[{"name": "trivy", "image": "aquasec/trivy:0.72.0"}]'""",
    "      image: aquasec/trivy:0.72.0",
    "        image: 'aquasec/trivy:0.72'",
    "      - uses: docker://aquasec/trivy:0.72.0",
    "          run: docker run --rm aquasec/trivy:0.72.0 image x",
    "          run: docker run ghcr.io/aquasecurity/trivy:v0.72.0",
])
def test_a_pinned_tool_image_fails_the_gate(tmp_path, line):
    found = wi.errors(_workflows(tmp_path, f"jobs:\n  x:\n{line}\n"), unmanaged={})
    assert len(found) == 1
    assert "trivy is pinned at" in found[0]
    assert found[0].startswith("w.yml:3: ")


@pytest.mark.parametrize("line", [
    "      image: postgres:16",
    "      image: postgres@sha256:" + "a" * 64,
    "      - uses: docker://alpine:3",
])
def test_a_structured_image_pinned_by_any_tag_or_digest_fails_the_gate(tmp_path, line):
    assert len(wi.errors(_workflows(tmp_path, f"jobs:\n  x:\n{line}\n"), unmanaged={})) == 1


@pytest.mark.parametrize("line", [
    "      image: ghcr.io/vergil-project/prod-base:latest",
    "      image: ghcr.io/vergil-project/prod-base",
    "      image: ${{ needs.select.outputs.image }}",
    "          TRIVY_IMAGE: ${{ steps.trivy-image.outputs.image }}",
    "      # was aquasec/trivy:0.72.0 (#439)",
    "        uses: actions/checkout@v6",
    "        ports: ['5000:5000']",
    "          REGISTRY: localhost:5000",
    "          run: curl -fsSL https://example.com:443/x",
])
def test_floating_derived_and_non_image_values_pass(tmp_path, line):
    assert wi.errors(_workflows(tmp_path, f"jobs:\n  x:\n{line}\n"), unmanaged={}) == []


def test_a_declared_unmanaged_image_passes_only_at_its_declared_version(tmp_path):
    workflows = _workflows(tmp_path, "      image: registry:2.8.3\n")
    assert wi.errors(workflows, unmanaged={"registry": ("2.8.3", "r")}) == []
    found = wi.errors(workflows, unmanaged={"registry": ("2.8.4", "r")})
    assert len(found) == 1
    assert "declares 2.8.4" in found[0]


def test_a_stale_unmanaged_entry_fails_the_gate(tmp_path):
    found = wi.errors(_workflows(tmp_path, "jobs: {}\n"), unmanaged={"registry": ("2.8.3", "r")})
    assert found == ["UNMANAGED in docker/pins/workflow_images.py declares registry, which no "
                     "workflow pins any more; remove the entry."]
