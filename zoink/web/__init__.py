"""Local web server with API, streaming, and background downloads."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from zoink.config import Config, DEFAULTS
from zoink.downloader import DownloadJob, DownloadManager, DownloadState
from zoink.library import Library
from zoink.provider import TrackResult
from zoink.providers import YouTubeProvider

app = Flask(__name__, static_folder=None)

_config: Optional[Config] = None
_library: Optional[Library] = None
_downloader: Optional[DownloadManager] = None
_bg_pool = ThreadPoolExecutor(max_workers=4)
_art_cache: dict[str, tuple[bytes, str]] = {}
_art_cache_lock = threading.Lock()

_AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aac"}
_CHUNK = 64 * 1024


def _get_config() -> Config:
    global _config
    if _config is None:
        _config = Config.get()
    return _config


def _get_library() -> Library:
    global _library
    if _library is None:
        _library = Library(_get_config())
        if _library.count() == 0:
            try:
                _library.scan_directory(prune=True)
            except Exception:
                pass
    return _library


def _get_downloader() -> DownloadManager:
    global _downloader
    if _downloader is None:
        _downloader = DownloadManager(_get_config())
    return _downloader


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _resolve_safe_path(arg1: str | Path, arg2: str | Path) -> Optional[Path]:
    """Resolve a relative path safely inside base_dir, strictly preventing path traversal."""
    if isinstance(arg1, Path) and not isinstance(arg2, Path):
        base_dir, rel_path = arg1, str(arg2)
    else:
        rel_path, base_dir = str(arg1), Path(arg2)

    try:
        clean = urllib.parse.unquote(rel_path or "").strip()
        if not clean or "\x00" in clean:
            return None
        # Strip any leading slashes/backslashes to ensure resolution is relative to base_dir
        clean = clean.lstrip("/\\")
        if not clean:
            return None
        target = (base_dir / clean).resolve()
        base_resolved = base_dir.resolve()
        if target.is_relative_to(base_resolved) and target.is_file():
            return target
    except (ValueError, RuntimeError, OSError):
        return None
    return None


def _find_track_file(track_id_or_path: str) -> Optional[tuple[dict | None, Path]]:
    """Locate an audio file by track ID in the library or relative path in download directory."""
    lib = _get_library()
    cfg = _get_config()

    # 1. Look up by track ID
    t = lib.get_track_by_id(track_id_or_path)
    if t and t.get("filepath"):
        fp = Path(t["filepath"])
        if fp.exists() and fp.is_file():
            return t, fp

    # 2. Look up by path directly in download_dir
    safe_fp = _resolve_safe_path(track_id_or_path, cfg.download_dir)
    if safe_fp:
        track_info = lib.get_track_by_path(safe_fp)
        if track_info:
            return track_info, safe_fp
        from zoink.metadata import is_zoink_file
        if is_zoink_file(safe_fp):
            return track_info, safe_fp

    return None


def _get_mime(filepath: Path) -> str:
    ext = filepath.suffix.lower()
    return {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".opus": "audio/ogg",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
    }.get(ext, mimetypes.guess_type(str(filepath))[0] or "application/octet-stream")


def _parse_range_header(range_header: str, size: int) -> Optional[tuple[int, int]]:
    """Parse HTTP Range header and return (start, end) tuple or None if unsatisfiable."""
    if not range_header or "=" not in range_header:
        return None
    try:
        unit, spec = range_header.split("=", 1)
        if unit.strip().lower() != "bytes":
            return None
        start_s, _, end_s = spec.partition("-")
        start_s = start_s.strip()
        end_s = end_s.strip()

        if not start_s and not end_s:
            return None

        if not start_s:
            suffix = int(end_s)
            if suffix <= 0:
                return None
            start = max(0, size - suffix)
            end = size - 1
        elif not end_s:
            start = int(start_s)
            end = size - 1
        else:
            start = int(start_s)
            end = int(end_s)

        end = min(end, size - 1)
        if start >= size or start > end or start < 0:
            return None
        return start, end
    except (ValueError, IndexError):
        return None


def _stream_file(filepath: Path, mime: str, as_attachment: bool = False, custom_filename: Optional[str] = None) -> Response:
    """Stream audio with memory-efficient HTTP 206 Range support."""
    try:
        size = filepath.stat().st_size
    except OSError:
        return Response("Not Found", status=404)

    fname = custom_filename or filepath.name
    ascii_fname = fname.encode("ascii", "replace").decode("ascii").replace('"', "")
    encoded_fname = urllib.parse.quote(fname, safe="")
    disp = (
        f'attachment; filename="{ascii_fname}"; filename*=UTF-8\'\'{encoded_fname}'
        if as_attachment
        else f'inline; filename="{ascii_fname}"; filename*=UTF-8\'\'{encoded_fname}'
    )

    range_header = request.headers.get("Range")
    if range_header:
        parsed = _parse_range_header(range_header, size)
        if parsed is None:
            return Response("Range Not Satisfiable", status=416, headers={
                "Content-Range": f"bytes */{size}",
                "Access-Control-Allow-Origin": "*",
            })
        start, end = parsed
        length = end - start + 1

        def generate():
            with open(filepath, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(_CHUNK, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        headers = {
            "Content-Type": mime,
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(length),
            "Content-Disposition": disp,
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Range, Content-Type, Accept",
            "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
        }
        return Response(generate(), status=206, headers=headers)

    def generate():
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                yield chunk

    headers = {
        "Content-Type": mime,
        "Accept-Ranges": "bytes",
        "Content-Length": str(size),
        "Content-Disposition": disp,
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Range, Content-Type, Accept",
        "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
    }
    return Response(generate(), status=200, headers=headers)


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"


@app.route("/")
def index():
    return send_from_directory(str(_STATIC_DIR), "index.html")


@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory(str(_STATIC_DIR), path)


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 15)), 50)
    if not q:
        return jsonify([])
    provider = YouTubeProvider()
    results = provider.search_tracks(q, limit)
    return jsonify([_track_to_dict(t) for t in results])


@app.route("/api/library")
@app.route("/api/tracks")
def api_library():
    lib = _get_library()
    limit = min(int(request.args.get("limit", 200)), 1000)
    offset = max(int(request.args.get("offset", 0)), 0)
    q = request.args.get("q", "").strip()
    if q:
        tracks = lib.search(q, limit)
    else:
        tracks = lib.get_all(limit, offset)
        if not tracks and offset == 0:
            try:
                lib.scan_directory(prune=False)
                tracks = lib.get_all(limit, offset)
            except Exception:
                pass
    return jsonify(tracks)


@app.route("/api/recent")
def api_recent():
    lib = _get_library()
    limit = min(int(request.args.get("limit", 30)), 100)
    tracks = lib.get_recent(limit)
    if not tracks:
        try:
            lib.scan_directory(prune=False)
            tracks = lib.get_recent(limit)
        except Exception:
            pass
    return jsonify(tracks)


@app.route("/api/artists")
def api_artists():
    lib = _get_library()
    return jsonify(lib.get_artists())


@app.route("/api/artists/<path:artist_name>/tracks")
def api_artist_tracks(artist_name):
    lib = _get_library()
    decoded = urllib.parse.unquote(artist_name)
    return jsonify(lib.get_tracks_by_artist(decoded))


@app.route("/api/albums")
def api_albums():
    lib = _get_library()
    return jsonify(lib.get_albums())


@app.route("/api/albums/<path:album_name>/tracks")
def api_album_tracks(album_name):
    lib = _get_library()
    decoded = urllib.parse.unquote(album_name)
    artist = request.args.get("artist", "")
    return jsonify(lib.get_tracks_by_album(decoded, artist))


@app.route("/api/tracks/<track_id>")
def api_track(track_id):
    lib = _get_library()
    t = lib.get_track_by_id(track_id)
    if not t:
        return jsonify({"error": "Not found"}), 404
    return jsonify(t)


@app.route("/api/library/rescan", methods=["POST", "GET"])
def api_library_rescan():
    lib = _get_library()
    added = lib.scan_directory(prune=True)
    return jsonify({"scanned": added, "total": lib.count()})


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    cfg = _get_config()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        for k, v in data.items():
            if k in DEFAULTS and k not in ("download_dir",):
                cfg.set_key(k, v)
    return jsonify({
        "user_name": cfg.user_name,
        "output_format": cfg.output_format,
        "quality": cfg.quality,
        "theme": cfg.get_value("theme", "default"),
        "download_dir": str(cfg.download_dir),
        "server_lan": cfg.server_lan,
        "server_port": cfg.server_port,
        "embed_artwork": cfg.embed_artwork,
        "embed_lyrics": cfg.embed_lyrics,
        "duplicate_handling": cfg.duplicate_handling,
    })


# ---------------------------------------------------------------------------
# Artwork & Lyrics
# ---------------------------------------------------------------------------


@app.route("/api/artwork/<path:track_id>")
def api_artwork(track_id):
    res = _find_track_file(track_id)
    if not res:
        return "", 404
    t, fp = res

    # Check memory cache
    with _art_cache_lock:
        if str(fp) in _art_cache:
            data, mime = _art_cache[str(fp)]
            return Response(data, content_type=mime)

    # Extract artwork from audio file
    try:
        from mutagen.flac import FLAC
        from mutagen.id3 import ID3
        from mutagen.mp4 import MP4
        from mutagen.oggopus import OggOpus
        from mutagen.oggvorbis import OggVorbis
        import base64

        ext = fp.suffix.lower()
        data, mime = None, "image/jpeg"

        if ext == ".mp3":
            tags = ID3(fp)
            for k in tags:
                if k.startswith("APIC"):
                    pic = tags[k]
                    data = pic.data
                    mime = getattr(pic, "mime", "image/jpeg")
                    break
        elif ext in (".m4a", ".mp4"):
            audio = MP4(fp)
            covers = audio.tags.get("covr", []) if audio.tags else []
            if covers:
                data = bytes(covers[0])
                mime = "image/png" if getattr(covers[0], "imageformat", None) == 14 else "image/jpeg"
        elif ext == ".flac":
            audio = FLAC(fp)
            if audio.pictures:
                data = audio.pictures[0].data
                mime = audio.pictures[0].mime
        elif ext in (".ogg", ".opus"):
            audio = OggOpus(fp) if ext == ".opus" else OggVorbis(fp)
            raw = audio.get("metadata_block_picture", [""])[0]
            if raw:
                from mutagen.flac import Picture
                pic = Picture(base64.b64decode(raw))
                data = pic.data
                mime = pic.mime

        if data:
            with _art_cache_lock:
                if len(_art_cache) > 200:
                    _art_cache.clear()
                _art_cache[str(fp)] = (data, mime)
            return Response(data, content_type=mime)
    except Exception:
        pass

    return "", 404


@app.route("/api/lyrics/<path:track_id>")
def api_lyrics(track_id):
    res = _find_track_file(track_id)
    if not res:
        return jsonify({"lyrics": ""})
    t, fp = res

    # 1. Try reading embedded lyrics
    try:
        from mutagen.flac import FLAC
        from mutagen.id3 import ID3
        from mutagen.mp4 import MP4
        from mutagen.oggopus import OggOpus
        from mutagen.oggvorbis import OggVorbis

        ext = fp.suffix.lower()
        if ext == ".mp3":
            tags = ID3(fp)
            for k in tags:
                if k.startswith("USLT"):
                    return jsonify({"lyrics": str(tags[k].text)})
        elif ext in (".m4a", ".mp4"):
            audio = MP4(fp)
            if audio.tags and "\xa9lyr" in audio.tags:
                return jsonify({"lyrics": str(audio.tags["\xa9lyr"][0])})
        elif ext == ".flac":
            audio = FLAC(fp)
            lyrics = audio.get("lyrics", [""])[0]
            if lyrics:
                return jsonify({"lyrics": lyrics})
        elif ext in (".ogg", ".opus"):
            audio = OggOpus(fp) if ext == ".opus" else OggVorbis(fp)
            lyrics = audio.get("lyrics", [""])[0]
            if lyrics:
                return jsonify({"lyrics": lyrics})
    except Exception:
        pass

    # 2. Dynamic fetch fallback
    if t:
        from zoink.lyrics import fetch_lyrics
        fetched = fetch_lyrics(
            track_id=t.get("id", ""),
            source=t.get("source", "youtube"),
            title=t.get("title", ""),
            artist=t.get("artist", ""),
            album=t.get("album", ""),
            duration=int(t.get("duration") or 0),
        )
        if fetched:
            return jsonify({"lyrics": fetched})

    return jsonify({"lyrics": ""})


# ---------------------------------------------------------------------------
# Streaming & Downloading Files
# ---------------------------------------------------------------------------


@app.route("/api/stream/<path:target>")
def api_stream(target):
    res = _find_track_file(target)
    if not res:
        return "Not Found", 404
    t, fp = res
    mime = _get_mime(fp)

    # Universal browser compatibility: transcode to MP3 on-the-fly if requested
    req_transcode = request.args.get("transcode", "").lower() or request.args.get("format", "").lower()
    if req_transcode == "mp3" and fp.suffix.lower() != ".mp3" and shutil.which("ffmpeg"):
        cmd = [
            "ffmpeg", "-i", str(fp), "-vn",
            "-c:a", "libmp3lame", "-b:a", "192k",
            "-f", "mp3", "pipe:1",
        ]

        def generate_mp3():
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                while True:
                    chunk = proc.stdout.read(_CHUNK)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    proc.kill()
                except Exception:
                    pass

        headers = {
            "Content-Type": "audio/mpeg",
            "Accept-Ranges": "none",
            "Content-Disposition": f'inline; filename="{fp.stem}.mp3"',
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Range, Content-Type, Accept",
        }
        return Response(generate_mp3(), status=200, headers=headers)

    return _stream_file(fp, mime)


@app.route("/api/file/<path:target>")
def api_file(target):
    res = _find_track_file(target)
    if not res:
        return "Not Found", 404
    t, fp = res
    mime = _get_mime(fp)
    return _stream_file(fp, mime, as_attachment=True)


@app.route("/api/download/<path:target>", methods=["GET", "POST"])
def api_download_legacy(target):
    # Support both direct file download and download triggers
    res = _find_track_file(target)
    if res:
        _, fp = res
        return _stream_file(fp, _get_mime(fp), as_attachment=True)
    # If not a local file, trigger download for online track ID
    return _start_single_download({"id": target})


# ---------------------------------------------------------------------------
# Background Download Operations
# ---------------------------------------------------------------------------


@app.route("/api/download", methods=["POST"])
def api_download_start():
    data = request.get_json() or {}
    track_data = data.get("track") or data
    if not track_data or not track_data.get("id"):
        return jsonify({"error": "Track id is required"}), 400
    return _start_single_download(track_data)


def _start_single_download(track_data: dict) -> Response:
    dm = _get_downloader()
    lib = _get_library()

    track = TrackResult(
        id=track_data.get("id", ""),
        title=track_data.get("title", "Unknown"),
        artist=track_data.get("artist", ""),
        album=track_data.get("album", ""),
        duration=int(track_data.get("duration") or 0),
        artwork_url=track_data.get("artwork_url", ""),
        source=track_data.get("source", "youtube"),
        url=track_data.get("url", ""),
    )

    def _worker():
        job = dm.download(track)
        if job.state == DownloadState.DONE and job.filepath:
            lib.add_track(job.filepath, job.track)

    _bg_pool.submit(_worker)
    return jsonify({"status": "queued", "id": track.id, "title": track.title})


@app.route("/api/download/bulk", methods=["POST"])
def api_download_bulk_start():
    data = request.get_json() or {}
    items = data.get("tracks", [])
    if not items:
        return jsonify({"error": "No tracks provided"}), 400

    dm = _get_downloader()
    lib = _get_library()
    tracks: list[TrackResult] = []

    for item in items:
        t = TrackResult(
            id=item.get("id", ""),
            title=item.get("title", "Unknown"),
            artist=item.get("artist", ""),
            album=item.get("album", ""),
            duration=int(item.get("duration") or 0),
            artwork_url=item.get("artwork_url", ""),
            source=item.get("source", "youtube"),
            url=item.get("url", ""),
        )
        tracks.append(t)

    def _worker():
        def on_complete(job: DownloadJob):
            if job.state == DownloadState.DONE and job.filepath:
                lib.add_track(job.filepath, job.track)
        dm.download_batch(tracks, on_complete=on_complete)

    _bg_pool.submit(_worker)
    return jsonify({"status": "queued", "count": len(tracks)})


@app.route("/api/download/queue")
def api_download_queue():
    dm = _get_downloader()
    return jsonify(dm.get_all_jobs())


@app.route("/api/download/<track_id>", methods=["DELETE"])
def api_download_cancel(track_id):
    dm = _get_downloader()
    ok = dm.cancel_job(track_id)
    return jsonify({"cancelled": ok, "id": track_id})


# ---------------------------------------------------------------------------
# Bulk ZIP Downloads (Safe & Memory-Efficient)
# ---------------------------------------------------------------------------


def _stream_zip_archive(files: list[tuple[Path, str]], zip_name: str) -> Response:
    """Generate a temporary ZIP on disk and stream it without high memory usage."""
    if not files:
        return Response("No matching files found", status=404)

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    try:
        written = 0
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for filepath, arcname in files:
                if filepath.exists() and filepath.is_file():
                    zf.write(filepath, arcname=arcname)
                    written += 1
        if written == 0:
            if tmp_path.exists():
                tmp_path.unlink()
            return Response("No existing files to archive", status=404)
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink()
        return Response(f"Error creating zip: {exc}", status=500)

    try:
        size = tmp_path.stat().st_size
    except OSError:
        return Response("Error archiving files", status=500)

    def generate():
        try:
            with open(tmp_path, "rb") as f:
                while True:
                    chunk = f.read(_CHUNK)
                    if not chunk:
                        break
                    yield chunk
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass

    ascii_zip = zip_name.encode("ascii", "replace").decode("ascii").replace('"', "")
    encoded_zip = urllib.parse.quote(zip_name, safe="")
    headers = {
        "Content-Type": "application/zip",
        "Content-Disposition": f'attachment; filename="{ascii_zip}"; filename*=UTF-8\'\'{encoded_zip}',
        "Content-Length": str(size),
    }
    return Response(generate(), status=200, headers=headers)


@app.route("/api/download-all")
def api_download_all():
    """ZIP archive of all music files in library."""
    lib = _get_library()
    tracks = lib.get_all(limit=2000)
    files: list[tuple[Path, str]] = []
    seen = set()
    for t in tracks:
        fp = Path(t["filepath"])
        if fp.exists() and fp.is_file():
            arc = f"{t.get('artist', 'Artist')} - {t.get('title', fp.stem)}{fp.suffix}"
            if arc in seen:
                arc = f"{t.get('id')}_{arc}"
            seen.add(arc)
            files.append((fp, arc))

    return _stream_zip_archive(files, "ZoinK_Full_Library.zip")


@app.route("/api/albums/<path:album_name>/zip")
def api_download_album_zip(album_name):
    """ZIP archive of a specific album."""
    lib = _get_library()
    decoded = urllib.parse.unquote(album_name)
    artist = request.args.get("artist", "")
    tracks = lib.get_tracks_by_album(decoded, artist)
    files: list[tuple[Path, str]] = []
    seen = set()
    for t in tracks:
        fp = Path(t["filepath"])
        if fp.exists() and fp.is_file():
            num = str(t.get("track_number", "00")).zfill(2)
            arc = f"{num} - {t.get('title', fp.stem)}{fp.suffix}"
            if arc in seen:
                arc = f"{t.get('id')}_{arc}"
            seen.add(arc)
            files.append((fp, arc))

    safe_album = "".join(c for c in decoded if c.isalnum() or c in " -_").strip() or "Album"
    return _stream_zip_archive(files, f"{safe_album}.zip")


@app.route("/api/download-bulk", methods=["POST", "GET"])
@app.route("/api/download-bulk-zip", methods=["POST", "GET"])
def api_download_bulk():
    """ZIP archive of selected track IDs."""
    track_ids: list[str] = []
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        track_ids = data.get("tracks") or data.get("track_ids") or []
    else:
        raw = request.args.get("tracks") or request.args.get("track_ids", "")
        if raw:
            track_ids = [s.strip() for s in raw.split(",") if s.strip()]

    if not track_ids:
        return jsonify({"error": "No tracks specified"}), 400

    lib = _get_library()
    files: list[tuple[Path, str]] = []
    seen = set()
    for tid in track_ids:
        t = lib.get_track_by_id(tid)
        if t and t.get("filepath"):
            fp = Path(t["filepath"])
            if fp.exists() and fp.is_file():
                arc = f"{t.get('artist', 'Artist')} - {t.get('title', fp.stem)}{fp.suffix}"
                if arc in seen:
                    arc = f"{t.get('id')}_{arc}"
                seen.add(arc)
                files.append((fp, arc))

    return _stream_zip_archive(files, "ZoinK_Selected.zip")


def _track_to_dict(t: TrackResult) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "artist": t.artist,
        "album": t.album,
        "album_artist": t.album_artist,
        "duration": t.duration,
        "duration_str": t.duration_str,
        "year": t.year,
        "track_number": t.track_number,
        "disc_number": t.disc_number,
        "artwork_url": t.artwork_url,
        "has_lyrics": t.has_lyrics,
        "source": t.source,
        "url": t.url,
    }


def create_app(config: Optional[Config] = None, library: Optional[Library] = None) -> Flask:
    """Configure and return the Flask application."""
    global _config, _library, _downloader
    if config is not None:
        _config = config
    if library is not None:
        _library = library
    elif _config is not None and _library is None:
        _library = Library(_config)
    if _config is not None and _downloader is None:
        _downloader = DownloadManager(_config)
    return app


def start_server(config: Optional[Config] = None) -> None:
    """Start the ZoinK web server."""
    global _config, _library
    _config = config or Config.get()
    _library = Library(_config)
    _library.scan_directory()

    host = "0.0.0.0" if _config.server_lan else _config.server_host
    port = _config.server_port
    local_ip = _local_ip()

    print(f"\n\033[32mZoinK Web Player\033[0m : made by Ritam/Trixx")
    print(f"  Local:   http://localhost:{port}")
    if _config.server_lan:
        print(f"  Network: http://{local_ip}:{port}")
    print(f"  Library: {_config.download_dir}")
    print(f"  Tracks:  {_library.count()}")
    print(f"\n  Press Ctrl+C to stop.\n")

    app.run(host=host, port=port, debug=False, threaded=True)


_server_thread: Optional[threading.Thread] = None


def start_server_background(config: Optional[Config] = None) -> tuple[bool, int]:
    """Start web server in a background daemon thread if not already running."""
    global _server_thread, _config
    cfg = config or _get_config()
    port = cfg.server_port
    if _server_thread is not None and _server_thread.is_alive():
        return False, port

    create_app(cfg)
    host = "0.0.0.0" if cfg.server_lan else cfg.server_host
    _server_thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False),
        daemon=True,
    )
    _server_thread.start()
    return True, port

