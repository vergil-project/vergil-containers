# /// script
# dependencies = ["pyyaml"]
# ///
"""The language toolchain pins: `docker/pins/toolchains.yml`, its schema, its
checks against the version manifest, and one resolver per upstream (epic
vergil-project/.github#649, Task 6; spec §5.3).

Each language image installs a toolchain it downloads (python-build-standalone,
Go, the nodejs.org tarballs) or that rustup installs (Rust, with a pinned
`rustup-init`). `toolchains.yml` pins each series to an exact release and, for
every verified download, the SHA-256 of each architecture's file. The image
build verifies the download against that hash and resolves nothing over the
network itself; `generate.py` carries the pins into each matrix entry's
`build-args` map (`build_args`).

The daily upstream refresh (`upstream-refresh.sh`) runs this script with
`--write`, which rewrites `toolchains.yml` to the newest patch of every series
the manifest lists (each family series of a pinned family, plus the core Node
major). Without `--write` it prints what would change and writes nothing.

**One fetcher per upstream.** `pbs_releases`, `go_releases`, `node_releases`,
`rust_release` and `rustup_init_release` each fetch and parse one upstream,
taking an injectable `fetch(url) -> bytes`. The lifecycle adapters import them
rather than fetching the same upstream themselves (spec §5.4), and the tests
inject canned bodies, so no test touches the network.

**Fail loud.** A schema violation raises ToolchainsError, a failed lookup
ResolutionError, each naming the toolchain and series. A partial result is
never written: any failure exits non-zero, so the refresh pushes nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE.parent / "versions"))

import manifest as mf  # noqa: E402

TOOLCHAINS_YML = HERE / "toolchains.yml"
MANIFEST_YML = HERE.parent / "versions" / "manifest.yml"

SCHEMA = 1
ARCHES = ("amd64", "arm64")

Fetch = Callable[[str], bytes]


class ToolchainsError(ValueError):
    """toolchains.yml violates its schema, or does not match the manifest."""


class ResolutionError(RuntimeError):
    """An upstream lookup failed or returned something unusable."""


# --- The schema ---------------------------------------------------------------


@dataclass(frozen=True)
class Kind:
    """What one `toolchains:` key pins, and the manifest family it serves."""

    family: str  # the manifest family key whose series it pins
    series_re: re.Pattern[str]
    hashed: bool  # each architecture's download is verified against a SHA-256
    release: bool = False  # the pin also names an upstream release tag


_MINOR = re.compile(r"^\d+\.\d+$")
_MAJOR = re.compile(r"^\d+$")

# Toolchain key -> what it pins. `node` serves the ts-node family and the core
# Node (the manifest's `core.node`). The core Python needs no pin: it is the
# vergil-python package from the vergil apt repository (spec §5.2.1).
KINDS: dict[str, Kind] = {
    "python": Kind(family="python", series_re=_MINOR, hashed=True, release=True),
    "go": Kind(family="go", series_re=_MINOR, hashed=True),
    "node": Kind(family="ts-node", series_re=_MAJOR, hashed=True),
    "rust": Kind(family="rust", series_re=_MINOR, hashed=False),
}
# Tools pinned beside the toolchains, keyed by name, and the toolchain each
# serves: rustup-init installs the pinned Rust release.
TOOLS: dict[str, str] = {"rustup-init": "rust"}
# The manifest's core runtimes that have a pin, and the toolchain holding it.
CORE_PINS: dict[str, str] = {"node": "node"}

_PATCH_RE = re.compile(r"^\d+\.\d+\.\d+$")
_RELEASE_RE = re.compile(r"^\d{8}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Pin:
    version: str  # the exact release: "3.15.2", "1.27.3", "24.11.1"
    sha256: dict[str, str] | None = None  # architecture -> hex digest
    release: str | None = None  # python-build-standalone's release tag


@dataclass(frozen=True)
class Toolchains:
    series: dict[str, dict[str, Pin]]  # toolchain -> series -> pin
    tools: dict[str, Pin]  # tool -> pin


def _keys(where: str, data: object, required: set[str]) -> dict:
    if not isinstance(data, dict):
        raise ToolchainsError(f"{where}: must be a mapping")
    unknown = sorted(set(data) - required)
    if unknown:
        raise ToolchainsError(f"{where}: unknown key(s) {', '.join(map(repr, unknown))}")
    missing = sorted(required - set(data))
    if missing:
        raise ToolchainsError(f"{where}: missing key(s) {', '.join(map(repr, missing))}")
    return data


def _string(where: str, field: str, value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise ToolchainsError(f"{where}: {field} {value!r} must be a string matching {pattern.pattern}")
    return value


def _parse_hashes(where: str, data: object) -> dict[str, str]:
    data = _keys(f"{where}: sha256", data, set(ARCHES))
    return {arch: _string(f"{where}: sha256", arch, data[arch], _SHA256_RE) for arch in ARCHES}


def _parse_pin(where: str, data: object, *, hashed: bool, release: bool) -> Pin:
    fields = {"version"} | ({"sha256"} if hashed else set()) | ({"release"} if release else set())
    data = _keys(where, data, fields)
    return Pin(
        version=_string(where, "version", data["version"], _PATCH_RE),
        sha256=_parse_hashes(where, data["sha256"]) if hashed else None,
        release=_string(where, "release", data["release"], _RELEASE_RE) if release else None,
    )


def _check_series_version(where: str, key: str, series: str, version: str) -> None:
    if not version.startswith(f"{series}."):
        raise ToolchainsError(f"{where}: version {version!r} is not a release of {key} {series}")


def parse_toolchains(data: object) -> Toolchains:
    """Validate already-parsed YAML data and build a Toolchains."""
    data = _keys("toolchains.yml", data, {"schema", "toolchains", "tools"})
    if data["schema"] != SCHEMA:
        raise ToolchainsError(f"toolchains.yml: schema {data['schema']!r} is not supported (want {SCHEMA})")
    raw = data["toolchains"]
    if not isinstance(raw, dict):
        raise ToolchainsError("toolchains.yml: toolchains must be a mapping")
    unknown = sorted(set(raw) - set(KINDS))
    if unknown:
        raise ToolchainsError(f"toolchains.yml: toolchains: unknown toolchain(s) {', '.join(map(repr, unknown))}")
    series: dict[str, dict[str, Pin]] = {}
    for key, entries in raw.items():
        kind = KINDS[key]
        if not isinstance(entries, dict) or not entries:
            raise ToolchainsError(f"toolchain {key!r}: must be a non-empty mapping of series to pins")
        pins: dict[str, Pin] = {}
        for s, pin in entries.items():
            where = f"toolchain {key!r} {s!r}"
            _string(f"toolchain {key!r}", "series", s, kind.series_re)
            parsed = _parse_pin(where, pin, hashed=kind.hashed, release=kind.release)
            _check_series_version(where, key, s, parsed.version)
            pins[s] = parsed
        series[key] = pins
    raw_tools = data["tools"]
    if not isinstance(raw_tools, dict):
        raise ToolchainsError("toolchains.yml: tools must be a mapping")
    unknown = sorted(set(raw_tools) - set(TOOLS))
    if unknown:
        raise ToolchainsError(f"toolchains.yml: tools: unknown tool(s) {', '.join(map(repr, unknown))}")
    tools = {name: _parse_pin(f"tool {name!r}", pin, hashed=True, release=False) for name, pin in raw_tools.items()}
    return Toolchains(series=series, tools=tools)


def load_toolchains(path: Path) -> Toolchains:
    """Read and validate `path`. Raises ToolchainsError on any violation."""
    try:
        text = path.read_text()
    except OSError as exc:
        raise ToolchainsError(f"toolchains.yml: cannot read {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ToolchainsError(f"toolchains.yml: {path} is not valid YAML: {exc}") from exc
    return parse_toolchains(data)


HEADER = """\
# Language toolchain pins (epic vergil-project/.github#649, spec §5.3).
#
# AUTO-MANAGED: the daily upstream refresh (docker/pins/upstream-refresh.sh)
# rewrites this file with `uv run docker/pins/resolve_toolchains.py --write`, then
# regenerates the matrix (`generate.py`) and CATALOG.md. Do not hand-edit a pin:
# run the resolver. check_pins.py requires exactly one entry per manifest series
# of each family below, plus the core Node major (`core.node`).
#
# Each pin is the exact release of its series and, for a verified download, the
# SHA-256 of each architecture's file:
#   python       python-build-standalone release <release>:
#                cpython-<version>+<release>-<x86_64|aarch64>-unknown-linux-gnu-install_only.tar.gz
#   go           https://go.dev/dl/go<version>.linux-<amd64|arm64>.tar.gz
#   node         https://nodejs.org/dist/v<version>/node-v<version>-linux-<x64|arm64>.tar.gz
#                (serves the ts-node family and the core Node)
#   rust         no hash: rustup checks every component against the release's
#                channel manifest
#   rustup-init  https://static.rust-lang.org/rustup/archive/<version>/<x86_64|aarch64>-unknown-linux-gnu/rustup-init
#
# generate.py passes them to each image as build args: TOOLCHAIN_VERSION,
# TOOLCHAIN_SHA256_AMD64, TOOLCHAIN_SHA256_ARM64, PBS_RELEASE (python), and
# RUSTUP_INIT_VERSION, RUSTUP_INIT_SHA256_AMD64, RUSTUP_INIT_SHA256_ARM64 (rust).
"""


def _q(value: str) -> str:
    return json.dumps(value)


def _dump_pin(pin: Pin, indent: str) -> list[str]:
    lines = [f"{indent}version: {_q(pin.version)}"]
    if pin.release is not None:
        lines.append(f"{indent}release: {_q(pin.release)}")
    if pin.sha256 is not None:
        lines.append(f"{indent}sha256:")
        lines += [f"{indent}  {arch}: {_q(pin.sha256[arch])}" for arch in ARCHES]
    return lines


def dump_toolchains(t: Toolchains) -> str:
    """Stable YAML for `t` (toolchains in KINDS order, series newest first);
    `load_toolchains` of the result returns `t`."""
    lines = [HEADER.rstrip("\n"), f"schema: {SCHEMA}", "toolchains:"]
    for key in KINDS:
        if key not in t.series:
            continue
        lines.append(f"  {key}:")
        for s in sorted(t.series[key], key=mf.version_sort_key, reverse=True):
            lines.append(f"    {_q(s)}:")
            lines += _dump_pin(t.series[key][s], "      ")
    lines.append("tools:" if t.tools else "tools: {}")
    for name in TOOLS:
        if name in t.tools:
            lines.append(f"  {name}:")
            lines += _dump_pin(t.tools[name], "    ")
    return "\n".join(lines) + "\n"


# --- Against the manifest -------------------------------------------------------


def required_series(m: mf.Manifest) -> dict[str, list[str]]:
    """The series each toolchain must pin: every manifest series of the family
    it serves, plus the core runtime it pins (the core Node major), newest
    first. A toolchain whose family is not in the manifest needs none."""
    families = {f.key: f for f in m.families}
    required: dict[str, list[str]] = {}
    for key, kind in KINDS.items():
        family = families.get(kind.family)
        found = {v.version for v in family.versions} if family is not None else set()
        for core_field, toolchain in CORE_PINS.items():
            if toolchain == key and m.core is not None:
                found.add(getattr(m.core, core_field))
        if found:
            required[key] = sorted(found, key=mf.version_sort_key, reverse=True)
    return required


def required_tools(m: mf.Manifest) -> list[str]:
    """The tools that must be pinned: each one whose toolchain has a series."""
    needed = required_series(m)
    return [name for name, toolchain in TOOLS.items() if toolchain in needed]


def consistency_errors(m: mf.Manifest, t: Toolchains) -> list[str]:
    """Every way `t` fails to pin exactly what `m` lists: a manifest series or
    the core Node major with no entry, or an entry for a series that is neither
    (an orphan); the same for the tools."""
    errors: list[str] = []
    required = required_series(m)
    for key in KINDS:
        want = set(required.get(key, ()))
        have = set(t.series.get(key, {}))
        for s in sorted(want - have, key=mf.version_sort_key, reverse=True):
            errors.append(f"toolchain {key!r} {s!r}: the manifest lists the series but toolchains.yml has no pin")
        for s in sorted(have - want, key=mf.version_sort_key, reverse=True):
            errors.append(
                f"toolchain {key!r} {s!r}: pinned, but neither a {KINDS[key].family} series nor a core runtime"
                " in the manifest; remove it"
            )
    tools = set(required_tools(m))
    for name in sorted(tools - set(t.tools)):
        errors.append(f"tool {name!r}: {TOOLS[name]} is pinned but toolchains.yml has no {name} pin")
    for name in sorted(set(t.tools) - tools):
        errors.append(f"tool {name!r}: pinned, but the manifest has no {TOOLS[name]} series; remove it")
    return errors


def _hash_args(prefix: str, pin: Pin) -> dict[str, str]:
    assert pin.sha256 is not None
    return {f"{prefix}_SHA256_{arch.upper()}": pin.sha256[arch] for arch in ARCHES}


def build_args(t: Toolchains, family: str, series: str) -> dict[str, str]:
    """The toolchain build args of `family`'s image at `series`, in order; `{}`
    for a family no toolchain pins (its toolchain comes from apt). A pinned
    family's series with no pin raises ToolchainsError."""
    keys = [key for key, kind in KINDS.items() if kind.family == family]
    if not keys:
        return {}
    (key,) = keys
    pin = t.series.get(key, {}).get(series)
    if pin is None:
        raise ToolchainsError(f"toolchain {key!r} {series!r}: {family} {series} has no pin in toolchains.yml")
    args = {"TOOLCHAIN_VERSION": pin.version}
    if pin.sha256 is not None:
        args |= _hash_args("TOOLCHAIN", pin)
    if pin.release is not None:
        args["PBS_RELEASE"] = pin.release
    for name, toolchain in TOOLS.items():
        if toolchain == key:
            tool = t.tools.get(name)
            if tool is None:
                raise ToolchainsError(f"tool {name!r}: {family} {series} needs it, but toolchains.yml has no pin")
            arg = name.upper().replace("-", "_")
            args[f"{arg}_VERSION"] = tool.version
            args |= _hash_args(arg, tool)
    return args


