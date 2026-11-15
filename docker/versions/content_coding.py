"""Decode an HTTP response body by its `Content-Encoding` (issue #883).

`urllib.request.urlopen` never decodes a content coding: `response.read()`
returns the bytes as sent. A request with no `Accept-Encoding` header lets the
server choose any coding (RFC 9110 §12.5.3), and apt.llvm.org's cache answers
such a request with gzip, so an undecoded body reached the parsers as gzip
bytes.

Both upstream fetchers, the lifecycle check's (`lifecycle/sources.py`) and the
toolchain pins' (`pins/resolve_toolchains.py`), send `ACCEPT_ENCODING` and pass
the body through `decode`. It depends on the standard library only, so neither
package takes on the other's imports.

Fail loud: an unsupported coding or a body that does not decompress raises
ContentCodingError naming the URL and the coding. Undecoded bytes are never
returned. Each fetcher re-raises it as its own error type.
"""
from __future__ import annotations

import gzip
import zlib

# The codings `decode` undoes, as the request's Accept-Encoding header.
ACCEPT_ENCODING = "gzip, deflate"

# RFC 9110 §8.4.1.3: a recipient SHOULD treat x-gzip as gzip.
_GZIP = frozenset({"gzip", "x-gzip"})


class ContentCodingError(ValueError):
    """A response body uses a coding `decode` does not support, or does not
    decompress under the coding it names."""


def _undo(url: str, coding: str, body: bytes) -> bytes:
    try:
        if coding in _GZIP:
            return gzip.decompress(body)
        if coding == "deflate":
            # RFC 9110 §8.4.1.2: "deflate" is the zlib format (RFC 1950).
            return zlib.decompress(body)
    except (OSError, EOFError, zlib.error) as exc:  # BadGzipFile is an OSError
        raise ContentCodingError(f"{url}: body does not decode as Content-Encoding {coding!r}: {exc}") from exc
    raise ContentCodingError(f"{url}: unsupported Content-Encoding {coding!r}")


def decode(url: str, content_encoding: str | None, body: bytes) -> bytes:
    """Return `body` with the codings `content_encoding` names undone.

    No header, an empty one or `identity` returns the body unchanged. A list
    (`gzip, deflate`) names the codings in the order they were applied, so
    they are undone last first."""
    if content_encoding is None:
        return body
    codings = [c.strip().lower() for c in content_encoding.split(",")]
    for coding in reversed(codings):
        if coding in ("", "identity"):
            continue
        body = _undo(url, coding, body)
    return body
