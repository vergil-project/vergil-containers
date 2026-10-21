"""Whether a runtime package is published in the vergil apt repository
(plan Task 13b; spec §6.1, §7).

A family whose manifest versions record `runtime_published` ships a deployed
runtime package per version. Its adapter names that package; this module reads
the signed vergil apt index (https://vergil-project.github.io/packages) and says
whether the package is listed. Shared code: nothing here knows any language.

A package is published when it is listed in every suite this repository serves,
for every architecture each suite's `Release` file declares: a runtime that some
supported hosts cannot install is not usable. Listed nowhere is "not published".

Fail loud: a `Release` or `Packages` file that cannot be fetched or parsed, that
declares no architecture or lists no package, and a package listed for only some
suites or architectures all raise SourceError. None of them is ever read as "not
published", which would tell packaged consumers a runtime they use is gone.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from lifecycle.core import SourceError
from lifecycle.sources import Fetch

APT_URL = "https://vergil-project.github.io/packages/deb"
# The suites the vergil apt repository serves (its install instructions name
# them). GitHub Pages lists no directories, so they cannot be discovered.
SUITES: tuple[str, ...] = ("noble", "resolute")
COMPONENT = "main"

Slot = tuple[str, str]  # (suite, architecture)


def _fields(url: str, text: str) -> list[dict[str, str]]:
    """The deb822 stanzas of `text`, each as field -> value (continuation lines
    are dropped: no field read here spans lines)."""
    stanzas: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            if current:
                stanzas.append(current)
                current = {}
            continue
        if line[0] in " \t":
            continue
        name, sep, value = line.partition(":")
        if not sep or not name:
            raise SourceError(f"{url}: malformed line {line!r}")
        current[name] = value.strip()
    if current:
        stanzas.append(current)
    return stanzas


def _text(url: str, fetch: Fetch) -> str:
    body = fetch(url)
    try:
        return body.decode()
    except UnicodeDecodeError as exc:
        raise SourceError(f"{url}: not UTF-8: {exc}") from exc


def _architectures(suite: str, fetch: Fetch) -> list[str]:
    url = f"{APT_URL}/dists/{suite}/Release"
    stanzas = _fields(url, _text(url, fetch))
    if not stanzas:
        raise SourceError(f"{url}: empty Release file")
    release = stanzas[0]
    if release.get("Codename") != suite:
        raise SourceError(f"{url}: Codename is {release.get('Codename')!r}, expected {suite!r}")
    archs = [a for a in release.get("Architectures", "").split() if a != "all"]
    if not archs:
        raise SourceError(f"{url}: declares no architecture")
    return archs


def _packages(suite: str, arch: str, fetch: Fetch) -> set[str]:
    url = f"{APT_URL}/dists/{suite}/{COMPONENT}/binary-{arch}/Packages"
    names: set[str] = set()
    for stanza in _fields(url, _text(url, fetch)):
        name = stanza.get("Package")
        if not name:
            raise SourceError(f"{url}: a stanza has no Package field")
        names.add(name)
    if not names:
        raise SourceError(f"{url}: lists no package")
    return names


@dataclass(frozen=True)
class AptIndex:
    """Which packages each (suite, architecture) of the vergil repo lists."""

    listings: Mapping[Slot, frozenset[str]]

    def published(self, package: str) -> bool:
        """True if every slot lists `package`, False if none does. A package
        listed in only some slots raises SourceError naming the missing ones."""
        missing = sorted(slot for slot, names in self.listings.items() if package not in names)
        if not missing:
            return True
        if len(missing) == len(self.listings):
            return False
        where = ", ".join(f"{suite}/{arch}" for suite, arch in missing)
        raise SourceError(f"{APT_URL}: {package} is published, but not for {where}")


def read_index(fetch: Fetch) -> AptIndex:
    """Read every suite's `Release` and per-architecture `Packages` file."""
    listings: dict[Slot, frozenset[str]] = {}
    for suite in SUITES:
        for arch in _architectures(suite, fetch):
            listings[(suite, arch)] = frozenset(_packages(suite, arch, fetch))
    return AptIndex(listings)


def runtime_published(package: str, fetch: Fetch) -> bool:
    """Whether runtime package `package` is published (see the module docstring)."""
    return read_index(fetch).published(package)