# --- The upstreams --------------------------------------------------------------

USER_AGENT = "vergil-containers-toolchain-pins (+https://github.com/vergil-project/vergil-containers)"
TIMEOUT_SECONDS = 30


def fetch_url(url: str) -> bytes:
    """GET `url` and return the body. Any HTTP, network or timeout failure
    raises ResolutionError naming the URL."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise ResolutionError(f"{url}: HTTP {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, OSError) as exc:  # URLError, timeouts, resets
        raise ResolutionError(f"{url}: {exc}") from exc


def _text(fetch: Fetch, url: str) -> str:
    try:
        return fetch(url).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResolutionError(f"{url}: not UTF-8 text: {exc}") from exc


def _json(fetch: Fetch, url: str) -> object:
    try:
        return json.loads(_text(fetch, url))
    except json.JSONDecodeError as exc:
        raise ResolutionError(f"{url}: not valid JSON: {exc}") from exc


def _sha256(where: str, value: object) -> str:
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        raise ResolutionError(f"{where}: {value!r} is not a SHA-256 hex digest")
    return value


def _newest_patch(versions: Iterable[str]) -> str:
    return max(versions, key=mf.version_sort_key)


def parse_sha256sums(where: str, text: str) -> dict[str, str]:
    """A `SHA256SUMS`-style file (`<hex>  <name>` per line) as {name: hex}."""
    sums: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ResolutionError(f"{where}:{lineno}: expected '<sha256>  <file>', got {line!r}")
        digest, name = parts
        sums[name.lstrip("*")] = _sha256(f"{where}:{lineno}", digest.lower())
    return sums


# python-build-standalone (https://github.com/astral-sh/python-build-standalone).
# Its releases are dated tags; the Atom feed of the repository's releases lists
# the recent ones without the GitHub API's unauthenticated rate limit, and each
# release's `SHA256SUMS` asset lists every build with its digest.
PBS_RELEASES_FEED = "https://github.com/astral-sh/python-build-standalone/releases.atom"
PBS_DOWNLOAD = "https://github.com/astral-sh/python-build-standalone/releases/download/{release}/{name}"
PBS_TRIPLES = {"amd64": "x86_64-unknown-linux-gnu", "arm64": "aarch64-unknown-linux-gnu"}
_PBS_TAG_RE = re.compile(r"/astral-sh/python-build-standalone/releases/tag/(\d{8})\b")
_PBS_ASSET_RE = re.compile(
    r"^cpython-(?P<version>\d+\.\d+\.\d+)\+(?P<release>\d{8})-(?P<triple>[a-z0-9_]+-unknown-linux-gnu)"
    r"-install_only\.tar\.gz$"
)


def pbs_asset(version: str, release: str, arch: str) -> str:
    """The file name of a python-build-standalone install-only build."""
    return f"cpython-{version}+{release}-{PBS_TRIPLES[arch]}-install_only.tar.gz"


def pbs_releases(fetch: Fetch = fetch_url) -> list[str]:
    """python-build-standalone's recent release tags, newest first."""
    tags = set(_PBS_TAG_RE.findall(_text(fetch, PBS_RELEASES_FEED)))
    if not tags:
        raise ResolutionError(f"{PBS_RELEASES_FEED}: no release tags in the feed")
    return sorted(tags, reverse=True)


