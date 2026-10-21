"""Render lifecycle results: a Markdown matrix report for humans and a JSON
document for the publishing step (Task 5 reads it back with `results_from_json`).

The report covers every family on every run. A family with an error is shown
as failing, never as "in sync".
"""
from __future__ import annotations

import json
from datetime import date

from lifecycle.core import CHANGE_KINDS, Change, FamilyResult

JSON_SCHEMA = 1


def family_status(result: FamilyResult) -> str:
    if result.error is not None:
        return "check failed"
    if not result.changes:
        return "in sync"
    return "changes"


def render_markdown(results: list[FamilyResult], today: date) -> str:
    lines = [
        f"# Language lifecycle report ({today.isoformat()})",
        "",
        "| Family | Status | Changes |",
        "|---|---|---|",
    ]
    for r in results:
        summary = ", ".join(f"{c.kind} {c.version}" for c in r.changes) or "-"
        lines.append(f"| {r.family} | {family_status(r)} | {summary} |")
    for r in results:
        if r.error is None and not r.changes:
            continue
        lines += ["", f"## {r.family}", ""]
        if r.error is not None:
            lines.append(f"Check failed: {r.error}")
        for c in r.changes:
            lines.append(f"- `{c.kind}` {c.version}: {c.detail}")
    return "\n".join(lines) + "\n"


def results_to_json(results: list[FamilyResult], today: date) -> str:
    doc = {
        "schema": JSON_SCHEMA,
        "today": today.isoformat(),
        "results": [
            {
                "family": r.family,
                "error": r.error,
                "changes": [
                    {"family": c.family, "kind": c.kind, "version": c.version, "detail": c.detail}
                    for c in r.changes
                ],
            }
            for r in results
        ],
    }
    return json.dumps(doc, indent=2) + "\n"


def results_from_json(text: str) -> list[FamilyResult]:
    """Inverse of `results_to_json`. Raises ValueError on any shape violation."""
    doc = json.loads(text)
    if not isinstance(doc, dict) or doc.get("schema") != JSON_SCHEMA:
        raise ValueError(f"lifecycle results: unsupported or missing schema (want {JSON_SCHEMA})")
    raw_results = doc.get("results")
    if not isinstance(raw_results, list):
        raise ValueError("lifecycle results: `results` must be a list")
    results: list[FamilyResult] = []
    try:
        for raw in raw_results:
            changes = []
            for c in raw["changes"]:
                if c["kind"] not in CHANGE_KINDS:
                    raise ValueError(f"lifecycle results: unknown change kind {c['kind']!r}")
                changes.append(Change(c["family"], c["kind"], c["version"], c["detail"]))
            results.append(FamilyResult(raw["family"], tuple(changes), raw["error"]))
    except (KeyError, TypeError) as exc:
        raise ValueError(f"lifecycle results: malformed entry: {exc!r}") from exc
    return results
