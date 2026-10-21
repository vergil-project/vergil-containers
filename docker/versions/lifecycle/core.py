"""The shared lifecycle machinery: the adapter contract, the generic window
helpers, and the classification of a target window against the manifest.

Nothing here knows about any one language (spec §6.2, principle 7). A rule
that only one language needs belongs in that language's adapter.

Fail loud (spec §6.2, §8.3): an adapter that cannot fetch or parse upstream
data raises SourceError, and `run` records it as that family's error. An empty
target window is an error too, never "drop everything".
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal, Protocol

from manifest import Family, Manifest, version_sort_key

# An upstream that says a version is EOL without giving a date (endoflife.date
# `"eol": true`). It compares as "EOL long ago", which is what it means.
EOL_DATE_UNKNOWN = date.min


class SourceError(Exception):
    """Upstream data could not be fetched or parsed, or made no sense.

    Never caught to mean "no change": `run` records it as the family's error.
    """


class NotFoundError(SourceError):
    """The upstream answered that the requested resource does not exist (HTTP 404).

    The one fetch failure that is an answer rather than an error, for checks
    such as "does this image tag exist". Callers that do not expect it let it
    propagate as the SourceError it is."""


@dataclass(frozen=True)
class UpstreamRelease:
    version: str  # "x.y", or the major for whole-number languages
    ga: date | None  # None: no release date published (not GA)
    eol: date | None  # None: not EOL and no date announced
    lts: bool  # upstream marks (or will mark) this release LTS
    lts_since: date | None = None  # when LTS starts, if upstream gives a date


@dataclass(frozen=True)
class TargetVersion:
    version: str
    ga: date | None
    eol: date | None
    installable: bool  # the base image or package for it exists
    # Whether the family's runtime package is published for this version: None
    # for a family with no runtime package (spec §6.1, plan Task 13b).
    runtime_published: bool | None = None


class Adapter(Protocol):
    key: str  # manifest family key
    evidence_url: str  # the human-readable upstream page the window is read from

    def fetch(self) -> list[UpstreamRelease]:
        """Read upstream release metadata. Raises SourceError."""
        ...

    def target(self, releases: list[UpstreamRelease], today: date) -> list[TargetVersion]:
        """Apply the family's support rule. Raises SourceError."""
        ...

    def extra_changes(self, change: Change) -> list[str]:
        """Manual follow-ups beyond the manifest for `change` (PR body checklist)."""
        ...


# `runtime`: a version recorded without a published runtime package now has one.
# `runtime_missing`: a version recorded with one no longer has it.
ChangeKind = Literal["add", "drop", "eol_soon", "blocked", "out_of_policy", "runtime", "runtime_missing"]
CHANGE_KINDS: tuple[ChangeKind, ...] = (
    "add", "drop", "eol_soon", "blocked", "out_of_policy", "runtime", "runtime_missing"
)


@dataclass(frozen=True)
class Change:
    family: str
    kind: ChangeKind
    version: str
    detail: str


@dataclass(frozen=True)
class FamilyResult:
    family: str
    changes: tuple[Change, ...]
    error: str | None
    # What upstream said and the adapter's window, so the publishing step can
    # build an add/drop PR (GA and EOL dates) without asking upstream again.
    # Both are empty when `error` is set.
    releases: tuple[UpstreamRelease, ...] = ()
    target: tuple[TargetVersion, ...] = ()


# --- Generic window helpers, composed by adapters ---------------------------


def is_ga(r: UpstreamRelease | TargetVersion, today: date) -> bool:
    """GA means released on or before `today`. A future or absent release date
    is not GA (principle 3: no pre-releases)."""
    return r.ga is not None and r.ga <= today


def is_eol(eol: date | None, today: date) -> bool:
    """EOL is reached on the EOL date itself."""
    return eol is not None and eol <= today


def ga_only(rs: list[UpstreamRelease], today: date) -> list[UpstreamRelease]:
    """The releases that are GA on `today`."""
    return [r for r in rs if is_ga(r, today)]


def ga_not_eol(rs: list[UpstreamRelease], today: date) -> list[UpstreamRelease]:
    """The releases that are GA and not EOL on `today`."""
    return [r for r in ga_only(rs, today) if not is_eol(r.eol, today)]


def newest_n(rs: list[UpstreamRelease], n: int) -> list[UpstreamRelease]:
    """The `n` newest releases by semantic-version order, newest first."""
    if n < 1:
        raise ValueError(f"newest_n: n must be at least 1, got {n}")
    return sorted(rs, key=lambda r: version_sort_key(r.version), reverse=True)[:n]


def lts_only(rs: list[UpstreamRelease], today: date) -> list[UpstreamRelease]:
    """The releases that are LTS on `today` (an LTS start date in the future
    does not count yet)."""
    return [r for r in rs if r.lts and (r.lts_since is None or r.lts_since <= today)]


# --- Classification ----------------------------------------------------------


def has_runtime(family: Family) -> bool:
    """Whether the family's versions track a published runtime package.

    Read from the data: a family whose versions record `runtime_published`
    (true or false, not null) has one."""
    return any(v.runtime_published is not None for v in family.versions)