def pbs_builds(release: str, fetch: Fetch = fetch_url) -> dict[str, Pin]:
    """The install-only builds of one python-build-standalone release that
    exist for every architecture: series -> pin (the newest patch of the
    series in the release, its release tag and both hashes)."""
    url = PBS_DOWNLOAD.format(release=release, name="SHA256SUMS")
    by_version: dict[str, dict[str, str]] = {}
    for name, digest in parse_sha256sums(url, _text(fetch, url)).items():
        match = _PBS_ASSET_RE.match(name)
        if match is None or match["release"] != release:
            continue
        arch = next((a for a, triple in PBS_TRIPLES.items() if triple == match["triple"]), None)
        if arch is not None:
            by_version.setdefault(match["version"], {})[arch] = digest
    complete = {v: h for v, h in by_version.items() if set(h) == set(ARCHES)}
    builds: dict[str, Pin] = {}
    for version in complete:
        s = version.rsplit(".", 1)[0]
        if s not in builds or mf.version_sort_key(version) > mf.version_sort_key(builds[s].version):
            builds[s] = Pin(version=version, sha256=dict(sorted(complete[version].items())), release=release)
    return builds


def resolve_python(series: Iterable[str], fetch: Fetch = fetch_url) -> dict[str, Pin]:
    """Each series' pin: its build in the newest python-build-standalone
    release that has an install-only build of the series for both
    architectures."""
    wanted = list(series)
    found: dict[str, Pin] = {}
    for release in pbs_releases(fetch):
        if len(found) == len(wanted):
            break
        builds = pbs_builds(release, fetch)
        for s in wanted:
            if s not in found and s in builds:
                found[s] = builds[s]
    missing = [s for s in wanted if s not in found]
    if missing:
        raise ResolutionError(
            f"python-build-standalone: no recent release has an install-only build of "
            f"{', '.join(missing)} for both {' and '.join(ARCHES)}"
        )
    return found


