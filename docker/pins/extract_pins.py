"""Scan Dockerfile templates + fragments for EXACT (x.y.z) version pins.
Major-only pins (NODE_MAJOR, language matrix ARGs) are intentional matrix and
are deliberately NOT reported."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Pin:
    tool: str
    version: str
    source: str


# (regex, tool-name-group, version-group). Each targets one install idiom.
_PATTERNS = [
    # ARG SHELLCHECK_VERSION=0.11.0  (only x.y.z — three numeric components)
    (re.compile(r"ARG\s+([A-Z0-9_]+)_VERSION=(\d+\.\d+\.\d+)\b"), 1, 2),
    # pip/uv:  yamllint==1.38.0 ,  uv tool install ansible-lint==26.4.0
    (re.compile(r"([a-z0-9][a-z0-9._-]+)==(\d+\.\d+\.\d+)\b"), 1, 2),
    # go install <module-path>[/vN]@vX.Y.Z — the tool is the last path segment
    # before the (optional) /vN major-version suffix, not "cmd" or "vN".
    (re.compile(r"go install\s+\S*?/([a-zA-Z0-9._-]+)(?:/v\d+)?@v(\d+\.\d+\.\d+)\b"), 1, 2),
    # cargo install cargo-deny@0.19.6
    (re.compile(r"cargo install\s+([a-z0-9-]+)@(\d+\.\d+\.\d+)\b"), 1, 2),
    # npm install -g markdownlint-cli@0.48.0
    (re.compile(r"npm install -g\s+([a-z0-9@/-]+)@(\d+\.\d+\.\d+)\b"), 1, 2),
    # shell var assignment: GTC_VERSION="v2.18.8" (conditional/looped installs)
    (re.compile(r'([A-Z0-9_]+)_VERSION="?v?(\d+\.\d+\.\d+)"?'), 1, 2),
]

# Some tools carry their version in an abbreviated shell var; map it to the tool.
_ALIASES = {"gtc": "go-test-coverage"}


def _normalize(tool: str) -> str:
    slug = tool.lower().replace("_", "-").removesuffix("-version")
    return _ALIASES.get(slug, slug)


def extract(root: Path) -> list[Pin]:
    files = list((root / "common").glob("*.dockerfile"))
    files += [p / "Dockerfile.template" for p in root.iterdir()
              if (p / "Dockerfile.template").exists()]
    seen: dict[tuple[str, str], Pin] = {}
    for f in files:
        text = f.read_text()
        for rx, tg, vg in _PATTERNS:
            for m in rx.finditer(text):
                tool = _normalize(m.group(tg))
                ver = m.group(vg)
                seen.setdefault((tool, ver), Pin(tool, ver, str(f.relative_to(root))))
    return sorted(seen.values(), key=lambda p: p.tool)
