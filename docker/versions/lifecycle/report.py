"""Render lifecycle results: a Markdown matrix report for humans and a JSON
document for the publishing step (Task 5 reads it back with `results_from_json`).

The report covers every family on every run. A family with an error is shown
as failing, never as "in sync".
"""
from __future__ import annotations

import json
from datetime import date

from lifecycle.core import CHANGE_KINDS, Change, FamilyResult, TargetVersion, UpstreamRelease

# Schema 2 adds each family's upstream `releases` and `target` window, which the
# add/drop PRs need for their GA and EOL dates.
JSON_SCHEMA = 2


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


def _date_out(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def _date_in(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"lifecycle results: date {value!r} must be an ISO string or null")
    return date.fromisoformat(value)


def _bool_in(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"lifecycle results: {value!r} must be true or false")
    return value


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
                "releases": [
                    {
                        "version": u.version,
                        "ga": _date_out(u.ga),
                        "eol": _date_out(u.eol),
                        "lts": u.lts,
                        "lts_since": _date_out(u.lts_since),
                    }
                    for u in r.releases
                ],
                "target": [
                    {"version": t.version, "ga": _date_out(t.ga), "eol": _date_out(t.eol), "installable": t.installable}
                    for t in r.target
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
            releases = tuple(
                UpstreamRelease(
                    u["version"], _date_in(u["ga"]), _date_in(u["eol"]), _bool_in(u["lts"]), _date_in(u["lts_since"])
                )
                for u in raw["releases"]
            )
            target = tuple(
                TargetVersion(t["version"], _date_in(t["ga"]), _date_in(t["eol"]), _bool_in(t["installable"]))
                for t in raw["target"]
            )
            results.append(FamilyResult(raw["family"], tuple(changes), raw["error"], releases, target))
    except (KeyError, TypeError) as exc:
        raise ValueError(f"lifecycle results: malformed entry: {exc!r}") from exc
    return results

