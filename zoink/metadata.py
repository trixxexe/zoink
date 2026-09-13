"""Metadata embedding and reading using mutagen.

Handles ID3 (MP3), MP4 (M4A), and Vorbis (FLAC/OGG/Opus) tagging.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional

from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    ID3,
    APIC,
    COMM,
    ID3NoHeaderError,
    TALB,
    TCOM,
    TCON,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TRCK,
    USLT,
)
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
import mutagen

from zoink.provider import TrackResult

# ---------------------------------------------------------------------------
# MIME and Image helpers
# ---------------------------------------------------------------------------

_EXT_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _mime_from_data(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _cover_from_data(data: bytes) -> Picture:
    pic = Picture()
    pic.type = 3  # Cover front
    pic.mime = _mime_from_data(data)
    pic.data = data
    return pic


# ---------------------------------------------------------------------------
# Media Integrity Verification
# ---------------------------------------------------------------------------


def verify_audio_file(filepath: Path) -> bool:
    """Verify that an audio file exists, has non-trivial size, and has valid container/audio headers."""
    if not filepath.exists() or not filepath.is_file():
        return False
    try:
        size = filepath.stat().st_size
        if size < 2048:  # Less than 2KB is almost certainly truncated/empty
            return False
        # Try loading with mutagen to verify container integrity
        try:
            mf = mutagen.File(filepath)
            if mf is not None:
                return True
        except Exception:
            pass

        # If mutagen could not parse, check magic bytes for standard audio containers
        with open(filepath, "rb") as f:
            header = f.read(32)
        if len(header) < 4:
            return False

        # MP3 ID3 header or sync word
        if header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
            return True
        # M4A/MP4/AAC container: "ftyp" at offset 4 or ADTS sync word
        if (len(header) >= 8 and header[4:8] == b"ftyp") or (len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xF6) == 0xF0):
            return True
        # FLAC: "fLaC"
        if header.startswith(b"fLaC"):
            return True
        # OGG/Opus: "OggS"
        if header.startswith(b"OggS"):
            return True
        # RIFF WAVE
        if header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WAVE":
            return True

        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_metadata(
    filepath: Path,
    track: TrackResult,
    artwork_data: Optional[bytes] = None,
    lyrics: Optional[str] = None,
) -> bool:
    """Embed metadata, artwork, and lyrics into an audio file.

    Returns True on success, False on failure.
    """
    ext = filepath.suffix.lower()
    lyrics_text = lyrics or track.lyrics or None
    try:
        if ext == ".mp3":
            return _embed_mp3(filepath, track, artwork_data, lyrics_text)
        if ext in (".m4a", ".mp4", ".aac"):
            return _embed_m4a(filepath, track, artwork_data, lyrics_text)
        if ext == ".flac":
            return _embed_flac(filepath, track, artwork_data, lyrics_text)
        if ext in (".ogg", ".opus"):
            return _embed_ogg(filepath, track, artwork_data, lyrics_text)
        return False
    except Exception:
        return False


def _embed_mp3(
    fp: Path, track: TrackResult, art: Optional[bytes], lyrics: Optional[str]
) -> bool:
    try:
        tags = ID3(fp)
    except ID3NoHeaderError:
        tags = ID3()
    except Exception:
        return False

    tags.add(TIT2(encoding=3, text=[track.title]))
    if track.artist:
        tags.add(TPE1(encoding=3, text=[track.artist]))
    if track.album_artist:
        tags.add(TPE2(encoding=3, text=[track.album_artist]))
    if track.album:
        tags.add(TALB(encoding=3, text=[track.album]))
    if track.year:
        tags.add(TDRC(encoding=3, text=[str(track.year)]))

    if track.track_number:
        trck_str = str(track.track_number)
        if track.total_tracks:
            trck_str = f"{track.track_number}/{track.total_tracks}"
        tags.add(TRCK(encoding=3, text=[trck_str]))

    if track.disc_number:
        disc_str = str(track.disc_number)
        if track.total_discs:
            disc_str = f"{track.disc_number}/{track.total_discs}"
        tags.add(TPOS(encoding=3, text=[disc_str]))

    if track.composer:
        tags.add(TCOM(encoding=3, text=[track.composer]))
    if track.genre:
        tags.add(TCON(encoding=3, text=[track.genre]))

    comment_str = track.comment or (f"Source: {track.source}" if track.source else "")
    if comment_str:
        tags.add(COMM(encoding=3, lang="eng", desc="", text=[comment_str]))

    if art:
        mime = _mime_from_data(art)
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=art))
    if lyrics:
        tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))

    try:
        tags.save(fp)
        return True
    except Exception:
        return False


def _embed_m4a(
    fp: Path, track: TrackResult, art: Optional[bytes], lyrics: Optional[str]
) -> bool:
    try:
        audio = MP4(fp)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
    except Exception:
        return False

    tags["\xa9nam"] = [track.title]
    if track.artist:
        tags["\xa9ART"] = [track.artist]
    if track.album_artist:
        tags["aART"] = [track.album_artist]
    if track.album:
        tags["\xa9alb"] = [track.album]
    if track.year:
        tags["\xa9day"] = [str(track.year)]
    if track.composer:
        tags["\xa9wrt"] = [track.composer]
    if track.genre:
        tags["\xa9gen"] = [track.genre]
    if track.track_number:
        tags["trkn"] = [(track.track_number, track.total_tracks or 0)]
    if track.disc_number:
        tags["disk"] = [(track.disc_number, track.total_discs or 0)]
    comment_str = track.comment or (f"Source: {track.source}" if track.source else "")
    if comment_str:
        tags["\xa9cmt"] = [comment_str]

    if art:
        mime = _mime_from_data(art)
        fmt = MP4Cover.FORMAT_PNG if "png" in mime else MP4Cover.FORMAT_JPEG
        tags["covr"] = [MP4Cover(art, imageformat=fmt)]
    if lyrics:
        tags["\xa9lyr"] = [lyrics]

    try:
        tags.save(fp)
        return True
    except Exception:
        return False


def _embed_flac(
    fp: Path, track: TrackResult, art: Optional[bytes], lyrics: Optional[str]
) -> bool:
    try:
        audio = FLAC(fp)
    except Exception:
        return False

    audio["title"] = [track.title]
    if track.artist:
        audio["artist"] = [track.artist]
    if track.album_artist:
        audio["albumartist"] = [track.album_artist]
    if track.album:
        audio["album"] = [track.album]
    if track.year:
        audio["date"] = [str(track.year)]
    if track.track_number:
        audio["tracknumber"] = [str(track.track_number)]
    if track.total_tracks:
        audio["totaltracks"] = [str(track.total_tracks)]
        audio["tracktotal"] = [str(track.total_tracks)]
    if track.disc_number:
        audio["discnumber"] = [str(track.disc_number)]
    if track.total_discs:
        audio["totaldiscs"] = [str(track.total_discs)]
        audio["disctotal"] = [str(track.total_discs)]
    if track.composer:
        audio["composer"] = [track.composer]
    if track.genre:
        audio["genre"] = [track.genre]

    comment_str = track.comment or (f"Source: {track.source}" if track.source else "")
    if comment_str:
        audio["comment"] = [comment_str]

    if art:
        audio.clear_pictures()
        audio.add_picture(_cover_from_data(art))
    if lyrics:
        audio["lyrics"] = [lyrics]

    try:
        audio.save()
        return True
    except Exception:
        return False


def _embed_ogg(
    fp: Path, track: TrackResult, art: Optional[bytes], lyrics: Optional[str]
) -> bool:
    try:
        audio = OggOpus(fp) if fp.suffix == ".opus" else OggVorbis(fp)
    except Exception:
        return False

    audio["title"] = [track.title]
    if track.artist:
        audio["artist"] = [track.artist]
    if track.album_artist:
        audio["albumartist"] = [track.album_artist]
    if track.album:
        audio["album"] = [track.album]
    if track.year:
        audio["date"] = [str(track.year)]
    if track.track_number:
        audio["tracknumber"] = [str(track.track_number)]
    if track.total_tracks:
        audio["totaltracks"] = [str(track.total_tracks)]
    if track.disc_number:
        audio["discnumber"] = [str(track.disc_number)]
    if track.total_discs:
        audio["totaldiscs"] = [str(track.total_discs)]
    if track.composer:
        audio["composer"] = [track.composer]
    if track.genre:
        audio["genre"] = [track.genre]

    comment_str = track.comment or (f"Source: {track.source}" if track.source else "")
    if comment_str:
        audio["comment"] = [comment_str]

    if art:
        pic = _cover_from_data(art)
        # Vorbis comments store cover pictures as base64-encoded binary picture blocks
        raw_block = pic.write()
        encoded = base64.b64encode(raw_block).decode("ascii")
        audio["metadata_block_picture"] = [encoded]

    if lyrics:
        audio["lyrics"] = [lyrics]

    try:
        audio.save()
        return True
    except Exception:
        return False


def read_metadata(filepath: Path) -> Optional[TrackResult]:
    """Read metadata from a local audio file into a TrackResult."""
    if not filepath.exists():
        return None
    ext = filepath.suffix.lower()
    try:
        if ext == ".mp3":
            return _read_mp3(filepath)
        if ext in (".m4a", ".mp4", ".aac"):
            return _read_m4a(filepath)
        if ext == ".flac":
            return _read_flac(filepath)
        if ext in (".ogg", ".opus"):
            return _read_ogg(filepath)
    except Exception:
        return None
    return None


def _read_mp3(fp: Path) -> Optional[TrackResult]:
    try:
        tags = ID3(fp)
    except Exception:
        return None

    def _get(key, default=""):
        val = tags.get(key)
        return str(val.text[0]) if val and val.text else default

    title = _get("TIT2", fp.stem)
    artist = _get("TPE1")
    album = _get("TALB")
    album_artist = _get("TPE2")
    composer = _get("TCOM")
    genre = _get("TCON")
    year = _safe_int(_get("TDRC", "0"))

    trck_str = _get("TRCK", "0")
    parts = trck_str.split("/")
    track_num = _safe_int(parts[0])
    total_tracks = _safe_int(parts[1]) if len(parts) > 1 else 0

    tpos_str = _get("TPOS", "0")
    d_parts = tpos_str.split("/")
    disc_num = _safe_int(d_parts[0])
    total_discs = _safe_int(d_parts[1]) if len(d_parts) > 1 else 0

    has_artwork = any(k.startswith("APIC") for k in tags)
    lyrics = ""
    for k in tags:
        if k.startswith("USLT"):
            lyrics = str(tags[k].text)
            break

    duration = 0
    try:
        mf = mutagen.File(fp)
        if mf and hasattr(mf, "info") and mf.info:
            duration = int(getattr(mf.info, "length", 0))
    except Exception:
        pass

    return TrackResult(
        id=fp.stem,
        title=title or fp.stem,
        artist=artist,
        album=album,
        album_artist=album_artist,
        composer=composer,
        genre=genre,
        year=year,
        track_number=track_num,
        total_tracks=total_tracks,
        disc_number=disc_num,
        total_discs=total_discs,
        has_lyrics=bool(lyrics),
        lyrics=lyrics,
        artwork_url="" if not has_artwork else f"local://{fp.stem}",
        source="local",
        filepath=str(fp),
        duration=duration,
    )


def _read_m4a(fp: Path) -> Optional[TrackResult]:
    try:
        audio = MP4(fp)
        tags = audio.tags or {}
    except Exception:
        return None

    title = str((tags.get("\xa9nam") or [fp.stem])[0])
    artist = str((tags.get("\xa9ART") or [""])[0])
    album = str((tags.get("\xa9alb") or [""])[0])
    album_artist = str((tags.get("aART") or [""])[0])
    composer = str((tags.get("\xa9wrt") or [""])[0])
    genre = str((tags.get("\xa9gen") or [""])[0])
    year = _safe_int(str((tags.get("\xa9day") or ["0"])[0]))

    trkn_list = tags.get("trkn") or [(0, 0)]
    trkn = trkn_list[0] if trkn_list else (0, 0)
    track_num = trkn[0] if len(trkn) > 0 else 0
    total_tracks = trkn[1] if len(trkn) > 1 else 0

    disk_list = tags.get("disk") or [(0, 0)]
    disk = disk_list[0] if disk_list else (0, 0)
    disc_num = disk[0] if len(disk) > 0 else 0
    total_discs = disk[1] if len(disk) > 1 else 0

    has_artwork = "covr" in tags and len(tags["covr"]) > 0
    lyrics = str((tags.get("\xa9lyr") or [""])[0])

    duration = int(getattr(audio.info, "length", 0)) if hasattr(audio, "info") and audio.info else 0

    return TrackResult(
        id=fp.stem,
        title=title or fp.stem,
        artist=artist,
        album=album,
        album_artist=album_artist,
        composer=composer,
        genre=genre,
        year=year,
        track_number=track_num,
        total_tracks=total_tracks,
        disc_number=disc_num,
        total_discs=total_discs,
        has_lyrics=bool(lyrics),
        lyrics=lyrics,
        artwork_url="" if not has_artwork else f"local://{fp.stem}",
        source="local",
        filepath=str(fp),
        duration=duration,
    )


def _read_flac(fp: Path) -> Optional[TrackResult]:
    try:
        audio = FLAC(fp)
    except Exception:
        return None

    def _get(key, default=""):
        val = audio.get(key, [""])
        return str(val[0]) if val else default

    title = _get("title", fp.stem)
    artist = _get("artist")
    album = _get("album")
    album_artist = _get("albumartist")
    composer = _get("composer")
    genre = _get("genre")
    year = _safe_int(_get("date", "0"))
    track_num = _safe_int(_get("tracknumber", "0"))
    total_tracks = _safe_int(_get("totaltracks") or _get("tracktotal", "0"))
    disc_num = _safe_int(_get("discnumber", "0"))
    total_discs = _safe_int(_get("totaldiscs") or _get("disctotal", "0"))
    lyrics = _get("lyrics")
    has_artwork = bool(audio.pictures)

    duration = int(getattr(audio.info, "length", 0)) if hasattr(audio, "info") and audio.info else 0

    return TrackResult(
        id=fp.stem,
        title=title or fp.stem,
        artist=artist,
        album=album,
        album_artist=album_artist,
        composer=composer,
        genre=genre,
        year=year,
        track_number=track_num,
        total_tracks=total_tracks,
        disc_number=disc_num,
        total_discs=total_discs,
        has_lyrics=bool(lyrics),
        lyrics=lyrics,
        artwork_url="" if not has_artwork else f"local://{fp.stem}",
        source="local",
        filepath=str(fp),
        duration=duration,
    )


def _read_ogg(fp: Path) -> Optional[TrackResult]:
    try:
        audio = OggOpus(fp) if fp.suffix == ".opus" else OggVorbis(fp)
    except Exception:
        return None

    def _get(key, default=""):
        val = audio.get(key, [""])
        return str(val[0]) if val else default

    title = _get("title", fp.stem)
    artist = _get("artist")
    album = _get("album")
    album_artist = _get("albumartist")
    composer = _get("composer")
    genre = _get("genre")
    year = _safe_int(_get("date", "0"))
    track_num = _safe_int(_get("tracknumber", "0"))
    total_tracks = _safe_int(_get("totaltracks") or _get("tracktotal", "0"))
    disc_num = _safe_int(_get("discnumber", "0"))
    total_discs = _safe_int(_get("totaldiscs") or _get("disctotal", "0"))
    lyrics = _get("lyrics")
    has_artwork = "metadata_block_picture" in audio

    duration = int(getattr(audio.info, "length", 0)) if hasattr(audio, "info") and audio.info else 0

    return TrackResult(
        id=fp.stem,
        title=title or fp.stem,
        artist=artist,
        album=album,
        album_artist=album_artist,
        composer=composer,
        genre=genre,
        year=year,
        track_number=track_num,
        total_tracks=total_tracks,
        disc_number=disc_num,
        total_discs=total_discs,
        has_lyrics=bool(lyrics),
        lyrics=lyrics,
        artwork_url="" if not has_artwork else f"local://{fp.stem}",
        source="local",
        filepath=str(fp),
        duration=duration,
    )


def _safe_int(s: str) -> int:
    try:
        clean = str(s).strip()
        if "-" in clean:
            clean = clean.split("-")[0]
        return int(clean)
    except (ValueError, TypeError):
        return 0

