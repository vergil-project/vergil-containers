"""Generate every version list in the repo from docker/versions/manifest.yml.

Run with no arguments to rewrite the generated files; `--check` exits 1 and
names each file that is out of date (the CI drift gate, like CATALOG.md from
pins.yml). `--root` points at a different repo checkout (used by the tests).

Generated outputs (epic vergil-project/.github#407, spec §6.1):

- docker/versions/matrix.json: the cd-docker-publish.yml build matrix;
- docker/versions/window.json: the published window consumers read;
- the `docker/build.sh` build and smoke-test lines;
- the `package-cleanup.yml` package lists;
- every docker/<family>/Dockerfile.template `ARG <BUILD_ARG>=` default;
- the version tables in README.md, CLAUDE.md and the docs site.

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
DOC_TABLES = (
    Path("README.md"),
    Path("CLAUDE.md"),
    Path("docs/site/docs/index.md"),
    Path("docs/site/docs/images/index.md"),
)

# The unversioned base image is not a language family; it is listed alongside
# the families wherever every image is enumerated.
BASE_KEY = "base"
BASE_VERSION = "latest"
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


def render_matrix_json(m: mf.Manifest) -> str:
    include = [
        {"language": f.key, "version": v.version, "build-arg": f.build_arg}
        for f in m.families
        for v in f.versions
    ]
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


def _smoke_test(root: Path, f: mf.Family) -> str | None:
    """The family's smoke test, by convention: docker/<key>/smoke-test.sh, else
    the one its language shares, docker/<language>/smoke-test.sh."""
    for directory in (f.key, f.language):
        if (root / "docker" / directory / "smoke-test.sh").is_file():
            return directory
    return None


def render_build_sh(m: mf.Manifest, root: Path) -> str:
    body = [f"build {f.key} {f.build_arg} {v.version}" for f in m.families for v in f.versions]
    for f in m.families:
        directory = _smoke_test(root, f)
        if directory is None:
            continue
        body += [
            f'"${{script_dir}}/{directory}/smoke-test.sh" "dev-{f.key}:{v.version}" "$runtime"'
            for v in f.versions
        ]
    return replace_block(_read(root, BUILD_SH), BUILD_SH, "versions", body, markdown=False)


def _template(f_key: str) -> Path:
    return Path("docker") / f_key / "Dockerfile.template"


def render_arg_default(f: mf.Family, root: Path) -> str:
    """Set the template's `ARG <BUILD_ARG>=` default to the newest version."""
    rel = _template(f.key)
    text = _read(root, rel)
    pattern = re.compile(rf"^ARG {re.escape(f.build_arg)}=.*$", re.MULTILINE)
    found = pattern.findall(text)
    if len(found) != 1:
        raise GenerateError(
            f"{rel}: expected exactly one 'ARG {f.build_arg}=<default>' line, found {len(found)}"
        )
    return pattern.sub(f"ARG {f.build_arg}={f.versions[0].version}", text)


def render_package_cleanup(m: mf.Manifest, root: Path) -> str:
    keys = [BASE_KEY] + [f.key for f in m.families]
    cleanup = [f"- {prefix}-{key}" for prefix in IMAGE_PREFIXES for key in keys]
    reap: list[str] = []
    for prefix, window in REAP_WINDOWS:
        for key in keys:
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
    rows.append([f"`dev-{BASE_KEY}`", "—", BASE_VERSION, f"`{_base_image(BASE_KEY, None, root)}`"])
    return _table(rows)


def render_all(m: mf.Manifest, root: Path) -> dict[Path, str]:
    """The full new content of every generated file, keyed by absolute path."""
    out: dict[Path, str] = {
        root / MATRIX_JSON: render_matrix_json(m),
        root / WINDOW_JSON: render_window_json(m),
        root / BUILD_SH: render_build_sh(m, root),
        root / PACKAGE_CLEANUP: render_package_cleanup(m, root),
    }
    for f in m.families:
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
            print("Run `python3 docker/versions/generate.py` and commit the result.")
            return 1
        print("Generated version files are up to date.")
        return 0
    for path in stale:
        path.write_text(rendered[path])
        print(f"wrote {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
