"""Tests for library module."""

from pathlib import Path

from zoink.config import Config
from zoink.library import Library
from zoink.provider import TrackResult


def test_library_init(tmp_path):
    config = Config()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)
    assert lib.count() == 0


def test_library_add_and_get(tmp_path):
    config = Config()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)
    track = TrackResult(
        id="test1",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        duration=180,
        year=2024,
        source="youtube",
    )
    # Create a dummy file
    fp = tmp_path / "test.mp3"
    fp.write_bytes(b"\xff" * 100)
    result = lib.add_track(fp, track)
    assert result is True
    assert lib.count() == 1


def test_library_search(tmp_path):
    config = Config()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)
    track = TrackResult(id="s1", title="Blinding Lights", artist="The Weeknd", source="youtube")
    fp = tmp_path / "blinding.mp3"
    fp.write_bytes(b"\xff" * 100)
    lib.add_track(fp, track)

    results = lib.search("Blinding")
    assert len(results) == 1
    assert results[0]["title"] == "Blinding Lights"

    results = lib.search("Weeknd")
    assert len(results) == 1

    results = lib.search("nonexistent")
    assert len(results) == 0


def test_library_get_all(tmp_path):
    config = Config()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)
    for i in range(5):
        track = TrackResult(id=f"t{i}", title=f"Song {i}", source="test")
        fp = tmp_path / f"song{i}.mp3"
        fp.write_bytes(b"\xff" * 100)
        lib.add_track(fp, track)
    assert lib.count() == 5
    all_tracks = lib.get_all()
    assert len(all_tracks) == 5


def test_library_remove(tmp_path):
    config = Config()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)
    track = TrackResult(id="rm1", title="Remove Me", source="test")
    fp = tmp_path / "remove.mp3"
    fp.write_bytes(b"\xff" * 100)
    lib.add_track(fp, track)
    assert lib.count() == 1
    lib.remove_track("rm1")
    assert lib.count() == 0


def test_library_get_artists(tmp_path):
    config = Config()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)
    for i, artist in enumerate(["A", "B", "A"]):
        track = TrackResult(id=f"a{i}", title=f"Song {i}", artist=artist, source="test")
        fp = tmp_path / f"track{i}.mp3"
        fp.write_bytes(b"\xff" * 100)
        lib.add_track(fp, track)
    artists = lib.get_artists()
    assert len(artists) == 2


def test_library_get_albums(tmp_path):
    config = Config()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)
    for i, album in enumerate(["Alb1", "Alb2", "Alb1"]):
        track = TrackResult(id=f"alb{i}", title=f"Song {i}", album=album, artist="X", source="test")
        fp = tmp_path / f"album{i}.mp3"
        fp.write_bytes(b"\xff" * 100)
        lib.add_track(fp, track)
    albums = lib.get_albums()
    assert len(albums) == 2


def test_library_get_track_by_id(tmp_path):
    config = Config()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)
    track = TrackResult(id="findme", title="Find Me", source="test")
    fp = tmp_path / "find.mp3"
    fp.write_bytes(b"\xff" * 100)
    lib.add_track(fp, track)
    result = lib.get_track_by_id("findme")
    assert result is not None
    assert result["title"] == "Find Me"
    assert lib.get_track_by_id("nonexistent") is None


def test_library_scan_filters_non_zoink_files(tmp_path, monkeypatch):
    config = Config()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)

    # File 1: ZoinK download
    f_zoink = tmp_path / "zoink_song.mp3"
    f_zoink.write_bytes(b"ID3" + b"\x00" * 200)

    # File 2: External audio file placed in folder
    f_ext = tmp_path / "external_song.mp3"
    f_ext.write_bytes(b"ID3" + b"\x00" * 200)

    def mock_read_metadata(p: Path):
        if p.name == "zoink_song.mp3":
            return TrackResult(id="z1", title="ZoinK Track", artist="Artist", source="youtube")
        return TrackResult(id="ext1", title="External Track", artist="Artist", source="local")

    monkeypatch.setattr("zoink.library.read_metadata", mock_read_metadata)

    scanned = lib.scan_directory(prune=True, only_zoink=True)
    assert scanned == 1
    assert lib.count() == 1

    tracks = lib.get_all()
    assert len(tracks) == 1
    assert tracks[0]["title"] == "ZoinK Track"


def test_library_reopen_persistence(tmp_path):
    config = Config()
    config["download_dir"] = str(tmp_path)

    # Session 1: Download track and store in library
    lib1 = Library(config)
    f = tmp_path / "song.mp3"
    f.write_bytes(b"audio data")
    t = TrackResult(id="s1", title="Persisted Song", artist="Artist", source="youtube")
    lib1.add_track(f, t)
    assert lib1.count() == 1

    # Session 2: Close and re-open (new Library instance)
    lib2 = Library(config)
    assert lib2.count() == 1
    tracks = lib2.get_all()
    assert len(tracks) == 1
    assert tracks[0]["title"] == "Persisted Song"

    # Rescan should retain the track
    lib2.scan_directory(prune=True)
    assert lib2.count() == 1