# go.dev (https://go.dev/dl/): every release, with each file's SHA-256.
GO_RELEASES = "https://go.dev/dl/?mode=json&include=all"
_GO_VERSION_RE = re.compile(r"^go(\d+\.\d+\.\d+)$")


def go_releases(fetch: Fetch = fetch_url) -> dict[str, dict[str, object]]:
    """Every stable Go release with a Linux archive for each architecture:
    version ("1.27.3") -> {arch: the listed sha256}. The digests are as listed,
    unchecked: the oldest releases list none (they published SHA-1 sums), so
    `resolve_go` checks the digests of the release it picks."""
    data = _json(fetch, GO_RELEASES)
    if not isinstance(data, list):
        raise ResolutionError(f"{GO_RELEASES}: expected a list of releases")
    releases: dict[str, dict[str, str]] = {}
    for i, entry in enumerate(data):
        where = f"{GO_RELEASES}: [{i}]"
        if not isinstance(entry, dict) or not isinstance(entry.get("files"), list):
            raise ResolutionError(f"{where}: expected a release with a list of files")
        match = _GO_VERSION_RE.match(str(entry.get("version")))
        if entry.get("stable") is not True or match is None:
            continue
        version = match[1]
        hashes: dict[str, object] = {}
        for f in entry["files"]:
            if not isinstance(f, dict):
                raise ResolutionError(f"{where}: a file entry is not a mapping")
            if f.get("os") == "linux" and f.get("kind") == "archive" and f.get("arch") in ARCHES:
                expected = f"go{version}.linux-{f['arch']}.tar.gz"
                if f.get("filename") != expected:
                    raise ResolutionError(f"{where}: linux {f['arch']} archive is {f.get('filename')!r}, not {expected!r}")
                hashes[f["arch"]] = f.get("sha256")
        if set(hashes) == set(ARCHES):
            releases[version] = dict(sorted(hashes.items()))
    return releases


