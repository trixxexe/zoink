"""Tests for web API, range streaming, path traversal security, and bulk downloads."""

import io
import os
import tempfile
import zipfile
from pathlib import Path
import pytest

from zoink.config import Config
from zoink.library import Library
from zoink.provider import TrackResult
from zoink.web import create_app, _resolve_safe_path, _parse_range_header


@pytest.fixture
def test_env(tmp_path):
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    config = Config.get()
    config["download_dir"] = str(music_dir)
    lib = Library(config)
    app = create_app(config, library=lib)
    app.config["TESTING"] = True
    client = app.test_client()
    return config, lib, client, music_dir


def test_index_serves_html(test_env):
    _, _, client, _ = test_env
    res = client.get("/")
    assert res.status_code == 200
    assert "ZoinK" in res.text
    assert "made by Ritam/Trixx" in res.text


def test_path_traversal_prevention(test_env):
    config, _, client, music_dir = test_env
    # Create a secret file outside music_dir
    secret_dir = music_dir.parent / "secret"
    secret_dir.mkdir()
    secret_file = secret_dir / "passwords.txt"
    secret_file.write_text("secret_data")

    # Direct helper test
    resolved = _resolve_safe_path(music_dir, "../secret/passwords.txt")
    assert resolved is None

    resolved_abs = _resolve_safe_path(music_dir, str(secret_file))
    assert resolved_abs is None

    # Via API endpoint
    res = client.get("/api/stream/..%2Fsecret%2Fpasswords.txt")
    assert res.status_code in (400, 403, 404)


def test_stream_range_requests(test_env):
    _, lib, client, music_dir = test_env
    test_file = music_dir / "sample.mp3"
    content = b"0123456789ABCDEF" * 64  # 1024 bytes
    test_file.write_bytes(content)

    tr = TrackResult(id="test1", title="Sample", artist="Tester", duration=60)
    lib.add_track(test_file, tr)

    # Full content without Range header
    res = client.get("/api/stream/sample.mp3")
    assert res.status_code == 200
    assert res.data == content
    assert res.headers.get("Accept-Ranges") == "bytes"

    # Partial range: bytes=0-9
    res_range = client.get("/api/stream/sample.mp3", headers={"Range": "bytes=0-9"})
    assert res_range.status_code == 206
    assert res_range.data == content[:10]
    assert "bytes 0-9/1024" in res_range.headers.get("Content-Range", "")

    # Open-ended range: bytes=1000-
    res_range2 = client.get("/api/stream/sample.mp3", headers={"Range": "bytes=1000-"})
    assert res_range2.status_code == 206
    assert res_range2.data == content[1000:]
    assert "bytes 1000-1023/1024" in res_range2.headers.get("Content-Range", "")


def test_parse_range_header():
    assert _parse_range_header("bytes=0-499", 1000) == (0, 499)
    assert _parse_range_header("bytes=500-", 1000) == (500, 999)
    assert _parse_range_header("bytes=-500", 1000) == (500, 999)
    assert _parse_range_header("bytes=1500-2000", 1000) is None
    assert _parse_range_header("invalid", 1000) is None


def test_bulk_download_all_zip(test_env):
    _, lib, client, music_dir = test_env
    f1 = music_dir / "song1.mp3"
    f1.write_bytes(b"song1_content")
    f2 = music_dir / "song2.mp3"
    f2.write_bytes(b"song2_content")

    lib.add_track(f1, TrackResult(id="s1", title="Song 1", artist="Artist"))
    lib.add_track(f2, TrackResult(id="s2", title="Song 2", artist="Artist"))

    res = client.get("/api/download-all")
    assert res.status_code == 200
    assert res.headers["Content-Type"] == "application/zip"

    # Verify returned bytes form a valid zip file
    zf = zipfile.ZipFile(io.BytesIO(res.data))
    names = zf.namelist()
    assert any("Song 1" in n for n in names)
    assert any("Song 2" in n for n in names)


