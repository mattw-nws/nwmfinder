import io
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nwmfinder import _http
from nwmfinder.downloader import Downloader
from nwmfinder.exceptions import IncompleteDownloadError
from nwmfinder.finder import FileReference


class _FakeResponse:
    def __init__(self, data: bytes, status: int = 200):
        self._buf = io.BytesIO(data)
        self.status = status

    def read(self, n):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_head_factory(content_length: int):
    def fake_head(url, *, ssl_verify=True, timeout=None):
        return _http.HeadResult(status_code=200, content_length=content_length, accept_ranges=True, last_modified=None)
    return fake_head


def test_download_file_success(tmp_path, monkeypatch):
    data = b"x" * 1000

    monkeypatch.setattr(_http, "head", _fake_head_factory(len(data)))
    monkeypatch.setattr("nwmfinder.downloader.urlopen", lambda req, timeout=None, context=None: _FakeResponse(data))

    dl = Downloader(cache_dir=tmp_path)
    dest = dl.download_file("https://example.com/file.nc")

    assert dest.read_bytes() == data
    assert not (tmp_path / "file.nc.part").exists()


def test_download_file_size_mismatch_raises_after_retries(tmp_path, monkeypatch):
    # Server always claims a size larger than what we actually receive.
    monkeypatch.setattr(_http, "head", _fake_head_factory(2000))
    monkeypatch.setattr("nwmfinder.downloader.urlopen", lambda req, timeout=None, context=None: _FakeResponse(b"short"))

    dl = Downloader(cache_dir=tmp_path, max_retries=1, retry_backoff=0)

    with pytest.raises(IncompleteDownloadError):
        dl.download_file("https://example.com/file.nc")


def test_download_many_preserves_order(tmp_path, monkeypatch):
    data = b"abc"
    monkeypatch.setattr(_http, "head", _fake_head_factory(len(data)))
    monkeypatch.setattr("nwmfinder.downloader.urlopen", lambda req, timeout=None, context=None: _FakeResponse(data))

    dl = Downloader(cache_dir=tmp_path, max_workers=2)
    urls = [f"https://example.com/f{i}.nc" for i in range(4)]
    results = dl.download_many(urls)

    assert [r.url for r in results] == urls
    assert all(r.success for r in results)


def test_download_references_wraps_download_many(tmp_path, monkeypatch):
    data = b"abc"
    monkeypatch.setattr(_http, "head", _fake_head_factory(len(data)))
    monkeypatch.setattr("nwmfinder.downloader.urlopen", lambda req, timeout=None, context=None: _FakeResponse(data))

    init_time = datetime(2026, 9, 20, tzinfo=timezone.utc)
    files = [
        FileReference(url=f"https://example.com/f{i}.nc", init_time=init_time, valid_time=init_time, forecast_hour=i)
        for i in range(3)
    ]

    dl = Downloader(cache_dir=tmp_path, max_workers=2)
    results = dl.download_references(files)

    assert [r.url for r in results] == [f.url for f in files]
    assert all(r.success for r in results)
