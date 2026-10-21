"""The language lifecycle check (epic vergil-project/.github#407, spec §6.2).

Each family's adapter reads upstream release metadata and computes a target
window; the shared core (`core.py`) diffs that window against the manifest and
classifies the changes; `report.py` renders them; `check.py` is the CLI.

Language specifics live only in `adapters/<language>.py`. The shared modules
(`core.py`, `sources.py`, `report.py`) contain no language names.
"""
