"""Comprehensive regression test suite for ZoinK.

Covers:
- TUI shutdown lifecycle, safe exit, and input handling post-shutdown
- Termux media playback isolation (no subprocess hang when inactive)
- Background worker cancellation and notify safety
- Downloader multi-stage progress reporting and atomic cleanup
- In-memory caching for artwork and lyrics
- SQLite connection management and batch scanning
- M4A empty tag edge cases and container integrity verification
- Web safe path traversal prevention, RFC 6266 headers, and ZIP handling
"""

import hashlib
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zoink.artwork import fetch_artwork, _ARTWORK_CACHE
from zoink.config import Config
from zoink.downloader import DownloadJob, DownloadManager, DownloadState
from zoink.library import Library
from zoink.lyrics import fetch_lyrics, _LYRICS_CACHE
from zoink.metadata import _read_m4a, verify_audio_file
from zoink.provider import TrackResult
from zoink.tui.app import TUIPhase, ZoinKTUI
from zoink.web import _resolve_safe_path, _stream_file, _stream_zip_archive, app


# ---------------------------------------------------------------------------
# TUI Lifecycle & Shutdown Tests
# ---------------------------------------------------------------------------


def test_tui_shutdown_idempotent(tmp_path):
    config = Config.get()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)
    tui = ZoinKTUI(config=config, library=lib)

    assert not tui._is_shutting_down
    assert not tui.should_exit

    # First shutdown call
    tui.shutdown()
    assert tui._is_shutting_down
    assert tui.should_exit
    assert tui.is_cancelled

    # Second shutdown call must be safe and idempotent
    tui.shutdown()
    assert tui._is_shutting_down


def test_tui_notify_after_shutdown(tmp_path):
    config = Config.get()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)
    tui = ZoinKTUI(config=config, library=lib)

    refresh_called = []
    tui.on_refresh = lambda: refresh_called.append(True)

    # Before shutdown, notify triggers callback
    tui.notify()
    assert len(refresh_called) == 1

    # After shutdown, notify must be an immediate no-op
    tui.shutdown()
    tui.notify()
    assert len(refresh_called) == 1  # Not incremented


def test_tui_handle_enter_after_shutdown(tmp_path):
    config = Config.get()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)
    tui = ZoinKTUI(config=config, library=lib)

    tui.input_text = "test query"
    tui.shutdown()

    # Enter keypress post-shutdown must not trigger search or throw
    tui.handle_enter()
    assert tui.phase == TUIPhase.INPUT  # Did not transition to SEARCHING


def test_tui_stop_audio_no_termux_hang(tmp_path):
    config = Config.get()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)
    tui = ZoinKTUI(config=config, library=lib)

    with patch("subprocess.run") as mock_run:
        tui.stop_audio()
        # Must not call termux-media-player when _playing_with_termux is False
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Downloader Progress Stages & Cancellation
# ---------------------------------------------------------------------------


