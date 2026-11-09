# /// script
# dependencies = ["pyyaml"]
# ///
"""Generate every version list in the repo from docker/versions/manifest.yml.

Run with no arguments to rewrite the generated files; `--check` exits 1 and
names each file that is out of date (the CI drift gate, like CATALOG.md from
pins.yml). `--root` points at a different repo checkout (used by the tests).

Generated outputs (epic vergil-project/.github#407, spec §6.1):

- docker/versions/matrix.json: the build matrix cd-docker-publish.yml and
  `docker/build.sh` read (every family version, then every toolchain version,
  then `base`, ordered by depth in the image tree);
- docker/versions/window.json: the published window consumers read (language
  families only: toolchains are not languages);
- the `docker/build.sh` smoke-test table;
- the `package-cleanup.yml` and `package-cache-warm.yml` package lists;
- every docker/<family>/Dockerfile.template `ARG <BUILD_ARG>=` default;
- the version tables in README.md and the docs site.

In-place blocks sit between `BEGIN generated: <name>` and `END generated: <name>`
marker lines (a `#` comment, or an HTML comment in Markdown). There are no
language branches: anything family-specific comes from the manifest or from the
family's own files under docker/."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import manifest as mf

ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST = Path("docker/versions/manifest.yml")
MATRIX_JSON = Path("docker/versions/matrix.json")
WINDOW_JSON = Path("docker/versions/window.json")
BUILD_SH = Path("docker/build.sh")
PACKAGE_CLEANUP = Path(".github/workflows/package-cleanup.yml")
PACKAGE_CACHE_WARM = Path(".github/workflows/package-cache-warm.yml")
DOC_TABLES = (
    Path("README.md"),
    Path("docs/site/docs/index.md"),
    Path("docs/site/docs/images/index.md"),
)

# The unversioned base image is not a language family; it is listed alongside
# the families wherever every image is enumerated.
BASE_KEY = mf.BASE_KEY
BASE_VERSION = mf.BASE_VERSION
IMAGE_PREFIXES = ("dev", "prod")
# Datestamp-alias retention per image prefix (package-cleanup.yml reap-aliases).
REAP_WINDOWS = (("prod", "30 days"), ("dev", "7 days"))

WINDOW_SCHEMA = 1


class GenerateError(RuntimeError):
    """A target file cannot be generated (missing file, marker or anchor)."""


def _read(root: Path, rel: Path) -> str:
    path = root / rel
    try:
        return path.read_text()
    except OSError as exc:
        raise GenerateError(f"{rel}: cannot read: {exc}") from exc


def _markers(name: str, markdown: bool) -> tuple[str, str]:
    if markdown:
        return f"<!-- BEGIN generated: {name} -->", f"<!-- END generated: {name} -->"
    return f"# BEGIN generated: {name}", f"# END generated: {name}"


def replace_block(text: str, rel: Path, name: str, body: list[str], *, markdown: bool) -> str:
    """Replace the lines between one BEGIN/END marker pair with `body`.

    Body lines are indented like the BEGIN marker. Exactly one marker pair must
    exist, in order; anything else is an error, never a silent skip."""
    begin, end = _markers(name, markdown)
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.strip() == begin]
    ends = [i for i, line in enumerate(lines) if line.strip() == end]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise GenerateError(
            f"{rel}: expected exactly one {begin!r} ... {end!r} block, "
            f"found {len(starts)} BEGIN and {len(ends)} END marker(s)"
        )
    start, stop = starts[0], ends[0]
    indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    new_body = [f"{indent}{line}" if line else "" for line in body]
    return "\n".join(lines[: start + 1] + new_body + lines[stop:])


def _json(data: object) -> str:
    return json.dumps(data, indent=2) + "\n"


def _matrix_parent(p: mf.Parent | None) -> dict[str, str] | None:
    return None if p is None else {"language": p.name, "version": p.version}


def render_matrix_json(m: mf.Manifest) -> str:
    """The publish matrix: one entry per family version, then per toolchain
    version, then `base`, ordered by depth in the image tree (stable, so within
    a depth the order is the manifest's: families, toolchains, then `base`).

    Each entry is `language` (the image key), `version`, `build-args` (every
    `--build-arg` the image takes, as a map: a family's or toolchain's version
    arg, and `{}` for `base`),
    `parent` (`null`, or the `language` and `version` of the entry it is built
    FROM) and `depth` (the publish tier). Raises ManifestError on a bad tree."""
    depths = mf.entry_depths(m)
    include = [
        {
            "language": f.key,
            "version": v.version,
            "build-args": {f.build_arg: v.version},
            "parent": _matrix_parent(f.parent),
            "depth": depths[f.key],
        }
        for f in m.families
        for v in f.versions
    ]
    include += [
        {
            "language": t.key,
            "version": v,
            "build-args": {t.build_arg: v},
            "parent": None,
            "depth": depths[t.key],
        }
        for t in m.toolchains
        for v in t.versions
    ]
    include.append({
        "language": BASE_KEY,
        "version": BASE_VERSION,
        "build-args": {},
        "parent": _matrix_parent(m.base_parent),
        "depth": depths[BASE_KEY],
    })
    include.sort(key=lambda e: e["depth"])
    return _json({"include": include})


def render_window_json(m: mf.Manifest) -> str:
    languages: dict[str, dict[str, list[dict[str, object]]]] = {}
    for f in m.families:
        family = {
            "key": f.key,
            "token_prefix": f.token_prefix,
            "versions": [
                {
                    "version": v.version,
                    "eol": v.eol.isoformat() if v.eol else None,
                    "in_policy": v.in_policy,
                    "runtime_published": v.runtime_published,
                }
                for v in f.versions
            ],
        }
        languages.setdefault(f.language, {"families": []})["families"].append(family)
    return _json({"schema": WINDOW_SCHEMA, "languages": languages})


def smoke_test_dir(root: Path, f: mf.Family | mf.Toolchain) -> str | None:
    """The directory under docker/ holding the entry's smoke test, by
    convention: docker/<key>/smoke-test.sh, else (for a family) the one its
    language shares, docker/<language>/smoke-test.sh. A toolchain has no
    language, so only its own directory counts. `includes.dependency_map`
    follows the same rule, so a change to a shared smoke test selects every
    family it runs for."""
    directories = (f.key, f.language) if isinstance(f, mf.Family) else (f.key,)
    for directory in directories:
        if (root / "docker" / directory / "smoke-test.sh").is_file():
            return directory
    return None


def render_build_sh(m: mf.Manifest, root: Path) -> str:
    """build.sh's smoke-test table: `<entry>:<directory>` for each family, then
    each toolchain, with a smoke test. The builds themselves come from
    matrix.json at run time."""
    pairs = []
    for f in (*m.families, *m.toolchains):
        directory = smoke_test_dir(root, f)
        if directory is not None:
            pairs.append(f"{f.key}:{directory}")
    body = [f'smoke_tests="{" ".join(pairs)}"']
    return replace_block(_read(root, BUILD_SH), BUILD_SH, "versions", body, markdown=False)


def _template(f_key: str) -> Path:
    return Path("docker") / f_key / "Dockerfile.template"


def _versions(f: mf.Family | mf.Toolchain) -> list[str]:
    """The entry's versions, newest first."""
    return [v.version for v in f.versions] if isinstance(f, mf.Family) else list(f.versions)


def render_arg_default(f: mf.Family | mf.Toolchain, root: Path) -> str:
    """Set the template's `ARG <BUILD_ARG>=` default to the newest version."""
    rel = _template(f.key)
    text = _read(root, rel)
    pattern = re.compile(rf"^ARG {re.escape(f.build_arg)}=.*$", re.MULTILINE)
    found = pattern.findall(text)
    if len(found) != 1:
        raise GenerateError(
            f"{rel}: expected exactly one 'ARG {f.build_arg}=<default>' line, found {len(found)}"
        )
    return pattern.sub(f"ARG {f.build_arg}={_versions(f)[0]}", text)


def _image_keys(m: mf.Manifest) -> list[str]:
    """Every image the repo publishes: `base`, each family, each toolchain."""
    return [BASE_KEY] + [f.key for f in m.families] + [t.key for t in m.toolchains]


def _package_list(m: mf.Manifest) -> list[str]:
    """Every org package, as YAML list items: each prefix, then each image."""
    return [f"- {prefix}-{key}" for prefix in IMAGE_PREFIXES for key in _image_keys(m)]


def render_package_cache_warm(m: mf.Manifest, root: Path) -> str:
    text = _read(root, PACKAGE_CACHE_WARM)
    return replace_block(text, PACKAGE_CACHE_WARM, "versions (warm)", _package_list(m), markdown=False)


def render_package_cleanup(m: mf.Manifest, root: Path) -> str:
    cleanup = _package_list(m)
    reap: list[str] = []
    for prefix, window in REAP_WINDOWS:
        for key in _image_keys(m):
            reap += [f"- package: {prefix}-{key}", f'  older_than: "{window}"']
    text = _read(root, PACKAGE_CLEANUP)
    text = replace_block(text, PACKAGE_CLEANUP, "versions (cleanup)", cleanup, markdown=False)
    return replace_block(text, PACKAGE_CLEANUP, "versions (reap)", reap, markdown=False)


def _base_image(f_key: str, build_arg: str | None, root: Path) -> str:
    """The upstream base image, read from the template's first FROM line."""
    rel = _template(f_key)
    match = re.search(r"^FROM\s+(\S+)", _read(root, rel), re.MULTILINE)
    if match is None:
        raise GenerateError(f"{rel}: no FROM line to read the base image from")
    image = match.group(1)
    if build_arg:
        image = image.replace(f"${{{build_arg}}}", "<v>")
    return image


def _table(rows: list[list[str]]) -> list[str]:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths)) + " |"

    return [line(rows[0]), line(["-" * w for w in widths])] + [line(r) for r in rows[1:]]


