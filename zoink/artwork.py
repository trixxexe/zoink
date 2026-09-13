"""Artwork fetcher — downloads, upgrades, validates, and prepares album art."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import requests

import threading

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ZoinK/0.1"})

_MAX_SIZE = 15 * 1024 * 1024  # 15 MB
_TIMEOUT = 6

_ARTWORK_CACHE: dict[str, bytes] = {}
_ARTWORK_CACHE_LOCK = threading.Lock()


def fetch_artwork(
    url: str = "",
    title: str = "",
    artist: str = "",
    album: str = "",
) -> Optional[bytes]:
    """Download artwork from a URL or fallback search. Returns JPEG/PNG bytes or None."""
    cache_key = url.strip() or f"{artist.strip().lower()}::{album.strip().lower() or title.strip().lower()}"
    if cache_key:
        with _ARTWORK_CACHE_LOCK:
            if cache_key in _ARTWORK_CACHE:
                return _ARTWORK_CACHE[cache_key]

    candidates = []
    if url:
        # Check if URL can be upgraded (e.g., YouTube thumbnail URLs)
        candidates.extend(_get_url_candidates(url))

    for candidate_url in candidates:
        data = _download_image(candidate_url)
        if data:
            norm = _normalize_image(data)
            if norm and cache_key:
                with _ARTWORK_CACHE_LOCK:
                    if len(_ARTWORK_CACHE) > 100:
                        _ARTWORK_CACHE.clear()
                    _ARTWORK_CACHE[cache_key] = norm
            return norm

    # Fallback search if URL wasn't available or all candidates failed
    if title and artist:
        fallback_url = _search_album_art(artist=artist, title=title, album=album)
        if fallback_url:
            data = _download_image(fallback_url)
            if data:
                norm = _normalize_image(data)
                if norm and cache_key:
                    with _ARTWORK_CACHE_LOCK:
                        if len(_ARTWORK_CACHE) > 100:
                            _ARTWORK_CACHE.clear()
                        _ARTWORK_CACHE[cache_key] = norm
                return norm

    return None


def _get_url_candidates(url: str) -> list[str]:
    """Return upgraded high-res candidate URLs if applicable."""
    candidates = []
    # YouTube thumbnails: hqdefault.jpg -> maxresdefault.jpg, sddefault.jpg
    if "ytimg.com/vi/" in url:
        m = re.search(r"ytimg\.com/vi/([^/?#]+)", url)
        if m:
            vid = m.group(1)
            candidates.append(f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg")
            candidates.append(f"https://i.ytimg.com/vi/{vid}/sddefault.jpg")
            candidates.append(f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg")
    candidates.append(url)
    return candidates


def _download_image(url: str) -> Optional[bytes]:
    """Download image bytes from URL."""
    try:
        resp = _SESSION.get(url, timeout=_TIMEOUT, stream=True)
        if resp.status_code != 200:
            return None
        content_type = resp.headers.get("Content-Type", "").lower()
        if "html" in content_type or "text" in content_type:
            return None
        data = resp.content
        if len(data) > _MAX_SIZE or len(data) < 100:
            return None
        if not _valid_image(data):
            return None
        return data
    except Exception:
        return None


def _search_album_art(artist: str, title: str, album: str = "") -> Optional[str]:
    """Search iTunes Search API for official high-resolution album artwork (no auth required)."""
    try:
        query = f"{artist} {album or title}"
        resp = _SESSION.get(
            "https://itunes.apple.com/search",
            params={"term": query, "media": "music", "entity": "song", "limit": "1"},
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        results = data.get("results") or []
        if results and results[0].get("artworkUrl100"):
            raw_art = results[0]["artworkUrl100"]
            # Upgrade 100x100 to 1000x1000 or 600x600
            return raw_art.replace("100x100bb.jpg", "1000x1000bb.jpg")
    except Exception:
        pass
    return None


def _normalize_image(data: bytes) -> bytes:
    """Ensure image is JPEG or PNG for standard player tag compatibility.

    If WebP, convert to JPEG using ffmpeg.
    """
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        converted = _convert_webp_to_jpeg(data)
        if converted:
            return converted
    return data


def _convert_webp_to_jpeg(webp_data: bytes) -> Optional[bytes]:
    """Convert WebP bytes to JPEG bytes using ffmpeg in-memory or fallback."""
    # Fast path: in-memory streaming via stdin/stdout pipe
    try:
        cmd = ["ffmpeg", "-y", "-i", "pipe:0", "-f", "image2", "-c:v", "mjpeg", "-q:v", "2", "pipe:1"]
        proc = subprocess.run(cmd, input=webp_data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
        if proc.returncode == 0 and proc.stdout and proc.stdout[:3] == b"\xff\xd8\xff":
            return proc.stdout
    except Exception:
        pass

    # Fallback path: temporary files
    try:
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as in_f:
            in_f.write(webp_data)
            in_path = Path(in_f.name)
        out_path = in_path.with_suffix(".jpg")
        try:
            cmd = ["ffmpeg", "-y", "-i", str(in_path), "-q:v", "2", str(out_path)]
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
            if proc.returncode == 0 and out_path.exists():
                return out_path.read_bytes()
        finally:
            if in_path.exists():
                in_path.unlink()
            if out_path.exists():
                out_path.unlink()
    except Exception:
        pass
    return webp_data


def _valid_image(data: bytes) -> bool:
    """Quick check that bytes look like an image."""
    if data[:3] == b"\xff\xd8\xff":  # JPEG
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":  # PNG
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":  # WebP
        return True
    return False