def test_downloader_progress_stages(tmp_path, monkeypatch):
    config = Config()
    config["download_dir"] = str(tmp_path)
    dm = DownloadManager(config)

    track = TrackResult(
        id="stage_track",
        title="Stage Test",
        artist="Tester",
        url="https://example.com/stream",
    )

    import yt_dlp

    class DummyYDL:
        def __init__(self, opts=None, *args, **kwargs):
            self.opts = opts or {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def download(self, urls):
            hooks = self.opts.get("progress_hooks", [])
            for h in hooks:
                h({"status": "downloading", "downloaded_bytes": 500, "total_bytes": 1000})
                h({"status": "finished"})
            outtmpl = self.opts.get("outtmpl", "")
            if outtmpl:
                target = Path(str(outtmpl).replace(".%(ext)s", ".mp3"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"ID3" + b"\x00" * 4096)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", DummyYDL)
    monkeypatch.setattr("zoink.downloader.verify_audio_file", lambda p: True)
    monkeypatch.setattr("zoink.downloader.fetch_artwork", lambda *a, **k: None)
    monkeypatch.setattr("zoink.downloader.fetch_lyrics", lambda *a, **k: None)

    recorded_progress = []

    def on_progress(job):
        recorded_progress.append((job.state, job.progress))

    job = dm.download(track, on_progress=on_progress)
    assert job.state == DownloadState.DONE
    assert job.progress == 100.0

    # Ensure progress went through intermediate stages
    states = [s for s, _ in recorded_progress]
    assert DownloadState.DOWNLOADING in states
    assert DownloadState.VERIFYING in states
    assert DownloadState.METADATA in states
    assert DownloadState.FINALIZING in states
    assert DownloadState.DONE in states


def test_downloader_cancellation_during_stages(tmp_path, monkeypatch):
    config = Config()
    config["download_dir"] = str(tmp_path)
    dm = DownloadManager(config)

    track = TrackResult(
        id="cancel_track",
        title="Cancel Test",
        artist="Tester",
        url="https://example.com/stream",
    )

    import yt_dlp

    class DummyYDL:
        def __init__(self, opts=None, *args, **kwargs):
            self.opts = opts or {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def download(self, urls):
            # Cancel job mid-download
            dm.cancel_job("cancel_track")
            outtmpl = self.opts.get("outtmpl", "")
            if outtmpl:
                target = Path(str(outtmpl).replace(".%(ext)s", ".mp3"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"ID3" + b"\x00" * 4096)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", DummyYDL)
    monkeypatch.setattr("zoink.downloader.verify_audio_file", lambda p: True)
    monkeypatch.setattr("zoink.downloader.fetch_artwork", lambda *a, **k: None)
    monkeypatch.setattr("zoink.downloader.fetch_lyrics", lambda *a, **k: None)

    job = dm.download(track)
    assert job.state == DownloadState.CANCELLED


# ---------------------------------------------------------------------------
# Caching Tests (Artwork & Lyrics)
# ---------------------------------------------------------------------------


def test_artwork_cache():
    url = "https://example.com/artwork/cover.jpg"
    _ARTWORK_CACHE[url] = b"\xff\xd8\xff\xe0" + b"\x00" * 100

    # Must return from cache without network call
    result = fetch_artwork(url)
    assert result == _ARTWORK_CACHE[url]


def test_lyrics_cache():
    key = "::coldplay::yellow"
    _LYRICS_CACHE[key] = "Look at the stars"

    # Must return from cache without network call
    result = fetch_lyrics(title="Yellow", artist="Coldplay")
    assert result == "Look at the stars"


# ---------------------------------------------------------------------------
# SQLite Library & Batch Scanning Tests
# ---------------------------------------------------------------------------


def test_library_generate_track_id_closes_connection(tmp_path):
    config = Config()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)

    test_file = tmp_path / "song.mp3"
    test_file.write_bytes(b"test")

    # Generate track id with a raw_id that triggers database query
    tid = lib._generate_track_id(test_file, raw_id="custom_track_123")
    assert tid == "custom_track_123"

    # Verify no open connection leak by performing subsequent DB operation
    assert lib.count() == 0


def test_library_scan_directory_batch(tmp_path, monkeypatch):
    config = Config()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)

    # Create dummy audio files
    for i in range(5):
        f = tmp_path / f"track_{i}.mp3"
        f.write_bytes(b"ID3" + b"\x00" * 2048)

    # Mock read_metadata to avoid reading dummy bytes
    monkeypatch.setattr(
        "zoink.library.read_metadata",
        lambda p: TrackResult(id=p.stem, title=p.stem, artist="Artist"),
    )

    indexed = lib.scan_directory()
    assert indexed == 5
    assert lib.count() == 5

    # Incremental scan with no changes should index 0 new files
    indexed_again = lib.scan_directory()
    assert indexed_again == 0


# ---------------------------------------------------------------------------
# Metadata Edge Cases & Audio Verification Tests
# ---------------------------------------------------------------------------


def test_metadata_m4a_empty_lists(tmp_path, monkeypatch):
    test_m4a = tmp_path / "empty_tags.m4a"
    test_m4a.write_bytes(b"\x00" * 100)

    class MockMP4:
        def __init__(self, path):
            self.tags = {
                "\xa9nam": [],
                "\xa9ART": [],
                "\xa9alb": [],
                "trkn": [],
                "disk": [],
                "covr": [],
            }
            self.info = MagicMock(length=120)

    monkeypatch.setattr("zoink.metadata.MP4", MockMP4)

    # Must not raise IndexError
    res = _read_m4a(test_m4a)
    assert res is not None
    assert res.title == "empty_tags"
    assert res.track_number == 0
    assert res.disc_number == 0
    assert not res.artwork_url


def test_verify_audio_file_heuristics(tmp_path):
    # File < 2KB returns False
    tiny = tmp_path / "tiny.mp3"
    tiny.write_bytes(b"small")
    assert not verify_audio_file(tiny)

    # Non-audio file > 8KB returns False
    html_error = tmp_path / "error.html"
    html_error.write_bytes(b"<html><head><title>Error</title></head></html>" * 200)
    assert not verify_audio_file(html_error)

    # MP3 with ID3 header
    mp3 = tmp_path / "valid.mp3"
    mp3.write_bytes(b"ID3\x03\x00\x00\x00" + b"\x00" * 4096)
    assert verify_audio_file(mp3)

    # FLAC with fLaC header
    flac = tmp_path / "valid.flac"
    flac.write_bytes(b"fLaC" + b"\x00" * 4096)
    assert verify_audio_file(flac)

    # OGG with OggS header
    ogg = tmp_path / "valid.ogg"
    ogg.write_bytes(b"OggS" + b"\x00" * 4096)
    assert verify_audio_file(ogg)

    # M4A with ftyp header
    m4a = tmp_path / "valid.m4a"
    m4a.write_bytes(b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 4096)
    assert verify_audio_file(m4a)


# ---------------------------------------------------------------------------
# Web API Security & Range Streaming Tests
# ---------------------------------------------------------------------------


def test_web_safe_path_traversal_guards(tmp_path):
    base_dir = tmp_path / "music"
    base_dir.mkdir()

    secret = tmp_path / "secret.txt"
    secret.write_text("classified")

    song = base_dir / "song.mp3"
    song.write_bytes(b"audio")

    # Legitimate relative path resolves
    assert _resolve_safe_path("song.mp3", base_dir) == song

    # Traversal attempts must be rejected
    assert _resolve_safe_path("../secret.txt", base_dir) is None
    assert _resolve_safe_path("/etc/passwd", base_dir) is None
    assert _resolve_safe_path("/secret.txt", base_dir) is None
    assert _resolve_safe_path("..\\secret.txt", base_dir) is None
    assert _resolve_safe_path("\x00song.mp3", base_dir) is None


def test_web_stream_zip_archive_empty_guard(tmp_path):
    # Non-existent files must return 404
    missing_file = tmp_path / "ghost.mp3"
    resp = _stream_zip_archive([(missing_file, "ghost.mp3")], "ghost.zip")
    assert resp.status_code == 404

    # Empty list must return 404
    resp2 = _stream_zip_archive([], "empty.zip")
    assert resp2.status_code == 404


def test_web_stream_file_rfc6266_headers(tmp_path):
    audio = tmp_path / "テスト曲 - Test.mp3"
    audio.write_bytes(b"ID3" + b"\x00" * 4096)

    with app.test_request_context():
        resp = _stream_file(audio, "audio/mpeg", as_attachment=True)
        cd = resp.headers.get("Content-Disposition", "")
        assert 'attachment; filename=' in cd
        assert "filename*=UTF-8''" in cd
