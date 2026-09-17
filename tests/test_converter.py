"""Tests for audio converter module, FFmpeg transcoding, web API, and CLI."""

import subprocess
from pathlib import Path
import pytest

from zoink.config import Config
from zoink.converter import (
    SUPPORTED_FORMATS,
    BITRATE_MAP,
    convert_audio_file,
    convert_library_track,
    is_ffmpeg_available,
    run_ffmpeg_transcode,
)
from zoink.library import Library
from zoink.metadata import embed_metadata, read_metadata, verify_audio_file
from zoink.provider import TrackResult
from zoink.web import create_app


@pytest.fixture(scope="module")
def sample_sine_mp3(tmp_path_factory):
    fn = tmp_path_factory.mktemp("audio_convert") / "test_sine.mp3"
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=1",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        str(fn),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    # Embed metadata into source
    meta = TrackResult(
        id="track_orig",
        title="Sine Wave Test",
        artist="Audio Synth",
        album="Frequencies",
        year=2024,
        lyrics="Synthesizer test tone lyrics",
    )
    embed_metadata(fn, meta)
    return fn


def test_converter_supported_formats():
    assert "mp3" in SUPPORTED_FORMATS
    assert "flac" in SUPPORTED_FORMATS
    assert "m4a" in SUPPORTED_FORMATS
    assert "opus" in SUPPORTED_FORMATS
    assert "ogg" in SUPPORTED_FORMATS
    assert "wav" in SUPPORTED_FORMATS


def test_ffmpeg_available():
    assert is_ffmpeg_available() is True


def test_transcode_direct(tmp_path, sample_sine_mp3):
    out_flac = tmp_path / "out.flac"
    ok = run_ffmpeg_transcode(sample_sine_mp3, out_flac, "flac", quality="best")
    assert ok is True
    assert out_flac.exists()
    assert out_flac.stat().st_size > 0
    assert verify_audio_file(out_flac) is True

    out_opus = tmp_path / "out.opus"
    ok = run_ffmpeg_transcode(sample_sine_mp3, out_opus, "opus", quality="160")
    assert ok is True
    assert out_opus.exists()
    assert verify_audio_file(out_opus) is True


def test_convert_audio_file_preserves_metadata(tmp_path, sample_sine_mp3):
    src_copy = tmp_path / "song.mp3"
    src_copy.write_bytes(sample_sine_mp3.read_bytes())

    # Convert to FLAC keeping original
    progress_calls = []
    def on_prog(pct, msg):
        progress_calls.append((pct, msg))

    success, dest, err = convert_audio_file(
        source_path=src_copy,
        target_format="flac",
        quality="best",
        destination_dir=tmp_path,
        replace_original=False,
        on_progress=on_prog,
    )

    assert success is True
    assert err is None
    assert dest is not None
    assert dest.suffix.lower() == ".flac"
    assert dest.exists()
    assert src_copy.exists()  # Original kept
    assert len(progress_calls) > 0

    # Verify metadata carried over
    meta = read_metadata(dest)
    assert meta is not None
    assert meta.title == "Sine Wave Test"
    assert meta.artist == "Audio Synth"


def test_convert_library_track_with_replace(tmp_path, sample_sine_mp3):
    config = Config.get()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)

    src_file = tmp_path / "library_song.mp3"
    src_file.write_bytes(sample_sine_mp3.read_bytes())

    meta = TrackResult(id="lib_1", title="Original Library Track", artist="Original Artist")
    embed_metadata(src_file, meta)
    lib.add_track(src_file, meta)
    track_id = meta.id

    # Convert to M4A with replace_original=True
    success, dest, err = convert_library_track(
        library=lib,
        track_id_or_path=track_id,
        target_format="m4a",
        quality="256",
        replace_original=True,
    )

    assert success is True
    assert err is None
    assert dest is not None
    assert dest.suffix.lower() == ".m4a"
    assert dest.exists()
    assert not src_file.exists()  # Old MP3 was deleted

    # Database updated
    old_track = lib.get_track_by_path(str(src_file))
    assert old_track is None

    new_track = lib.get_track_by_path(str(dest))
    assert new_track is not None
    assert new_track["filepath"] == str(dest)


def test_web_api_convert_endpoints(tmp_path, sample_sine_mp3):
    music_dir = tmp_path / "web_music"
    music_dir.mkdir()
    config = Config.get()
    config["download_dir"] = str(music_dir)
    lib = Library(config)

    track_file = music_dir / "web_sample.mp3"
    track_file.write_bytes(sample_sine_mp3.read_bytes())
    t_meta = TrackResult(id="web_t1", title="Web Sample", artist="Artist")
    lib.add_track(track_file, t_meta)
    track_id = t_meta.id

    app = create_app(config, library=lib)
    app.config["TESTING"] = True
    client = app.test_client()

    # GET /api/convert/formats
    res = client.get("/api/convert/formats")
    assert res.status_code == 200
    data = res.get_json()
    assert "formats" in data
    assert "flac" in data["formats"]

    # POST /api/convert (invalid format)
    res_bad = client.post("/api/convert", json={"track_id": track_id, "format": "exe"})
    assert res_bad.status_code == 400

    # POST /api/convert (valid convert to flac)
    res_ok = client.post(
        "/api/convert",
        json={"track_id": track_id, "format": "flac", "replace_original": True},
    )
    assert res_ok.status_code == 200
    res_data = res_ok.get_json()
    assert res_data["status"] == "success"
    assert res_data["filepath"].endswith(".flac")
    assert Path(res_data["filepath"]).exists()


def test_cli_convert_command(tmp_path, sample_sine_mp3):
    from zoink.cli import main

    music_dir = tmp_path / "cli_music"
    music_dir.mkdir()
    config = Config.get()
    config["download_dir"] = str(music_dir)
    lib = Library(config)

    track_file = music_dir / "cli_sample.mp3"
    track_file.write_bytes(sample_sine_mp3.read_bytes())
    lib.add_track(track_file, TrackResult(id="cli_t1", title="CLI Song", artist="Artist"))

    # Execute CLI convert
    ret = main(["convert", str(track_file), "-f", "opus", "--quality", "160"])
    assert ret == 0
    expected_out = track_file.with_suffix(".opus")
    assert expected_out.exists()