def resolve_go(series: Iterable[str], fetch: Fetch = fetch_url) -> dict[str, Pin]:
    releases = go_releases(fetch)
    found: dict[str, Pin] = {}
    for s in series:
        versions = [v for v in releases if v.startswith(f"{s}.")]
        if not versions:
            raise ResolutionError(f"go.dev: no stable go{s}.x release with linux archives for both architectures")
        version = _newest_patch(versions)
        hashes = {arch: _sha256(f"go.dev: go{version}.linux-{arch}.tar.gz", releases[version][arch]) for arch in ARCHES}
        found[s] = Pin(version=version, sha256=hashes)
    return found


# nodejs.org: the release index, and each release's SHASUMS256.txt.
NODE_INDEX = "https://nodejs.org/dist/index.json"
NODE_SHASUMS = "https://nodejs.org/dist/v{version}/SHASUMS256.txt"
NODE_PLATFORMS = {"amd64": "linux-x64", "arm64": "linux-arm64"}
_NODE_VERSION_RE = re.compile(r"^v(\d+\.\d+\.\d+)$")


def node_tarball(version: str, arch: str) -> str:
    return f"node-v{version}-{NODE_PLATFORMS[arch]}.tar.gz"


def node_releases(fetch: Fetch = fetch_url) -> list[str]:
    """Every Node release with a Linux build for each architecture, newest
    first, as bare versions ("24.11.1")."""
    data = _json(fetch, NODE_INDEX)
    if not isinstance(data, list):
        raise ResolutionError(f"{NODE_INDEX}: expected a list of releases")
    versions: list[str] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict) or not isinstance(entry.get("files"), list):
            raise ResolutionError(f"{NODE_INDEX}: [{i}]: expected a release with a list of files")
        match = _NODE_VERSION_RE.match(str(entry.get("version")))
        if match is not None and all(p in entry["files"] for p in NODE_PLATFORMS.values()):
            versions.append(match[1])
    return sorted(versions, key=mf.version_sort_key, reverse=True)