def render_doc_table(m: mf.Manifest, root: Path) -> list[str]:
    rows = [["Image", "Language", "Versions", "Base"]]
    for f in m.families:
        rows.append([
            f"`dev-{f.key}`",
            f.language,
            ", ".join(v.version for v in f.versions),
            f"`{_base_image(f.key, f.build_arg, root)}`",
        ])
    for t in m.toolchains:
        rows.append([
            f"`dev-{t.key}`",
            "—",
            ", ".join(t.versions),
            f"`{_base_image(t.key, t.build_arg, root)}`",
        ])
    rows.append([f"`dev-{BASE_KEY}`", "—", BASE_VERSION, f"`{_base_image(BASE_KEY, None, root)}`"])
    return _table(rows)


def render_all(m: mf.Manifest, root: Path) -> dict[Path, str]:
    """The full new content of every generated file, keyed by absolute path."""
    out: dict[Path, str] = {
        root / MATRIX_JSON: render_matrix_json(m),
        root / WINDOW_JSON: render_window_json(m),
        root / BUILD_SH: render_build_sh(m, root),
        root / PACKAGE_CLEANUP: render_package_cleanup(m, root),
        root / PACKAGE_CACHE_WARM: render_package_cache_warm(m, root),
    }
    for f in (*m.families, *m.toolchains):
        out[root / _template(f.key)] = render_arg_default(f, root)
    table = render_doc_table(m, root)
    for rel in DOC_TABLES:
        out[root / rel] = replace_block(_read(root, rel), rel, "versions", table, markdown=True)
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if any file is out of date")
    parser.add_argument("--root", type=Path, default=ROOT, help="repo root (default: this checkout)")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        rendered = render_all(mf.load_manifest(root / MANIFEST), root)
    except (mf.ManifestError, GenerateError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    stale = [
        path for path, content in rendered.items()
        if not path.is_file() or path.read_text() != content
    ]
    if args.check:
        if stale:
            print("Generated version files are out of date with docker/versions/manifest.yml:")
            for path in stale:
                print(f"  {path.relative_to(root)}")
            print("Run `uv run docker/versions/generate.py` and commit the result.")
            return 1
        print("Generated version files are up to date.")
        return 0
    for path in stale:
        path.write_text(rendered[path])
        print(f"wrote {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
