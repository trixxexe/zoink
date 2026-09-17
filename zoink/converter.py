"""Audio conversion module for ZoinK.

Converts audio files between formats (MP3, M4A, FLAC, Opus, OGG, WAV) using FFmpeg,
preserving full metadata, lyrics, and embedded album artwork.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from zoink.library import Library
from zoink.metadata import embed_metadata, extract_artwork_data, read_metadata, verify_audio_file
from zoink.provider import TrackResult

SUPPORTED_FORMATS = ("mp3", "m4a", "flac", "opus", "ogg", "wav")

BITRATE_MAP = {
    "best": {"mp3": "320k", "m4a": "256k", "opus": "160k", "ogg": "6"},
    "lossless": {"mp3": "320k", "m4a": "256k", "opus": "160k", "ogg": "6"},
    "320k": {"mp3": "320k", "m4a": "320k", "opus": "256k", "ogg": "9"},
    "320": {"mp3": "320k", "m4a": "320k", "opus": "256k", "ogg": "9"},
    "256k": {"mp3": "256k", "m4a": "256k", "opus": "192k", "ogg": "8"},
    "256": {"mp3": "256k", "m4a": "256k", "opus": "192k", "ogg": "8"},
    "192k": {"mp3": "192k", "m4a": "192k", "opus": "160k", "ogg": "6"},
    "192": {"mp3": "192k", "m4a": "192k", "opus": "160k", "ogg": "6"},
    "160k": {"mp3": "160k", "m4a": "160k", "opus": "160k", "ogg": "5"},
    "160": {"mp3": "160k", "m4a": "160k", "opus": "160k", "ogg": "5"},
    "128k": {"mp3": "128k", "m4a": "128k", "opus": "128k", "ogg": "4"},
    "128": {"mp3": "128k", "m4a": "128k", "opus": "128k", "ogg": "4"},
}


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg executable is available in PATH."""
    return shutil.which("ffmpeg") is not None


def run_ffmpeg_transcode(
    input_file: Path,
    output_file: Path,
    target_format: str,
    quality: str = "best",
) -> bool:
    """Run FFmpeg to transcode an audio file into the target format."""
    target_format = target_format.lower().lstrip(".")
    if target_format not in SUPPORTED_FORMATS:
        return False

    q_key = str(quality).lower()
    rates = BITRATE_MAP.get(q_key, BITRATE_MAP["best"])

    cmd = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-i",
        str(input_file),
        "-vn",
        "-threads",
        "0",
    ]

    if target_format == "mp3":
        br = rates.get("mp3", "320k")
        cmd.extend(["-c:a", "libmp3lame", "-b:a", br, "-id3v2_version", "3"])
    elif target_format in ("m4a", "aac"):
        br = rates.get("m4a", "256k")
        cmd.extend(["-c:a", "aac", "-b:a", br])
    elif target_format == "flac":
        cmd.extend(["-c:a", "flac", "-compression_level", "5"])
    elif target_format == "opus":
        br = rates.get("opus", "160k")
        cmd.extend(["-c:a", "libopus", "-b:a", br])
    elif target_format == "ogg":
        q_val = rates.get("ogg", "6")
        cmd.extend(["-c:a", "libvorbis", "-q:a", q_val])
    elif target_format == "wav":
        cmd.extend(["-c:a", "pcm_s16le"])

    cmd.append(str(output_file))

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
            check=False,
        )
        return proc.returncode == 0 and output_file.exists() and output_file.stat().st_size > 0
    except Exception:
        return False