def node_hashes(version: str, fetch: Fetch = fetch_url) -> dict[str, str]:
    """{arch: sha256} of a release's Linux tarballs, from its SHASUMS256.txt."""
    url = NODE_SHASUMS.format(version=version)
    sums = parse_sha256sums(url, _text(fetch, url))
    hashes: dict[str, str] = {}
    for arch in ARCHES:
        name = node_tarball(version, arch)
        if name not in sums:
            raise ResolutionError(f"{url}: no entry for {name}")
        hashes[arch] = sums[name]
    return hashes


def resolve_node(series: Iterable[str], fetch: Fetch = fetch_url) -> dict[str, Pin]:
    releases = node_releases(fetch)
    found: dict[str, Pin] = {}
    for major in series:
        versions = [v for v in releases if v.startswith(f"{major}.")]
        if not versions:
            raise ResolutionError(f"nodejs.org: no v{major}.x release with linux-x64 and linux-arm64 builds")
        version = _newest_patch(versions)
        found[major] = Pin(version=version, sha256=node_hashes(version, fetch))
    return found


# The Rust release channel: `channel-rust-<x.y>.toml` is the manifest of the
# newest release of the series, the one rustup installs for a `<x.y>` toolchain.
RUST_CHANNEL = "https://static.rust-lang.org/dist/channel-rust-{series}.toml"
_RUST_PKG_VERSION_RE = re.compile(r"^(\d+\.\d+\.\d+) \(")


def rust_release(series: str, fetch: Fetch = fetch_url) -> str:
    """The newest release of a Rust series ("1.93.1"), from its channel manifest."""
    url = RUST_CHANNEL.format(series=series)
    try:
        data = tomllib.loads(_text(fetch, url))
    except tomllib.TOMLDecodeError as exc:
        raise ResolutionError(f"{url}: not valid TOML: {exc}") from exc
    raw = data.get("pkg", {}).get("rust", {}).get("version")
    match = _RUST_PKG_VERSION_RE.match(raw) if isinstance(raw, str) else None
    if match is None:
        raise ResolutionError(f"{url}: pkg.rust.version {raw!r} is not '<x.y.z> (<commit> <date>)'")
    version = match[1]
    if not version.startswith(f"{series}."):
        raise ResolutionError(f"{url}: pkg.rust.version {version!r} is not a release of {series}")
    return version


def resolve_rust(series: Iterable[str], fetch: Fetch = fetch_url) -> dict[str, Pin]:
    return {s: Pin(version=rust_release(s, fetch)) for s in series}


