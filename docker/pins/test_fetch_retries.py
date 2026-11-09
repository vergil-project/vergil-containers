"""Every build-time download in the image sources retries transient errors and
still fails the build when the retries run out (issue #743).

The nightly publish went red on one-off network faults: a connection reset
fetching the uv installer and a reset on a GitHub release download. The rule
the fragments follow, pinned here so a new download cannot skip it:

- every `curl` carries `--retry 5 --retry-all-errors --retry-delay 2` and `-f`,
  so a transient error is retried and a persistent one fails the RUN;
- every `curl` writes to a file (`-o`) and never feeds a pipe: curl discards a
  failed partial transfer before retrying only when it writes to a file, so a
  retried pipe could pass duplicated bytes downstream;
- no download tool other than curl is used, and nothing is piped into a shell.

The checks read the sources (docker/common fragments and the per-image
templates), not the generated Dockerfiles, because the sources are what is
committed and reviewed.
"""

import re
import shlex
from pathlib import Path

import pytest

DOCKER = Path(__file__).resolve().parent.parent
SOURCES = sorted(DOCKER.glob("common/*.dockerfile")) + sorted(DOCKER.glob("*/Dockerfile.template"))
SEPARATORS = {"&&", "||", "|", ";", ";;", "(", ")"}
KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
RETRY = ("--retry", "5", "--retry-all-errors", "--retry-delay", "2")


def _run_instructions(path: Path) -> list[str]:
    """Each RUN instruction of a Dockerfile source as one logical line, with
    comment lines dropped and backslash continuations joined."""
    lines = [ln for ln in path.read_text().splitlines() if not ln.lstrip().startswith("#")]
    logical = "\n".join(lines).replace("\\\n", " ").splitlines()
    return [ln.strip()[len("RUN"):] for ln in logical if ln.strip().startswith("RUN ")]


def _commands(run: str) -> list[tuple[list[str], str | None]]:
    """Split a RUN body into simple commands, each with the separator that
    follows it (None at the end)."""
    lexer = shlex.shlex(run, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    commands, current = [], []
    for token in lexer:
        if token in SEPARATORS:
            if current:
                commands.append((current, token))
            current = []
        else:
            current.append(token)
    if current:
        commands.append((current, None))
    return commands


def _program(argv: list[str]) -> list[str]:
    """argv from the program name on: drops leading shell keywords and
    `VAR=value` assignments (`if UV_INSTALL_DIR=/x sh …` runs `sh`)."""
    i = 0
    while i < len(argv) and (argv[i] in KEYWORDS or ASSIGNMENT.match(argv[i])):
        i += 1
    return argv[i:]


def _all_commands() -> list[tuple[Path, list[str], str | None]]:
    return [
        (path, prog, after)
        for path in SOURCES
        for run in _run_instructions(path)
        for argv, after in _commands(run)
        if (prog := _program(argv))
    ]


# `curl --version` downloads nothing: the package toolchain images run it in
# their build-time checks (vergil-containers#728). It is the only curl exempt.
VERSION_PROBE = ["curl", "--version"]


def _curls() -> list[tuple[Path, list[str], str | None]]:
    return [
        (p, argv, after)
        for p, argv, after in _all_commands()
        if argv[0] == "curl" and argv != VERSION_PROBE
    ]


def test_only_a_bare_version_probe_is_exempt():
    # A curl with a URL beside --version is still a download and still checked.
    assert any(argv == VERSION_PROBE for _, argv, _ in _all_commands())
    probe = _commands(" curl --version https://x/y")[0][0]
    assert probe != VERSION_PROBE


def _has_retry(argv: list[str]) -> bool:
    return any(tuple(argv[i:i + len(RETRY)]) == RETRY for i in range(len(argv)))


def _fails_on_http_error(argv: list[str]) -> bool:
    return any(a == "--fail" or (a.startswith("-") and not a.startswith("--") and "f" in a) for a in argv)


def test_the_sources_contain_downloads():
    # Guards against the checks below passing vacuously on a parsing slip.
    assert SOURCES
    assert len(_curls()) >= 20


@pytest.mark.parametrize("path,argv,after", _curls(), ids=lambda v: v.name if isinstance(v, Path) else "")
def test_every_curl_retries_and_fails_loud(path, argv, after):
    cmd = " ".join(argv)
    assert _has_retry(argv), f"{path.name}: curl without `{' '.join(RETRY)}`: {cmd}"
    assert _fails_on_http_error(argv), f"{path.name}: curl without -f: {cmd}"


@pytest.mark.parametrize("path,argv,after", _curls(), ids=lambda v: v.name if isinstance(v, Path) else "")
def test_every_curl_writes_a_file_not_a_pipe(path, argv, after):
    cmd = " ".join(argv)
    assert "-o" in argv or "--output" in argv, f"{path.name}: curl without -o: {cmd}"
    assert after != "|", f"{path.name}: curl output piped: {cmd}"


def test_no_other_downloader_and_nothing_piped_into_a_shell():
    commands = _all_commands()
    assert not [(p.name, a) for p, a, _ in commands if a[0] == "wget"]
    piped_into = {
        commands[i + 1][1][0]
        for i, (_, _, after) in enumerate(commands[:-1])
        if after == "|"
    }
    assert not piped_into & {"sh", "bash"}, piped_into


def test_parser_sees_pipes_and_retries():
    # The splitter itself: a piped curl without retries is caught on both counts.
    ((argv, after), (shell, _)) = _commands(' curl -fsSL "https://x/y" | UV_INSTALL_DIR=/b sh')
    assert argv == ["curl", "-fsSL", "https://x/y"] and after == "|"
    assert not _has_retry(argv)
    assert _program(shell) == ["sh"]
    ((guarded, _), *_rest) = _commands(" if curl -fsSL u -o f; then true; fi")
    assert _program(guarded)[0] == "curl"
    ((argv, after),) = _commands(" curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 u -o f")
    assert _has_retry(argv) and _fails_on_http_error(argv) and after is None
