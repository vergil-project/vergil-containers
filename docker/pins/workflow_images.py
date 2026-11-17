"""The tool images this repo's workflows run, and the gate that keeps every one
of them on an update mechanism (vergil-containers#855).

A tool image pinned in a workflow is invisible to the daily upstream refresh,
which rewrites only the `ARG <TOOL>_VERSION=` pins in docker/common/*
(resolve_latest.py), and to Dependabot, which here watches only `uses:`
references. The CI and publish Trivy gates once ran `aquasec/trivy:0.72.0` that
way, months behind the Trivy the images ship, and nothing noticed.

So a workflow never names a tool image's version itself. It derives the image
from the auto-managed pin the images are built with, through this script:

    python3 docker/pins/workflow_images.py trivy-image

prints the Trivy image for the `ARG TRIVY_VERSION=` in
docker/common/security-tools.dockerfile, so the CI gate scans with exactly the
Trivy the images ship, and moves with it on every upstream-refresh bump. The
refresh cannot rewrite workflow files instead: its path fence (the
[upstream-refresh].paths allowlist in vergil.toml) always refuses a change
under .github/, so such a bump would fail the refresh.

A tool image no image ships has no fragment ARG to derive from, so its pin is
a line in docker/pins/workflow-images.txt, which the refresh moves within its
major version only (resolve_latest.WORKFLOW_PIN_REPOS, vergil-containers#914):

    python3 docker/pins/workflow_images.py registry-image

prints the image of PR CI's job-local registry service (ci-images.yml).

    uv run docker/pins/workflow_images.py check

is the gate (scripts/bin/validate-custom): it fails on any image a workflow
pins by a literal version or digest that is not declared in UNMANAGED below,
and on any UNMANAGED entry that no workflow pins any more. An image built from
an expression (`${{ ... }}`), or a floating one (no tag, or `:latest`), is not
a pin.

`trivy-image` and `registry-image` use only the standard library, so a
workflow step can run them with the runner's python3.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import resolve_latest

# The Trivy image every Trivy gate runs. The GitHub Container Registry mirror,
# as the shared vergil-actions trivy action defaults to, avoids Docker Hub's
# anonymous pull rate limits.
TRIVY_REPOSITORY = "ghcr.io/aquasecurity/trivy"

# The fragment that installs the images' Trivy; its ARG is the auto-managed pin.
TRIVY_FRAGMENT = Path("common") / "security-tools.dockerfile"

# The official Docker image of the distribution/distribution registry, which
# PR CI's image build runs as its job-local registry service.
REGISTRY_REPOSITORY = "registry"

# Images a workflow may pin by a literal version although no update mechanism
# moves them: repository → (the pinned version, why it is accepted). Each entry
# is a known gap, declared so it is reviewed rather than found by accident; a
# new literal pin fails the gate until it is derived from a managed pin or
# declared here. Today there is none.
UNMANAGED: dict[str, tuple[str, str]] = {}

# An image repository, lower case as every image reference is. A registry host
# may carry a port (`localhost:5000/x`), which only a `/` follows.
_NAME = (r"(?:[a-z0-9][a-z0-9.-]*(?::\d+)?/)?"
         r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?(?:/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)*")
# A version or digest pin inside free text (an env value, a JSON string, a
# script): `<repository>:<x.y…>` or `<repository>@sha256:<hex>`.
_TEXT_PIN = re.compile(
    rf"(?<![\w./@:-])(?P<repo>{_NAME})"
    rf"(?::(?P<tag>v?\d+\.\d+[\w.+-]*)|@(?P<digest>sha256:[0-9a-f]{{64}}))"
)
# The reference an `image:` (job container, service) or `docker://` names.
_REF = re.compile(rf"^(?P<repo>{_NAME})(?::(?P<tag>[\w][\w.+-]*))?(?:@(?P<digest>sha256:[0-9a-f]{{64}}))?$")
_IMAGE_KEY = re.compile(r"^\s*(?:-\s+)?image:\s*['\"]?(?P<ref>[^'\"\s#]+)")
_DOCKER_USES = re.compile(r"^\s*(?:-\s+)?uses:\s*['\"]?docker://(?P<ref>[^'\"\s#]+)")


class WorkflowImageError(RuntimeError):
    """A managed image's version could not be read. Raised loudly: a workflow
    must never run a gate with a guessed or empty image."""


@dataclass(frozen=True)
class Pin:
    repo: str
    version: str
    source: str  # <file>:<line>


def trivy_version(docker_root: Path) -> str:
    """The `ARG TRIVY_VERSION=` the images are built with."""
    arg = resolve_latest.TOOL_ARGS["trivy"]
    fragment = docker_root / TRIVY_FRAGMENT
    match = re.search(rf"^ARG\s+{re.escape(arg)}=(\d+\.\d+\.\d+)\s*$",
                      fragment.read_text(), re.MULTILINE)
    if not match:
        raise WorkflowImageError(f"no 'ARG {arg}=x.y.z' in {fragment}")
    return match.group(1)


def trivy_image(docker_root: Path) -> str:
    """The Trivy image the CI and publish gates run: the images' own Trivy."""
    return f"{TRIVY_REPOSITORY}:{trivy_version(docker_root)}"