# rustup: the current release, and each architecture's rustup-init digest.
RUSTUP_RELEASE = "https://static.rust-lang.org/rustup/release-stable.toml"
RUSTUP_INIT_SHA256 = "https://static.rust-lang.org/rustup/archive/{version}/{triple}/rustup-init.sha256"
RUSTUP_TRIPLES = {"amd64": "x86_64-unknown-linux-gnu", "arm64": "aarch64-unknown-linux-gnu"}


def rustup_init_release(fetch: Fetch = fetch_url) -> Pin:
    """The current rustup release and its rustup-init digest per architecture."""
    try:
        data = tomllib.loads(_text(fetch, RUSTUP_RELEASE))
    except tomllib.TOMLDecodeError as exc:
        raise ResolutionError(f"{RUSTUP_RELEASE}: not valid TOML: {exc}") from exc
    version = data.get("version")
    if not isinstance(version, str) or not _PATCH_RE.match(version):
        raise ResolutionError(f"{RUSTUP_RELEASE}: version {version!r} is not x.y.z")
    hashes: dict[str, str] = {}
    for arch in ARCHES:
        url = RUSTUP_INIT_SHA256.format(version=version, triple=RUSTUP_TRIPLES[arch])
        fields = _text(fetch, url).split()
        if not fields:
            raise ResolutionError(f"{url}: empty")
        hashes[arch] = _sha256(url, fields[0].lower())
    return Pin(version=version, sha256=hashes)


RESOLVERS: dict[str, Callable[[Iterable[str], Fetch], dict[str, Pin]]] = {
    "python": resolve_python,
    "go": resolve_go,
    "node": resolve_node,
    "rust": resolve_rust,
}
TOOL_RESOLVERS: dict[str, Callable[[Fetch], Pin]] = {"rustup-init": rustup_init_release}


def resolve(m: mf.Manifest, fetch: Fetch = fetch_url) -> Toolchains:
    """The newest pin of every series and tool `m` requires. Any failed lookup
    raises ResolutionError: nothing is ever partly resolved."""
    series = {key: RESOLVERS[key](wanted, fetch) for key, wanted in required_series(m).items()}
    tools = {name: TOOL_RESOLVERS[name](fetch) for name in required_tools(m)}
    t = Toolchains(series=series, tools=tools)
    errors = consistency_errors(m, t)
    if errors:
        raise ResolutionError("the resolved pins do not match the manifest:\n  " + "\n  ".join(errors))
    return t


def changes(old: Toolchains | None, new: Toolchains) -> list[str]:
    """One line per pin that differs between `old` and `new`. A pin whose
    release is unchanged but whose hash differs raises ResolutionError: the
    refresh never rewrites the hash of a release it already pins."""
    def flat(t: Toolchains | None) -> dict[str, Pin]:
        if t is None:
            return {}
        out = {f"{key} {s}": pin for key, pins in t.series.items() for s, pin in pins.items()}
        out |= {name: pin for name, pin in t.tools.items()}
        return out

    before, after = flat(old), flat(new)
    lines = []
    for name in sorted(before.keys() | after.keys()):
        a, b = before.get(name), after.get(name)
        if a == b:
            continue
        if a is None:
            lines.append(f"added {name}: {b.version}")
        elif b is None:
            lines.append(f"removed {name}: {a.version}")
        elif a.version == b.version and a.release == b.release:
            raise ResolutionError(
                f"{name} {a.version}: upstream now lists a different SHA-256 for a release that is already"
                f" pinned ({a.sha256} -> {b.sha256}). A published release's files should never change:"
                " check the upstream before moving this pin by hand"
            )
        else:
            lines.append(f"bumped {name}: {a.version} -> {b.version}")
    return lines


def main(argv: list[str], fetch: Fetch = fetch_url, manifest: Path = MANIFEST_YML, out: Path = TOOLCHAINS_YML) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help=f"rewrite {out.name} with the resolved pins")
    args = parser.parse_args(argv)
    try:
        m = mf.load_manifest(manifest)
        old = load_toolchains(out) if out.exists() else None
        new = resolve(m, fetch)
        lines = changes(old, new)
    except (mf.ManifestError, ToolchainsError, ResolutionError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    if not lines:
        print("no toolchain pin changes")
    if args.write and (old != new or not out.exists() or out.read_text() != dump_toolchains(new)):
        out.write_text(dump_toolchains(new))
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
