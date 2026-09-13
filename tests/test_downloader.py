"""Tests for download manager."""

import os
from pathlib import Path

from zoink.config import Config
from zoink.downloader import DownloadManager, DownloadJob, DownloadState, _sanitize, _build_path
from zoink.provider import TrackResult


def test_sanitize():
    assert _sanitize("Hello World") == "Hello World"
    assert _sanitize('Bad/Name"') == "Bad_Name"
    assert _sanitize("") == "Unknown"
    assert _sanitize("a" * 250)[:200] == "a" * 200


def test_build_path_basic():
    track = TrackResult(
        id="abc",
        title="My Song",
        artist="Artist",
        album="Album",
        track_number=1,
        year=2024,
    )
    path = _build_path(
        "{artist}/{album}/{track} - {title}.{ext}",
        track,
        "mp3",
        Path("/music"),
    )
    assert "Artist" in path
    assert "Album" in path
    assert "01 - My Song.mp3" in path
    assert path.startswith("/music/")


def test_build_path_defaults():
    track = TrackResult(id="x", title="Song")
    path = _build_path("{title}.{ext}", track, "flac", Path("/dl"))
    assert "Song.flac" in path


def test_download_state_values():
    assert DownloadState.PENDING.value == "pending"
    assert DownloadState.DONE.value == "done"
    assert DownloadState.FAILED.value == "failed"


def test_download_job_defaults():
    track = TrackResult(id="x", title="Y")
    job = DownloadJob(track=track)
    assert job.state == DownloadState.PENDING
    assert job.progress == 0.0
    assert job.filepath is None
    assert job.error is None


def test_download_manager_init(tmp_path):
    config = Config()
    config["download_dir"] = str(tmp_path)
    dm = DownloadManager(config)
    assert dm.config is config


def test_cancel():
    config = Config()
    dm = DownloadManager(config)
    assert dm._cancelled is False
    dm.cancel_all()
    assert dm._cancelled is True


def test_download_resets_cancelled(tmp_path, monkeypatch):
    config = Config()
    config["download_dir"] = str(tmp_path)
    dm = DownloadManager(config)
    dm.cancel_all()
    assert dm._cancelled is True

    # When starting a new download, _cancelled should be reset to False
    track = TrackResult(id="test_id", title="Test Song", artist="Artist", url="https://example.com/audio")
    # Mock yt-dlp to avoid network requests
    import yt_dlp
    class DummyYDL:
        def __init__(self, opts=None, *args, **kwargs):
            self.opts = opts or {}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def download(self, urls):
            outtmpl = self.opts.get("outtmpl", "")
            if outtmpl:
                target = Path(str(outtmpl).replace(".%(ext)s", ".mp3"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"dummy")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", DummyYDL)
    monkeypatch.setattr("zoink.downloader.verify_audio_file", lambda p: True)

    job = dm.download(track)
    assert dm._cancelled is False
    assert job.state == DownloadState.DONE


def test_provider_resolution_error_handled(tmp_path, monkeypatch):
    config = Config()
    config["download_dir"] = str(tmp_path)
    dm = DownloadManager(config)

    track = TrackResult(id="bad_id", title="Broken Track", artist="Artist", url="")

    class MockFailingProvider:
        def resolve_track(self, tid):
            raise RuntimeError("Provider connection timeout")

    monkeypatch.setattr("zoink.providers.YouTubeProvider", MockFailingProvider)

    job = dm.download(track)
    assert job.state == DownloadState.FAILED
    assert "Provider resolution failed" in (job.error or "")