def registry_image(docker_root: Path) -> str:
    """The image of PR CI's job-local registry service: its pin in
    docker/pins/workflow-images.txt."""
    try:
        version = resolve_latest.read_workflow_pin(docker_root, "registry")
    except resolve_latest.ResolutionError as exc:
        raise WorkflowImageError(str(exc)) from exc
    return f"{REGISTRY_REPOSITORY}:{version}"


def _ref_pin(ref: str) -> tuple[str, str] | None:
    """(repository, version) when `ref`, a whole image reference, is pinned."""
    if "${{" in ref:
        return None
    match = _REF.match(ref)
    if not match:
        raise WorkflowImageError(f"cannot parse the image reference {ref!r}")
    version = match.group("digest") or match.group("tag")
    if version is None or version == "latest":
        return None
    return match.group("repo"), version


def extract(workflows: Path) -> list[Pin]:
    """Every image the workflows in `workflows` pin by a literal version or
    digest: a job container or service `image:`, a `docker://` step, or a
    reference in any other value. Comment lines are skipped."""
    pins: set[Pin] = set()
    for path in sorted(workflows.glob("*.y*ml")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            source = f"{path.name}:{number}"
            for key in (_IMAGE_KEY, _DOCKER_USES):
                match = key.match(line)
                if match:
                    pinned = _ref_pin(match.group("ref"))
                    if pinned:
                        pins.add(Pin(*pinned, source))
            for match in _TEXT_PIN.finditer(line):
                pins.add(Pin(match.group("repo"), match.group("tag") or match.group("digest"), source))
    return sorted(pins, key=lambda p: (p.repo, p.source))


def errors(workflows: Path, unmanaged: dict[str, tuple[str, str]] = UNMANAGED) -> list[str]:
    """Why the workflows' image pins are not all accounted for; empty when they
    are."""
    out: list[str] = []
    pins = extract(workflows)
    for pin in pins:
        declared = unmanaged.get(pin.repo)
        if declared is None:
            out.append(
                f"{pin.source}: {pin.repo} is pinned at {pin.version} in a workflow, "
                "where no update mechanism moves it. Derive it from a managed pin "
                "(docker/pins/workflow_images.py), or declare it in UNMANAGED there "
                "with why it is accepted."
            )
        elif pin.version != declared[0]:
            out.append(
                f"{pin.source}: {pin.repo} is pinned at {pin.version}, but UNMANAGED in "
                f"docker/pins/workflow_images.py declares {declared[0]}; make them agree."
            )
    for repo in sorted(set(unmanaged) - {p.repo for p in pins}):
        out.append(
            f"UNMANAGED in docker/pins/workflow_images.py declares {repo}, which no "
            "workflow pins any more; remove the entry."
        )
    return out


def main(argv: list[str]) -> int:
    pins_dir = Path(__file__).resolve().parent
    docker_root = pins_dir.parent
    if argv == ["trivy-image"]:
        print(trivy_image(docker_root))
        return 0
    if argv == ["registry-image"]:
        print(registry_image(docker_root))
        return 0
    if argv == ["check"]:
        found = errors(docker_root.parent / ".github" / "workflows")
        for error in found:
            print(f"::error::{error}", file=sys.stderr)
        return 1 if found else 0
    print("usage: workflow_images.py trivy-image | registry-image | check", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
