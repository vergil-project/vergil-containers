"""Turn one lifecycle change into the content of an add/drop pull request
(spec §6.2 item 4): the edited manifest, its toolchain pins, and every file
regenerated from them.

Shared code: nothing here knows about any one language (principle 7). What a
change does to the manifest is decided by its kind alone; anything a family
needs beyond the manifest comes from its adapter's `extra_changes`.

A change carries its own toolchain pins (epic vergil-project/.github#1095,
spec §6.1): an add resolves the pin of the series it adds through that
toolchain's resolver, a drop removes the pin the edited manifest no longer
needs, and no other pin is touched. The pins are edited in memory and passed
to the renderers; the checkout is never written.

Fail loud: a change that cannot be applied exactly (an add whose version is
already listed, a drop of a version that is not, an add with no installable
target, an add whose toolchain pin cannot be resolved) raises ApplyError.
Nothing is ever skipped silently.

Only the kinds in `APPLIERS` get a pull request; every other kind is reported
as an issue. A new kind is one more entry in `APPLIERS` and `TITLES`.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path

import generate  # first: it puts docker/pins on the import path
import generate_catalog
import resolve_toolchains as rt
from lifecycle.core import EOL_DATE_UNKNOWN, Change, TargetVersion, has_runtime
from manifest import Family, Manifest, ManifestVersion, dump_manifest, version_sort_key

BRANCH_PREFIX = "lifecycle/"
MANIFEST = generate.MANIFEST  # repo-relative
TOOLCHAINS = generate.TOOLCHAINS  # repo-relative
CATALOG = Path("docker/pins/CATALOG.md")  # repo-relative


class ApplyError(ValueError):
    """A change cannot be applied to the manifest exactly as reported."""


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


def _runtime(family: Family, change: Change, target: TargetVersion | None) -> Family:
    """Record that `change.version`'s runtime package is now published."""
    if target is None or target.version != change.version or target.runtime_published is not True:
        raise ApplyError(
            f"{change.family}: runtime {change.version} needs a target version whose runtime is published, "
            f"got {target!r}"
        )
    if not has_runtime(family):
        raise ApplyError(f"{change.family}: runtime {change.version}: the family records no runtime package")
    versions = []
    for v in family.versions:
        if v.version == change.version:
            if v.runtime_published is not False:
                raise ApplyError(
                    f"{change.family}: runtime {change.version}: the manifest records "
                    f"runtime_published: {v.runtime_published}, not false"
                )
            v = replace(v, runtime_published=True)
        versions.append(v)
    if versions == list(family.versions):
        raise ApplyError(f"{change.family}: runtime {change.version}: the manifest does not list it")
    return replace(family, versions=tuple(versions))


Applier = Callable[[Family, Change, "TargetVersion | None"], Family]

# The change kinds that become a pull request, and what each does to the family.
APPLIERS: dict[str, Applier] = {"add": _add, "drop": _drop, "runtime": _runtime}
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
    # Every other section (core, base's parent, the toolchains) is kept as it is.
    return replace(m, families=tuple(families))


def edit_pins(after: Manifest, base: rt.Toolchains, fetch: rt.Fetch) -> rt.Toolchains:
    """The toolchain pins of `after`, edited from `base`.

    Each series `after` requires (`rt.required_series`) that `base` does not
    pin is resolved through its toolchain's resolver; each series `base` pins
    that `after` no longer requires is removed; each tool `after` requires that
    `base` lacks is resolved. Every other pin is kept exactly as `base` has it:
    an add never re-resolves another series' patch, which is the daily
    refresh's job. A pin that serves a core runtime as well as a family
    (`rt.CORE_PINS`) is still required, so a drop of that family's series
    keeps it.

    `base` is the PR base's pins, which `check_pins.py` holds consistent with
    the base manifest, so the only pins that differ are the change's own.
    A failed lookup, or a result that still does not match `after`, raises
    ApplyError naming the manifest family and series."""
    required = rt.required_series(after)
    series: dict[str, dict[str, rt.Pin]] = {}
    for key in rt.KINDS:
        have = base.series.get(key, {})
        pins: dict[str, rt.Pin] = {}
        for s in required.get(key, ()):
            pins[s] = have[s] if s in have else _resolve_series(key, s, fetch)
        if pins:
            series[key] = pins
    tools = {
        name: base.tools[name] if name in base.tools else _resolve_tool(name, fetch)
        for name in rt.required_tools(after)
    }
    result = rt.Toolchains(series=series, tools=tools)
    errors = rt.consistency_errors(after, result)
    if errors:
        raise ApplyError("the edited toolchain pins do not match the edited manifest:\n  " + "\n  ".join(errors))
    return result


def _resolve_series(key: str, series: str, fetch: rt.Fetch) -> rt.Pin:
    family = rt.KINDS[key].family
    try:
        resolved = rt.RESOLVERS[key]([series], fetch)
    except rt.ResolutionError as exc:
        raise ApplyError(f"{family} {series}: cannot resolve its toolchain pin: {exc}") from exc
    if series not in resolved:
        raise ApplyError(f"{family} {series}: the {key} resolver returned no pin for it")
    return resolved[series]


def _resolve_tool(name: str, fetch: rt.Fetch) -> rt.Pin:
    family = rt.KINDS[rt.TOOLS[name]].family
    try:
        return rt.TOOL_RESOLVERS[name](fetch)
    except rt.ResolutionError as exc:
        raise ApplyError(f"{family}: cannot resolve the {name} pin: {exc}") from exc


def _base_pins(change: Change, root: Path) -> rt.Toolchains:
    try:
        return generate.load_pins(root)
    except generate.GenerateError as exc:
        raise ApplyError(f"{change.family}: {change.kind} {change.version}: {exc}") from exc


def render_change(
    m: Manifest, change: Change, target: TargetVersion | None, root: Path, *, fetch: rt.Fetch
) -> dict[Path, str]:
    """The files a pull request for `change` writes, repo-relative path to full
    content: the manifest, the toolchain pins and the pin catalog, plus every
    generated file whose content changes.

    `root` is a checkout whose files match `m` (the PR's base). Every file is
    compared against it as it is, and nothing is written to it, so a change's
    pin can neither drop out of its own PR nor leak into the next change
    rendered from the same checkout. `fetch` reaches the toolchain upstreams
    for a pin the change adds; it has no default, so no caller reaches the
    network unless it asks to."""
    after = apply_change(m, change, target)
    pins = edit_pins(after, _base_pins(change, root), fetch)
    try:
        rendered = generate.render_all(after, root, pins)
        # The catalog's image-pin table reads the base's Dockerfiles, which a
        # change edits only in a way the extractor ignores (a family version
        # is `x.y` or a major, never `x.y.z`); its toolchain table comes from
        # the edited pins.
        rendered[root / CATALOG] = generate_catalog.render(root / "docker", pins)
    except (generate.GenerateError, OSError) as exc:
        # One change that cannot be rendered must not hold back the others
        # (publish.py).
        raise ApplyError(f"{change.family}: {change.kind} {change.version}: {exc}") from exc
    rendered[root / TOOLCHAINS] = rt.dump_toolchains(pins)
    files: dict[Path, str] = {MANIFEST: dump_manifest(after)}
    for path, content in rendered.items():
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
    "runtime": lambda c, eol: f"feat(versions): record the published {c.family} {c.version} runtime",
}


def pr_title(change: Change, eol: date | None) -> str:
    title = TITLES.get(change.kind)
    if title is None:
        raise ApplyError(f"{change.family}: a {change.kind!r} change has no pull request")
    return title(change, eol)
