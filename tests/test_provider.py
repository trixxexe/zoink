"""Tests for provider abstraction."""

from zoink.provider import TrackResult, AlbumResult, MediaStream, SearchProvider


def test_track_result_creation():
    t = TrackResult(id="abc", title="My Song", artist="Artist", duration=180)
    assert t.id == "abc"
    assert t.title == "My Song"
    assert t.artist == "Artist"
    assert t.duration == 180
    assert t.duration_str == "3:00"


def test_album_result_creation():
    a = AlbumResult(id="alb1", title="My Album", artist="Artist", year=2024)
    assert a.id == "alb1"
    assert a.tracks == []


def test_media_stream_creation():
    m = MediaStream(url="http://example.com/audio.mp3", ext="mp3", audio_bitrate=320)
    assert m.url == "http://example.com/audio.mp3"
    assert m.ext == "mp3"
    assert m.audio_bitrate == 320
    assert m.is_video is False


def test_search_provider_is_abstract():
    import abc
    assert isinstance(SearchProvider, abc.ABCMeta)


def test_track_result_optional_fields():
    t = TrackResult(id="x", title="Y")
    assert t.album_artist == ""
    assert t.track_number == 0
    assert t.disc_number == 0
    assert t.artwork_url == ""
    assert t.url == ""
