"""Small stdlib-only HTTP helpers shared by :mod:`nwmfinder.finder` and
:mod:`nwmfinder.downloader`.

Deliberately avoids the ``requests`` library; everything here is built on
``urllib`` and ``ssl`` from the standard library.
"""
from __future__ import annotations

import ssl
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT = 30  # seconds


@dataclass(frozen=True)
class HeadResult:
    status_code: int
    content_length: int | None
    accept_ranges: bool
    last_modified: str | None


_UNVERIFIED_CONTEXT = ssl._create_unverified_context()


def ssl_context_for(verify: bool) -> ssl.SSLContext | None:
    """Return an SSL context suitable for passing to urlopen, or None for defaults."""
    return None if verify else _UNVERIFIED_CONTEXT


def head(url: str, *, ssl_verify: bool = True, timeout: float = DEFAULT_TIMEOUT) -> HeadResult:
    """Issue a HEAD request, returning a normalized result (never raises on non-2xx)."""
    req = Request(url=url, method="HEAD")
    context = ssl_context_for(ssl_verify)
    try:
        with urlopen(req, timeout=timeout, context=context) as response:
            return _head_result_from_response(response.status, response.headers)
    except HTTPError as e:
        return _head_result_from_response(e.code, e.headers)
    except URLError as e:
        raise ConnectionError(f"Failed to reach {url}: {e.reason}") from e


def _head_result_from_response(status_code: int, headers) -> HeadResult:
    content_length = headers.get("Content-Length") if headers else None
    return HeadResult(
        status_code=status_code,
        content_length=int(content_length) if content_length is not None else None,
        accept_ranges=(headers.get("Accept-Ranges", "").lower() == "bytes") if headers else False,
        last_modified=headers.get("Last-Modified") if headers else None,
    )
