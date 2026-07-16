"""CI gate: every EXACT image pin has a pins.yml justification, and every
pins.yml entry still corresponds to a real pin. Exit 1 (loud) on drift."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

import extract_pins


def load_pins(root: Path) -> dict:
    # `root` is the repo `docker/` dir (same root extract_pins scans); the
    # justification catalog lives in the `pins/` subdir alongside these scripts.
    data = yaml.safe_load((root / "pins" / "pins.yml").read_text()) or {}
    return data.get("pins", {})


def main(root: Path) -> int:
    pinned = {p.tool for p in extract_pins.extract(root)}
    documented = set(load_pins(root))
    undocumented = sorted(pinned - documented)
    stale = sorted(documented - pinned)
    for t in undocumented:
        print(f"::error::pin '{t}' has no justification in pins.yml", file=sys.stderr)
    for t in stale:
        print(f"::error::pins.yml entry '{t}' no longer pins anything; remove it", file=sys.stderr)
    return 1 if (undocumented or stale) else 0


if __name__ == "__main__":
    # This script lives in docker/pins/; the scan root is the parent docker/ dir.
    sys.exit(main(Path(__file__).resolve().parent.parent))
