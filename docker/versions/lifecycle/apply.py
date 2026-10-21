"""Turn one lifecycle change into the content of an add/drop pull request
(spec §6.2 item 4): the edited manifest and every file regenerated from it.

Shared code: nothing here knows about any one language (principle 7). What a
change does to the manifest is decided by its kind alone; anything a family
needs beyond the manifest comes from its adapter's `extra_changes`.

Fail loud: a change that cannot be applied exactly (an add whose version is
already listed, a drop of a version that is not, an add with no installable
target) raises ApplyError. Nothing is ever skipped silently.

Only the kinds in `APPLIERS` get a pull request; every other kind is reported
as an issue. A new kind (for example a runtime-published flip) is one more
entry in `APPLIERS` and `TITLES`.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path

import generate
from lifecycle.core import EOL_DATE_UNKNOWN, Change, TargetVersion
from manifest import Family, Manifest, ManifestVersion, dump_manifest, version_sort_key

BRANCH_PREFIX = "lifecycle/"
MANIFEST = generate.MANIFEST  # repo-relative


class ApplyError(ValueError):
    """A change cannot be applied to the manifest exactly as reported."""


def has_runtime(family: Family) -> bool:
    """Whether the family's versions track a published runtime package.

    Read from the data: a family whose versions record `runtime_published`
    (true or false, not null) has one."""
    return any(v.runtime_published is not None for v in family.versions)


def _add(family: Family, change: Change, target: TargetVersion | None) -> Family:
    if target is None or target.version != change.version:
        raise ApplyError(f"{change.family}: add {change.version} needs its target version, got {target!r}")
    if not target.installable:
        raise ApplyError(f"{change.family}: add {change.version}: the target is not installable on the base")
    if target.eol == EOL_DATE_UNKNOWN:
        raise ApplyError(f"{change.family}: add {change.version}: upstream says it is EOL")
    if any(v.version == change.version for v in family.versions):
        raise ApplyError(f"{change.family}: add {change.version}: the manifest already lists it")
    added = ManifestVersion(
        version=change.version,
        ga=target.ga,
        eol=target.eol,
        in_policy=True,
        # A new version never has a published runtime yet; the runtime signal
        # flips it once the package exists.
        runtime_published=False if has_runtime(family) else None,
    )
    versions = sorted((*family.versions, added), key=lambda v: version_sort_key(v.version), reverse=True)
    return replace(family, versions=tuple(versions))


def _drop(family: Family, change: Change, target: TargetVersion | None) -> Family:
    versions = tuple(v for v in family.versions if v.version != change.version)
    if len(versions) == len(family.versions):
        raise ApplyError(f"{change.family}: drop {change.version}: the manifest does not list it")
    if not versions:
        raise ApplyError(f"{change.family}: drop {change.version} would leave the family with no versions")
    return replace(family, versions=versions)


Applier = Callable[[Family, Change, "TargetVersion | None"], Family]

# The change kinds that become a pull request, and what each does to the family.
APPLIERS: dict[str, Applier] = {"add": _add, "drop": _drop}
PR_KINDS: tuple[str, ...] = tuple(APPLIERS)


def apply_change(m: Manifest, change: Change, target: TargetVersion | None = None) -> Manifest:
    """The manifest with `change` applied. `target` is the upstream window
    entry for the change's version (required for an add)."""
    applier = APPLIERS.get(change.kind)
    if applier is None:
        raise ApplyError(f"{change.family}: a {change.kind!r} change is reported, not applied")
    families = []
    found = False
    for f in m.families:
        if f.key == change.family:
            f = applier(f, change, target)
            found = True
        families.append(f)
    if not found:
        raise ApplyError(f"{change.family}: no such family in the manifest")
    return Manifest(families=tuple(families))


def render_change(m: Manifest, change: Change, target: TargetVersion | None, root: Path) -> dict[Path, str]:
    """The files a pull request for `change` writes, repo-relative path to full
    content: the manifest, plus every generated file whose content changes.

    `root` is a checkout whose files match `m` (the PR's base)."""
    after = apply_change(m, change, target)
    files: dict[Path, str] = {MANIFEST: dump_manifest(after)}
    for path, content in generate.render_all(after, root).items():
        rel = path.relative_to(root)
        if not path.is_file() or path.read_text() != content:
            files[rel] = content
    return files


# --- Names -------------------------------------------------------------------------


def branch_name(change: Change) -> str:
    return f"{BRANCH_PREFIX}{change.family}-{change.kind}-{change.version}"


_BRANCH_RE = re.compile(
    rf"^{re.escape(BRANCH_PREFIX)}(?P<family>[a-z0-9]+(?:-[a-z0-9]+)*?)-(?P<kind>{'|'.join(PR_KINDS)})-(?P<version>\d+(?:\.\d+)?)$"
)


def parse_branch(branch: str) -> tuple[str, str, str] | None:
    """(family, kind, version) of a managed branch name, or None."""
    m = _BRANCH_RE.match(branch)
    return (m["family"], m["kind"], m["version"]) if m else None


def _eol_text(eol: date | None) -> str:
    if eol is None or eol == EOL_DATE_UNKNOWN:
        return "date unknown"
    return eol.isoformat()


TITLES: dict[str, Callable[[Change, "date | None"], str]] = {
    "add": lambda c, eol: f"feat(versions): add {c.family} {c.version}",
    "drop": lambda c, eol: f"feat(versions): drop {c.family} {c.version} (EOL {_eol_text(eol)})",
}


def pr_title(change: Change, eol: date | None) -> str:
    title = TITLES.get(change.kind)
    if title is None:
        raise ApplyError(f"{change.family}: a {change.kind!r} change has no pull request")
    return title(change, eol)