def test_bulk_select_zip(test_env):
    _, lib, client, music_dir = test_env
    f1 = music_dir / "songA.mp3"
    f1.write_bytes(b"content_a")
    lib.add_track(f1, TrackResult(id="sa", title="Song A", artist="Artist"))

    res = client.post("/api/download-bulk-zip", json={"track_ids": ["sa"]})
    assert res.status_code == 200
    assert res.headers["Content-Type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(res.data))
    assert len(zf.namelist()) == 1


def test_api_tracks_and_search(test_env):
    _, lib, client, music_dir = test_env
    f1 = music_dir / "test.mp3"
    f1.write_bytes(b"data")
    lib.add_track(f1, TrackResult(id="t1", title="Blinding Lights", artist="The Weeknd", album="After Hours"))

    # /api/tracks
    res = client.get("/api/tracks")
    assert res.status_code == 200
    data = res.get_json()
    assert len(data) == 1
    assert data[0]["title"] == "Blinding Lights"

    # /api/artists
    res_art = client.get("/api/artists")
    assert res_art.status_code == 200
    assert any(a["artist"] == "The Weeknd" for a in res_art.get_json())

    # /api/albums
    res_alb = client.get("/api/albums")
    assert res_alb.status_code == 200
    assert any(a["album"] == "After Hours" for a in res_alb.get_json())

    # /api/library?q=Lights (local library filter)
    res_lib_q = client.get("/api/library?q=Lights")
    assert res_lib_q.status_code == 200
    assert len(res_lib_q.get_json()) == 1

    # /api/search?q=Mocked with monkeypatch
    from unittest.mock import patch
    with patch("zoink.web.YouTubeProvider.search_tracks") as mock_search:
        mock_search.return_value = [TrackResult(id="mock1", title="Mock Song", artist="Mock Artist")]
        res_srch = client.get("/api/search?q=Mock")
        assert res_srch.status_code == 200
        assert len(res_srch.get_json()) == 1
        assert res_srch.get_json()[0]["title"] == "Mock Song"


def test_web_index_no_placeholder_data(test_env):
    _, _, client, _ = test_env
    res = client.get("/")
    assert res.status_code == 200
    # Must NOT have hardcoded mock songs
    assert "Midnight City" not in res.text
    assert "Instant Crush" not in res.text
    assert "Get Lucky" not in res.text
    assert "Nightcall" not in res.text
    assert "Resonance" not in res.text
    # Must have real audio engine
    assert 'audio id="audio-player"' in res.text
    assert "api/stream" in res.text
    assert "api/artwork" in res.text
    assert "api/lyrics" in res.text


def test_web_stream_transcode_mp3(test_env):
    _, lib, client, music_dir = test_env
    test_file = music_dir / "sample_transcode.wav"
    # Create valid wave header or small file
    test_file.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
    lib.add_track(test_file, TrackResult(id="wav1", title="Sample WAV"))

    res = client.get("/api/stream/wav1?transcode=mp3")
    assert res.status_code == 200
    assert res.headers["Content-Type"] == "audio/mpeg"


def test_web_only_shows_zoink_tracks(test_env):
    _, lib, client, music_dir = test_env
    # 1. ZoinK track
    f_zoink = music_dir / "zoink.mp3"
    f_zoink.write_bytes(b"data")
    lib.add_track(f_zoink, TrackResult(id="z1", title="ZoinK Download", artist="Artist", source="youtube"))

    # 2. External local file
    f_ext = music_dir / "external.mp3"
    f_ext.write_bytes(b"data")
    lib.add_track(f_ext, TrackResult(id="e1", title="External File", artist="Artist", source="local"))

    res = client.get("/api/library")
    assert res.status_code == 200
    data = res.get_json()
    titles = [t["title"] for t in data]
    assert "ZoinK Download" in titles
    assert "External File" not in titles

    res_rec = client.get("/api/recent")
    assert res_rec.status_code == 200
    rec_titles = [t["title"] for t in res_rec.get_json()]
    assert "ZoinK Download" in rec_titles
    assert "External File" not in rec_titles


