"""Lyrics fetcher with LRCLIB API support and yt-dlp subtitles fallback."""

from __future__ import annotations

import re
from typing import Optional

import requests
import yt_dlp

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "ZoinK/0.1 (https://github.com/zoink-music)"})


def fetch_lyrics(
    track_id: str = "",
    source: str = "youtube",
    title: str = "",
    artist: str = "",
    album: str = "",
    duration: int = 0,
    **kwargs,
) -> Optional[str]:
    """Fetch full lyrics for a track.

    Tries LRCLIB public lyrics database first; falls back to yt-dlp captions.
    Returns plain text lyrics or None.
    """
    if track_id and not title and source not in ("youtube", "soundcloud", "bandcamp", ""):
        title = track_id
        artist = source
        track_id = kwargs.get("track_id", "")
        source = kwargs.get("source", "youtube")
    # 1. Try LRCLIB if track title is available
    if title:
        lyrics = _fetch_lrclib(title=title, artist=artist, album=album, duration=duration)
        if lyrics:
            return lyrics

    # 2. Try yt-dlp subtitle/captions if track_id and source == 'youtube'
    if source == "youtube" and track_id:
        return _fetch_ytdlp_captions(track_id)

    return None


def _fetch_lrclib(title: str, artist: str = "", album: str = "", duration: int = 0) -> Optional[str]:
    """Query LRCLIB public lyrics service (free, legitimate, no auth required)."""
    try:
        # Clean title (remove (Official Video), [Audio], etc.)
        clean_title = re.sub(r"[\(\[][^\)\]]*(official|audio|video|lyric|remaster)[^\)\]]*[\)\]]", "", title, flags=re.IGNORECASE).strip()
        params = {"track_name": clean_title or title}
        if artist:
            # Clean artist (remove - Topic, etc.)
            clean_artist = re.sub(r"\s*-\s*Topic\s*", "", artist, flags=re.IGNORECASE).strip()
            params["artist_name"] = clean_artist
        if album:
            params["album_name"] = album
        if duration > 0:
            params["duration"] = str(duration)

        resp = _SESSION.get("https://lrclib.net/api/get", params=params, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            plain = data.get("plainLyrics")
            if plain and plain.strip():
                return plain.strip()

        # Fallback to search if exact match 404s
        search_resp = _SESSION.get("https://lrclib.net/api/search", params={"q": f"{artist} {clean_title or title}"}, timeout=8)
        if search_resp.status_code == 200:
            items = search_resp.json()
            if isinstance(items, list) and items:
                first = items[0]
                plain = first.get("plainLyrics")
                if plain and plain.strip():
                    return plain.strip()
    except Exception:
        pass
    return None


def _fetch_ytdlp_captions(track_id: str) -> Optional[str]:
    """Fetch captions from YouTube using yt-dlp."""
    url = f"https://www.youtube.com/watch?v={track_id}"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "subtitlesformat": "vtt/srt/best",
        "noplaylist": True,
        "socket_timeout": 15,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None
    if not info:
        return None

    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    sub_data = subs.get("en") or auto.get("en")
    if not sub_data:
        for lang_list in [subs, auto]:
            for tracks in lang_list.values():
                if tracks:
                    sub_data = tracks
                    break
            if sub_data:
                break
    if not sub_data:
        return None

    sub_url = sub_data[0].get("url") or sub_data[0].get("ext", "")
    if not sub_url or sub_url.startswith("vtt") or sub_url.startswith("srt"):
        return None

    try:
        resp = _SESSION.get(sub_url, timeout=12)
        if resp.status_code == 200:
            return _clean_vtt(resp.text)
    except Exception:
        pass
    return None


def _clean_vtt(text: str) -> str:
    """Strip VTT formatting tags and return clean plain text."""
    lines = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if "-->" in line or line.isdigit():
            continue
        # Strip HTML-like tags
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean and clean not in seen:
            seen.add(clean)
            lines.append(clean)
    return "\n".join(lines) if lines else ""

