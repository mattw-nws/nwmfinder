"""Concurrent, resumable downloading with post-download size verification.

Handles the common failure mode where a NetCDF file begins downloading before
the source has finished writing it, producing a truncated/corrupt file: after
each download, a follow-up HEAD request compares Content-Length against the
bytes actually written, resuming (via HTTP Range) or re-downloading as needed.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import _http
from .exceptions import IncompleteDownloadError
from .finder import FileReference

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def _url_filename(url: str) -> Path:
    """Derive a filesystem-safe relative Path from the last path segment of a URL."""
    return Path(Path(urlparse(url).path).name)


@dataclass
class DownloadResult:
    url: str
    path: Path | None
    success: bool
    error: str | None = None


class Downloader:
    """Downloads NWM data files to a cache directory, with resume/verification."""

    def __init__(
        self,
        cache_dir: Path | str,
        *,
        max_workers: int = 4,
        max_retries: int = 3,
        retry_backoff: float = 5.0,
        ssl_verify: bool = True,
    ):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._max_workers = max_workers
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._ssl_verify = ssl_verify

    def download_file(self, url: str, dest_path: Path | None = None) -> Path:
        """Download a single file, returning the final local path.

        Raises :class:`IncompleteDownloadError` if the file's size could not
        be verified against the server after all retries are exhausted.
        """
        dest = dest_path if dest_path is not None else self._cache_dir / _url_filename(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")

        attempts = self._max_retries + 1
        backoff = self._retry_backoff
        for attempt in range(attempts):
            expected_size = _http.head(url, ssl_verify=self._ssl_verify).content_length
            self._fetch(url, tmp, expected_size)

            verify = _http.head(url, ssl_verify=self._ssl_verify)
            actual_size = tmp.stat().st_size if tmp.exists() else 0
            if verify.content_length is None:
                logger.debug("Server did not report Content-Length for %s; skipping size verification.", url)
                tmp.replace(dest)
                return dest
            if actual_size == verify.content_length:
                tmp.replace(dest)
                return dest

            logger.warning(
                "Size mismatch for %s: got %d bytes, server reports %d (attempt %d/%d)",
                url, actual_size, verify.content_length, attempt + 1, attempts,
            )
            if attempt + 1 < attempts:
                time.sleep(backoff)
                backoff *= 2

        tmp.unlink(missing_ok=True)
        raise IncompleteDownloadError(f"Repeated size mismatches downloading {url}; giving up.")

    def download_many(self, urls: list[str], dest_dir: Path | str | None = None) -> list[DownloadResult]:
        """Download several files concurrently, preserving input order in the result."""
        target_dir = Path(dest_dir) if dest_dir is not None else self._cache_dir

        def _do(url: str) -> DownloadResult:
            try:
                path = self.download_file(url, target_dir / _url_filename(url))
                return DownloadResult(url=url, path=path, success=True)
            except Exception as e:
                logger.error("Failed to download %s: %s", url, e)
                return DownloadResult(url=url, path=None, success=False, error=str(e))

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            return list(executor.map(_do, urls))

    def download_references(self, files: list[FileReference], dest_dir: Path | str | None = None) -> list[DownloadResult]:
        """Convenience wrapper around download_many() for a list of FileReference (e.g. Cycle.files)."""
        return self.download_many([f.url for f in files], dest_dir)

    def _fetch(self, url: str, tmp: Path, expected_size: int | None) -> None:
        """Stream `url` into `tmp`, resuming from the existing partial file if possible."""
        existing_size = tmp.stat().st_size if tmp.exists() else 0
        if expected_size is not None and existing_size == expected_size:
            return  # Already have the whole file from a previous attempt.

        req = Request(url=url)
        mode = "wb"
        if existing_size > 0:
            req.add_header("Range", f"bytes={existing_size}-")
            mode = "ab"

        context = _http.ssl_context_for(self._ssl_verify)
        try:
            with urlopen(req, timeout=_http.DEFAULT_TIMEOUT, context=context) as response:
                if mode == "ab" and response.status != 206:
                    # Server ignored the Range request; restart from scratch.
                    mode = "wb"
                    existing_size = 0
                with open(tmp, mode) as f:
                    while chunk := response.read(_CHUNK_SIZE):
                        f.write(chunk)
        except HTTPError as e:
            if e.code == 416 and expected_size is not None:
                # Range not satisfiable--our partial file is already complete or corrupt; restart.
                tmp.unlink(missing_ok=True)
                self._fetch(url, tmp, expected_size)
                return
            raise
        except URLError as e:
            raise ConnectionError(f"Failed to reach {url}: {e.reason}") from e
