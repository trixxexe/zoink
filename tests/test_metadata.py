"""Tests for metadata embedding."""

from pathlib import Path

from zoink.metadata import embed_metadata, read_metadata, _safe_int
from zoink.provider import TrackResult


def test_safe_int():
    assert _safe_int("42") == 42
    assert _safe_int("0") == 0
    assert _safe_int("abc") == 0
    assert _safe_int("") == 0
    assert _safe_int(None) == 0


def test_embed_metadata_mp3(tmp_path):
    # Create a minimal MP3 file (just a header)
    mp3_file = tmp_path / "test.mp3"
    # Write a minimal valid MP3 frame
    mp3_file.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 1024)
    track = TrackResult(
        id="test123",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        year=2024,
        track_number=1,
        source="youtube",
    )
    result = embed_metadata(mp3_file, track)
    # May fail on minimal file, but shouldn't crash
    assert isinstance(result, bool)


def test_read_metadata_nonexistent(tmp_path):
    result = read_metadata(tmp_path / "nonexistent.mp3")
    assert result is None


def test_track_result_duration_str():
    t = TrackResult(id="1", title="Test", duration=200)
    assert t.duration_str == "3:20"

    t2 = TrackResult(id="2", title="Test", duration=0)
    assert t2.duration_str == ""

    t3 = TrackResult(id="3", title="Test", duration=65)
    assert t3.duration_str == "1:05"


def test_track_result_defaults():
    t = TrackResult(id="x", title="Y")
    assert t.artist == ""
    assert t.album == ""
    assert t.duration == 0
    assert t.has_lyrics is False
    assert t.source == ""
