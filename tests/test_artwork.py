"""Tests for artwork downloading, resolution upgrading, and validation."""

from unittest.mock import MagicMock, patch
from zoink.artwork import (
    _get_url_candidates,
    _valid_image,
    _search_album_art,
    fetch_artwork,
)


def test_get_url_candidates_youtube():
    yt_url = "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    candidates = _get_url_candidates(yt_url)
    assert len(candidates) >= 3
    assert any("maxresdefault.jpg" in c for c in candidates)
    assert any("sddefault.jpg" in c for c in candidates)


def test_valid_image_formats():
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 120
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 120
    webp_bytes = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 120
    bad_bytes = b"NOT_AN_IMAGE"

    assert _valid_image(jpeg_bytes) is True
    assert _valid_image(png_bytes) is True
    assert _valid_image(webp_bytes) is True
    assert _valid_image(bad_bytes) is False


def test_search_album_art_itunes():
    with patch("zoink.artwork._SESSION.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/Music/100x100bb.jpg"
                }
            ]
        }
        mock_get.return_value = mock_resp

        upgraded = _search_album_art("Queen", "Bohemian Rhapsody")
        assert upgraded is not None
        assert "1000x1000bb.jpg" in upgraded


def test_fetch_artwork_mock_success():
    valid_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 200
    with patch("zoink.artwork._download_image", return_value=valid_jpeg):
        result = fetch_artwork(url="https://example.com/art.jpg")
        assert result == valid_jpeg
