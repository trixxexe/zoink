"""YouTube search provider via yt-dlp."""

from __future__ import annotations

import os
import re
from typing import Optional

import yt_dlp

from zoink.provider import (
    AlbumResult,
    MediaStream,
    SearchProvider,
    TrackResult,
)

_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _node_path() -> str | None:
    for candidate in (
        "/data/data/com.termux/files/usr/bin/node",
        "/usr/bin/node",
        "/usr/local/bin/node",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    for p in os.environ.get("PATH", "").split(os.pathsep):
        probe = os.path.join(p, "node")
        if os.path.isfile(probe) and os.access(probe, os.X_OK):
            return probe
    return None


_NODE = _node_path()


def _base_opts(**overrides) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "ignoreerrors": True,
        "retries": 3,
        "fragment_retries": 3,
        "headers": dict(_BASE_HEADERS),
        "socket_timeout": 15,
        "geo_bypass": True,
        "concurrent_fragment_downloads": 4,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
                "skip": ["dash", "hls", "translated_subs"],
            }
        },
    }
    if _NODE:
        opts["jsruntime"] = _NODE
    opts.update(overrides)
    return opts


def _clean_artist(uploader: str, title: str) -> tuple[str, str]:
    """Extract and clean artist and track title."""
    clean_uploader = re.sub(r"\s*-\s*Topic$", "", uploader, flags=re.IGNORECASE).strip()
    clean_uploader = re.sub(r"\s*VEVO$", "", clean_uploader, flags=re.IGNORECASE).strip()

    # If title has "Artist - Song", extract
    if " - " in title:
        parts = title.split(" - ", 1)
        parsed_artist = parts[0].strip()
        parsed_title = parts[1].strip()
        # Remove common trailing tags like (Official Music Video)
        parsed_title = re.sub(r"[\(\[][^\)\]]*(official|audio|video|lyric|remaster|hd)[^\)\]]*[\)\]]", "", parsed_title, flags=re.IGNORECASE).strip()
        return parsed_artist or clean_uploader, parsed_title or title

    clean_title = re.sub(r"[\(\[][^\)\]]*(official|audio|video|lyric|remaster|hd)[^\)\]]*[\)\]]", "", title, flags=re.IGNORECASE).strip()
    return clean_uploader, clean_title or title


