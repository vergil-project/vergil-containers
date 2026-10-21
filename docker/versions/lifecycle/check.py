#!/usr/bin/env python3
"""Run the language lifecycle check against upstream (spec §6.2).

    python3 docker/versions/lifecycle/check.py [--report PATH] [--json PATH]

Checks every manifest family with its adapter, prints the Markdown matrix
report, and writes it to --report and the results to --json when given.
Exits 1 when any family's check failed (after writing both outputs), so a
broken check is never indistinguishable from "in sync".
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path

if __package__ in (None, ""):  # run as a script: make `docker/versions` importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lifecycle.core import Adapter, run  # noqa: E402
from lifecycle.report import render_markdown, results_to_json  # noqa: E402
from manifest import ManifestError, load_manifest  # noqa: E402

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.yml"
DEFAULT_LOOKAHEAD_DAYS = 90


def main(argv: list[str] | None = None, *, adapters: Mapping[str, Adapter] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, help="write the Markdown report here")
    parser.add_argument("--json", type=Path, help="write the results JSON here")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--today", type=date.fromisoformat, default=None, help="ISO date (default: today)")
    parser.add_argument("--lookahead-days", type=int, default=DEFAULT_LOOKAHEAD_DAYS)
    args = parser.parse_args(argv)

    if adapters is None:
        from lifecycle.adapters import ADAPTERS

        adapters = ADAPTERS
    today = args.today or date.today()

    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"lifecycle check: {exc}", file=sys.stderr)
        return 1

    results = run(manifest, adapters, today, args.lookahead_days)
    report = render_markdown(results, today)
    if args.report:
        args.report.write_text(report)
    if args.json:
        args.json.write_text(results_to_json(results, today))
    sys.stdout.write(report)

    failed = [r for r in results if r.error is not None]
    for r in failed:
        print(f"lifecycle check failed for {r.family}: {r.error}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
