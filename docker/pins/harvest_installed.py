"""Harvest resolved tool versions actually installed in each image.

The probe is INJECTED so unit tests never run Docker; the CLI default shells out
to `docker run --rm <image> <tool> --version` and extracts the first x.y.z.
A tool that is absent from an image (probe yields no x.y.z) is simply omitted
from that image's map — that is the expected "not installed here" signal, not an
error."""
from __future__ import annotations

import re
import subprocess
import sys

_VER = re.compile(r"(\d+\.\d+\.\d+)")


def _docker_probe(image: str, tool: str) -> str:
    """Default probe: run `<tool> --version` inside the image and return its
    combined output. A genuine infrastructure failure (no runtime, image
    unpullable) is warned about — never swallowed silently — and yields empty
    output so the harvest continues over the rest of the matrix."""
    try:
        out = subprocess.run(
            ["docker", "run", "--rm", f"ghcr.io/vergil-project/{image}", tool, "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"::warning::probe failed for {tool} in {image}: {exc}", file=sys.stderr)
        return ""
    return out.stdout + out.stderr


def harvest(images, tools, probe=_docker_probe) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for image in images:
        found: dict[str, str] = {}
        for tool in tools:
            match = _VER.search(probe(image, tool))
            if match:
                found[tool] = match.group(1)
        result[image] = found
    return result