class YouTubeProvider(SearchProvider):
    """yt-dlp backed YouTube search provider."""

    name = "youtube"

    def search_tracks(self, query: str, limit: int = 10) -> list[TrackResult]:
        query = query.strip()
        if not query:
            return []

        # Check if query is a direct URL
        if query.startswith(("http://", "https://", "www.", "youtu.be")):
            opts = _base_opts(skip_download=True)
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(query, download=False)
                if not info:
                    return []
                # If single video
                if "entries" not in info:
                    artist, title = _clean_artist(str(info.get("uploader", "")), str(info.get("title", "Unknown")))
                    return [
                        TrackResult(
                            id=info.get("id", ""),
                            title=title,
                            artist=artist,
                            album=str(info.get("album", "")).strip(),
                            duration=int(info.get("duration") or 0),
                            artwork_url=info.get("thumbnail", ""),
                            source="youtube",
                            url=info.get("webpage_url") or f"https://www.youtube.com/watch?v={info.get('id', '')}",
                        )
                    ]
                # If playlist URL
                entries = list(info.get("entries") or [])
                results: list[TrackResult] = []
                for e in entries[:limit]:
                    if not e:
                        continue
                    vid = e.get("id", "")
                    raw_title = str(e.get("title", "Unknown")).strip()
                    raw_uploader = str(e.get("uploader", "")).strip()
                    artist, title = _clean_artist(raw_uploader, raw_title)
                    url = e.get("url") or f"https://www.youtube.com/watch?v={vid}"
                    results.append(
                        TrackResult(
                            id=vid,
                            title=title,
                            artist=artist,
                            duration=int(e.get("duration") or 0),
                            artwork_url=e.get("thumbnail", ""),
                            source="youtube",
                            url=url,
                        )
                    )
                return results
            except Exception:
                return []

        opts = _base_opts(extract_flat=True, skip_download=True)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        except Exception:
            return []

        entries = list(info.get("entries") or []) if info else []
        results: list[TrackResult] = []
        for e in entries:
            if not e:
                continue
            vid = e.get("id", "")
            url = e.get("url")
            if not url and vid:
                url = f"https://www.youtube.com/watch?v={vid}"
            if not url:
                continue
            raw_title = str(e.get("title", "Unknown")).strip()
            raw_uploader = str(e.get("uploader", "")).strip()
            artist, title = _clean_artist(raw_uploader, raw_title)
            results.append(
                TrackResult(
                    id=vid or e.get("id", ""),
                    title=title,
                    artist=artist,
                    duration=int(e.get("duration") or 0),
                    artwork_url=e.get("thumbnail", ""),
                    source="youtube",
                    url=url,
                )
            )
        return results

    def resolve_track(self, track_id: str) -> Optional[TrackResult]:
        url = track_id if track_id.startswith(("http://", "https://")) else f"https://www.youtube.com/watch?v={track_id}"
        opts = _base_opts(skip_download=True)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception:
            return None
        if not info:
            return None

        artist, title = _clean_artist(str(info.get("uploader", "")), str(info.get("title", "Unknown")))
        album = str(info.get("album", "")).strip()
        return TrackResult(
            id=info.get("id", track_id),
            title=title,
            artist=artist,
            album=album,
            album_artist=str(info.get("album_artist", "")).strip() or artist,
            duration=int(info.get("duration") or 0),
            year=int(info.get("upload_date", "")[:4] or 0) if info.get("upload_date") else 0,
            track_number=int(info.get("track_number") or 0),
            artwork_url=info.get("thumbnail", ""),
            has_lyrics=bool(info.get("subtitles") or info.get("automatic_captions")),
            source="youtube",
            url=info.get("webpage_url") or url,
        )

    def search_albums(self, query: str, limit: int = 5) -> list[AlbumResult]:
        opts = _base_opts(extract_flat=True, skip_download=True)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{query} full album", download=False)
        except Exception:
            return []
        entries = list(info.get("entries") or []) if info else []
        albums = []
        for e in entries:
            if not e:
                continue
            vid = e.get("id", "")
            title = str(e.get("title", "Unknown")).strip()
            artist = str(e.get("uploader", "")).strip()
            albums.append(
                AlbumResult(
                    id=vid,
                    title=title,
                    artist=artist,
                    artwork_url=e.get("thumbnail", ""),
                    source="youtube",
                )
            )
        return albums

    def resolve_album(self, album_id: str) -> Optional[AlbumResult]:
        # Handle playlist URL or playlist ID
        url = album_id if album_id.startswith(("http://", "https://")) else f"https://www.youtube.com/playlist?list={album_id}"
        opts = _base_opts(extract_flat=True, skip_download=True)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception:
            # Maybe it's a single video ID that user treated as album
            return None
        if not info:
            return None

        tracks: list[TrackResult] = []
        for i, e in enumerate(info.get("entries") or [], 1):
            if not e:
                continue
            vid = e.get("id", "")
            url_track = e.get("url") or f"https://www.youtube.com/watch?v={vid}"
            artist, title = _clean_artist(str(e.get("uploader", "")), str(e.get("title", "Unknown")))
            tracks.append(
                TrackResult(
                    id=vid,
                    title=title,
                    artist=artist,
                    album=str(info.get("title", "")).strip(),
                    duration=int(e.get("duration") or 0),
                    track_number=i,
                    artwork_url=e.get("thumbnail", ""),
                    source="youtube",
                    url=url_track,
                )
            )

        return AlbumResult(
            id=info.get("id", album_id),
            title=str(info.get("title", "Unknown Album")).strip(),
            artist=str(info.get("uploader", "")).strip(),
            artwork_url=info.get("thumbnail", ""),
            tracks=tracks,
            source="youtube",
        )

    def resolve_media(
        self,
        track_id: str,
        audio_format: str = "mp3",
        quality: str = "best",
    ) -> Optional[MediaStream]:
        quality_map = {
            "best": "0",
            "320": "320",
            "256": "256",
            "192": "192",
            "128": "128",
        }
        q = quality_map.get(quality, "0")
        url = track_id if track_id.startswith(("http://", "https://")) else f"https://www.youtube.com/watch?v={track_id}"
        opts = _base_opts(
            format="bestaudio/best",
            skip_download=True,
        )
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception:
            return None
        if not info:
            return None

        # Pick best audio format
        fmts = info.get("formats") or []
        audio_fmts = [f for f in fmts if f.get("acodec") != "none" and f.get("vcodec") == "none"]
        if not audio_fmts:
            audio_fmts = [f for f in fmts if f.get("acodec") != "none"]
        if not audio_fmts:
            return None
        best = max(audio_fmts, key=lambda f: f.get("abr") or 0)
        return MediaStream(
            url=best.get("url", info.get("url", "")),
            format_id=best.get("format_id", ""),
            ext=audio_format,
            audio_bitrate=int(best.get("abr") or 0),
            audio_quality=q,
        )