def convert_audio_file(
    source_path: Path | str,
    target_format: str,
    quality: str = "best",
    destination_dir: Optional[Path] = None,
    replace_original: bool = False,
    on_progress: Optional[Callable[[float, str], None]] = None,
) -> tuple[bool, Optional[Path], Optional[str]]:
    """Convert an existing audio file to a new format, copying tags and artwork.

    Returns:
        (success, destination_path, error_message)
    """
    src = Path(source_path).expanduser().resolve()
    if not src.exists() or not src.is_file():
        return False, None, f"Source file does not exist: {src}"

    target_format = target_format.lower().lstrip(".")
    if target_format not in SUPPORTED_FORMATS:
        return False, None, f"Unsupported target format: {target_format}"

    # If already in the target format and replacing original, nothing to do
    cur_ext = src.suffix.lower().lstrip(".")
    if cur_ext == target_format and replace_original:
        return True, src, None

    if not is_ffmpeg_available():
        return False, None, "FFmpeg is not installed or not in PATH"

    if on_progress:
        on_progress(10.0, "Reading source metadata and artwork...")

    # Read existing metadata and artwork
    meta = read_metadata(src)
    artwork_data, _ = extract_artwork_data(src)
    lyrics_text = meta.lyrics if meta else None

    # Determine final destination path
    out_dir = destination_dir or src.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    base_stem = src.stem
    final_dest = out_dir / f"{base_stem}.{target_format}"

    if final_dest.exists() and not replace_original and final_dest.resolve() != src.resolve():
        counter = 1
        candidate = out_dir / f"{base_stem} ({counter}).{target_format}"
        while candidate.exists():
            counter += 1
            candidate = out_dir / f"{base_stem} ({counter}).{target_format}"
        final_dest = candidate

    tmp_dir = Path(tempfile.mkdtemp(prefix="zoink_convert_"))
    tmp_out = tmp_dir / f"transcoded.{target_format}"

    try:
        if on_progress:
            on_progress(30.0, f"Transcoding to {target_format.upper()} via FFmpeg...")

        ok = run_ffmpeg_transcode(src, tmp_out, target_format, quality=quality)
        if not ok or not tmp_out.exists() or tmp_out.stat().st_size == 0:
            return False, None, f"FFmpeg transcoding to {target_format} failed"

        if on_progress:
            on_progress(70.0, "Verifying audio container integrity...")

        if not verify_audio_file(tmp_out):
            return False, None, "Converted file failed audio container integrity check"

        if on_progress:
            on_progress(85.0, "Embedding metadata and artwork...")

        if meta:
            if not meta.source:
                meta.source = "zoink"
            embed_metadata(tmp_out, meta, artwork_data=artwork_data, lyrics=lyrics_text)

        if on_progress:
            on_progress(95.0, "Finalizing output file...")

        # If replacing original, remove old file if the path/extension differs
        if replace_original:
            if final_dest.exists() and final_dest.resolve() != src.resolve():
                final_dest.unlink()
            if src.exists() and src.resolve() != final_dest.resolve():
                try:
                    src.unlink()
                except OSError:
                    pass

        shutil.move(str(tmp_out), str(final_dest))

        if on_progress:
            on_progress(100.0, f"Converted to {target_format.upper()} successfully!")

        return True, final_dest, None

    except Exception as exc:
        return False, None, str(exc)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def convert_library_track(
    library: Library,
    track_id_or_path: str | Path,
    target_format: str,
    quality: str = "best",
    replace_original: bool = True,
    on_progress: Optional[Callable[[float, str], None]] = None,
) -> tuple[bool, Optional[Path], Optional[str]]:
    """Convert a track tracked in the SQLite library and update database records."""
    # Find track in library
    if isinstance(track_id_or_path, dict):
        track_record = track_id_or_path
        src_path = Path(track_record.get("filepath", ""))
    else:
        ref_str = str(track_id_or_path)
        track_record = library.get_track_by_id(ref_str)
        if not track_record:
            track_record = library.get_track_by_path(ref_str)

        if track_record and track_record.get("filepath"):
            src_path = Path(track_record["filepath"])
        else:
            try:
                src_path = Path(ref_str)
            except Exception:
                return False, None, f"Invalid track reference: {track_id_or_path}"

    old_filepath_str = str(src_path)

    success, final_path, err = convert_audio_file(
        source_path=src_path,
        target_format=target_format,
        quality=quality,
        replace_original=replace_original,
        on_progress=on_progress,
    )

    if not success or not final_path:
        return False, None, err

    # Update SQLite database
    new_meta = read_metadata(final_path)
    if new_meta:
        if track_record:
            if not new_meta.title and track_record.get("title"):
                new_meta.title = track_record["title"]
            if not new_meta.artist and track_record.get("artist"):
                new_meta.artist = track_record["artist"]
            if not new_meta.album and track_record.get("album"):
                new_meta.album = track_record["album"]
            new_meta.source = track_record.get("source") or "youtube"

    if replace_original and str(final_path) != old_filepath_str:
        # Delete old record from library if filename changed
        with library._conn() as conn:
            conn.execute("DELETE FROM tracks WHERE filepath = ?", (old_filepath_str,))
            conn.commit()

    library.add_track(final_path, new_meta)
    return True, final_path, None
