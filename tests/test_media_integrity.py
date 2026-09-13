"""Tests for audio file integrity verification, duplicate handling, and Vorbis comments."""

import subprocess
from pathlib import Path
import pytest

from zoink.config import Config
from zoink.downloader import DownloadManager, DownloadJob, DownloadState
from zoink.metadata import verify_audio_file, embed_metadata, read_metadata
from zoink.provider import TrackResult


@pytest.fixture(scope="module")
def sample_mp3(tmp_path_factory):
    fn = tmp_path_factory.mktemp("audio") / "sine.mp3"
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-b:a", "128k", str(fn)]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return fn


@pytest.fixture(scope="module")
def sample_flac(tmp_path_factory):
    fn = tmp_path_factory.mktemp("audio") / "sine.flac"
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(fn)]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return fn


@pytest.fixture(scope="module")
def sample_opus(tmp_path_factory):
    fn = tmp_path_factory.mktemp("audio") / "sine.opus"
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "libopus", str(fn)]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return fn


def test_verify_audio_file_valid(sample_mp3, sample_flac, sample_opus):
    assert verify_audio_file(sample_mp3) is True
    assert verify_audio_file(sample_flac) is True
    assert verify_audio_file(sample_opus) is True


def test_verify_audio_file_corrupted(tmp_path):
    # Non-existent file
    assert verify_audio_file(tmp_path / "missing.mp3") is False

    # Zero-byte file
    empty = tmp_path / "empty.mp3"
    empty.touch()
    assert verify_audio_file(empty) is False

    # Truncated garbage file
    garbage = tmp_path / "garbage.mp3"
    garbage.write_bytes(b"\xff\xfb\x90\x00" + b"random_corrupted_data_not_enough_to_decode")
    assert verify_audio_file(garbage) is False


def test_ogg_opus_artwork_base64_embedding(tmp_path, sample_opus):
    test_opus = tmp_path / "test_embedded.opus"
    test_opus.write_bytes(sample_opus.read_bytes())

    # Create dummy 200 byte valid JPEG
    jpeg_data = b"\xff\xd8\xff\xe0" + b"\x00" * 150 + b"\xff\xd9"
    track = TrackResult(
        id="opus1",
        title="Opus Test",
        artist="Opus Artist",
        album="Opus Album",
        year=2024,
        genre="Ambient",
    )
    # embed_metadata with artwork_data
    ok = embed_metadata(test_opus, track, artwork_data=jpeg_data)
    assert ok is True

    # Mutagen should open the file without crash and have vorbis metadata
    read_back = read_metadata(test_opus)
    assert read_back is not None
    assert read_back.title == "Opus Test"
    assert read_back.artist == "Opus Artist"
    assert read_back.album == "Opus Album"


def test_duplicate_handling_modes(tmp_path, sample_mp3):
    music_dir = tmp_path / "music"
    music_dir.mkdir()

    cfg = Config.get()
    cfg["download_dir"] = str(music_dir)
    cfg["output_format"] = "mp3"

    # Pre-populate existing track
    existing_file = music_dir / "Existing Artist" / "Existing Album" / "01 - Existing Song.mp3"
    existing_file.parent.mkdir(parents=True, exist_ok=True)
    existing_file.write_bytes(sample_mp3.read_bytes())

    tr = TrackResult(
        id="ex1",
        title="Existing Song",
        artist="Existing Artist",
        album="Existing Album",
        track_number=1,
    )

    # 1. Mode 'skip'
    cfg["duplicate_handling"] = "skip"
    dl_skip = DownloadManager(cfg)
    job_skip = dl_skip.download(tr)
    assert job_skip.state == DownloadState.DONE
    assert job_skip.filepath == str(existing_file)

    # 2. Mode 'rename'
    cfg["duplicate_handling"] = "rename"
    dl_rename = DownloadManager(cfg)
    resolved_path = dl_rename.resolve_target_path(tr)
    assert "(1)" in resolved_path.name
