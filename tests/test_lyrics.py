"""Tests for lyrics fetching and VTT parsing."""

from unittest.mock import MagicMock, patch
from zoink.lyrics import _clean_vtt, fetch_lyrics


def test_clean_vtt():
    sample_vtt = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000
<c>First</c> line of the song

00:00:03.000 --> 00:00:05.000
Second line of the song

00:00:05.000 --> 00:00:07.000
Second line of the song
"""
    cleaned = _clean_vtt(sample_vtt)
    assert "WEBVTT" not in cleaned
    assert "-->" not in cleaned
    assert "<c>" not in cleaned
    assert "First line of the song" in cleaned
    assert "Second line of the song" in cleaned
    # Deduplication test
    assert cleaned.count("Second line of the song") == 1


def test_fetch_lyrics_lrclib_success():
    with patch("zoink.lyrics._SESSION.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "plainLyrics": "I've been on my own for long enough\nMaybe you can show me how to love"
        }
        mock_get.return_value = mock_resp

        lyrics = fetch_lyrics(title="Blinding Lights", artist="The Weeknd", duration=200)
        assert lyrics is not None
        assert "I've been on my own" in lyrics


def test_fetch_lyrics_not_found():
    with patch("zoink.lyrics._SESSION.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp

        # No captions either
        with patch("zoink.lyrics._fetch_ytdlp_captions", return_value=None):
            lyrics = fetch_lyrics(title="Unknown Song", artist="Nobody")
            assert lyrics is None