def _dates(ga: date | None, eol: date | None) -> str:
    def fmt(d: date | None, none: str) -> str:
        if d is None:
            return none
        return "date unknown" if d == EOL_DATE_UNKNOWN else d.isoformat()

    return f"GA {fmt(ga, 'unknown')}, EOL {fmt(eol, 'not announced')}"


def classify(
    family: Family, target: list[TargetVersion], today: date, lookahead_days: int
) -> list[Change]:
    """Diff `target` against `family`'s manifest versions.

    The order is stable: adds and blocked versions newest first, then drops
    (or out-of-policy versions) and EOL warnings, newest first.
    Runtime changes come last: for a family with a runtime package, each kept
    version whose recorded `runtime_published` disagrees with the target's.

    Raises SourceError for an empty or duplicated target, and for a GA target
    whose runtime evidence does not match whether the family has a runtime."""
    if not target:
        raise SourceError(
            f"family {family.key!r}: upstream gave an empty target window; "
            "refusing to read that as 'drop every version'"
        )
    seen: set[str] = set()
    for t in target:
        if t.version in seen:
            raise SourceError(f"family {family.key!r}: target lists {t.version!r} twice")
        seen.add(t.version)

    # No backfill (principle 12): never consider anything older than the
    # family's current oldest version.
    oldest = min(version_sort_key(v.version) for v in family.versions)
    window = [t for t in target if version_sort_key(t.version) >= oldest]
    ga_window = [t for t in window if is_ga(t, today)]
    if not ga_window:
        raise SourceError(
            f"family {family.key!r}: no GA target version at or above the oldest "
            "manifest version; refusing to read that as 'drop every version'"
        )
    runtime = has_runtime(family)
    for t in ga_window:
        if runtime and t.runtime_published is None:
            raise SourceError(
                f"family {family.key!r}: the manifest records a runtime package, but the target "
                f"gives no runtime evidence for {t.version}"
            )
        if not runtime and t.runtime_published is not None:
            raise SourceError(
                f"family {family.key!r}: the target gives runtime evidence for {t.version}, but the "
                "manifest records no runtime package"
            )
    by_version = {t.version: t for t in window}
    in_manifest = {v.version for v in family.versions}

    changes: list[Change] = []
    for t in sorted(ga_window, key=lambda t: version_sort_key(t.version), reverse=True):
        if not t.installable:
            changes.append(
                Change(family.key, "blocked", t.version, f"{_dates(t.ga, t.eol)}; not installable on the base")
            )
        elif t.version not in in_manifest:
            changes.append(Change(family.key, "add", t.version, _dates(t.ga, t.eol)))

    drop_kind: ChangeKind = "out_of_policy" if family.automation == "report" else "drop"
    horizon = today + timedelta(days=lookahead_days)
    kept: list[tuple[str, bool | None, TargetVersion]] = []
    for v in family.versions:  # newest first
        t = by_version.get(v.version)
        eol = t.eol if t is not None and t.eol is not None else v.eol
        if t is None:
            changes.append(Change(family.key, drop_kind, v.version, "not in the upstream support window"))
        elif is_eol(eol, today):
            changes.append(Change(family.key, drop_kind, v.version, f"EOL reached ({_dates(t.ga, eol)})"))
        else:
            kept.append((v.version, v.runtime_published, t))
            if eol is not None and eol <= horizon:
                changes.append(
                    Change(family.key, "eol_soon", v.version, f"EOL {eol.isoformat()}, within {lookahead_days} days")
                )

    # A version being dropped gets no runtime change: the drop removes it. A
    # target that is not GA carries no checked evidence, so it is left alone.
    if runtime:
        for version, recorded, t in kept:
            if not is_ga(t, today) or t.runtime_published is None or t.runtime_published == recorded:
                continue
            if t.runtime_published:
                changes.append(Change(family.key, "runtime", version, "runtime package published"))
            else:
                changes.append(
                    Change(
                        family.key,
                        "runtime_missing",
                        version,
                        "the manifest records a published runtime package, but the package index does not list it",
                    )
                )
    return changes


def run(
    manifest: Manifest,
    adapters: Mapping[str, Adapter],
    today: date,
    lookahead_days: int = 90,
) -> list[FamilyResult]:
    """Check every manifest family. A family whose adapter fails (SourceError or
    ValueError), or that has no adapter, gets its error recorded and the run
    continues with the rest. Nothing is swallowed: every failure is in a result."""
    results: list[FamilyResult] = []
    for family in manifest.families:
        adapter = adapters.get(family.key)
        if adapter is None:
            results.append(
                FamilyResult(family.key, (), f"no lifecycle adapter is registered for family {family.key!r}")
            )
            continue
        try:
            releases = adapter.fetch()
            target = adapter.target(releases, today)
            changes = classify(family, target, today, lookahead_days)
        except (SourceError, ValueError) as exc:
            results.append(FamilyResult(family.key, (), f"{type(exc).__name__}: {exc}"))
            continue
        results.append(FamilyResult(family.key, tuple(changes), None, tuple(releases), tuple(target)))
    return results
