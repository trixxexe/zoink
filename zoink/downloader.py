"""Download manager with concurrent downloads, progress, retry, and atomic finalization."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from zoink.artwork import fetch_artwork
from zoink.config import Config
from zoink.lyrics import fetch_lyrics
from zoink.metadata import embed_metadata, verify_audio_file
from zoink.provider import TrackResult
from zoink.providers import _base_opts


class DownloadState(Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    METADATA = "metadata"
    FINALIZING = "finalizing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DownloadJob:
    track: TrackResult
    state: DownloadState = DownloadState.PENDING
    progress: float = 0.0
    filepath: Optional[Path] = None
    error: Optional[str] = None
    bytes_downloaded: int = 0
    total_bytes: int = 0
    speed: float = 0.0
    eta: int = 0
    status_text: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.track.id,
            "title": self.track.title,
            "artist": self.track.artist,
            "album": self.track.album,
            "state": self.state.value,
            "progress": round(self.progress, 1),
            "filepath": str(self.filepath) if self.filepath else None,
            "error": self.error,
            "bytes_downloaded": self.bytes_downloaded,
            "total_bytes": self.total_bytes,
            "speed": self.speed,
            "eta": self.eta,
            "status_text": self.status_text,
        }


@dataclass
class DownloadManager:
    """Manages concurrent downloads with progress tracking and robust recovery."""

    config: Config
    _active_jobs: dict[str, DownloadJob] = field(default_factory=dict)
    _completed_jobs: list[DownloadJob] = field(default_factory=list)
    _cancelled_jobs: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _cancelled: bool = False

    def is_cancelled(self, track_id: str) -> bool:
        with self._lock:
            return self._cancelled or (track_id in self._cancelled_jobs)

    def cancel_job(self, track_id: str) -> bool:
        """Cancel a specific download job."""
        with self._lock:
            self._cancelled_jobs.add(track_id)
            job = self._active_jobs.get(track_id)
            if job:
                job.state = DownloadState.CANCELLED
                job.error = "Cancelled by user"
                return True
        return False

    def cancel_all(self) -> None:
        """Cancel all running and queued downloads."""
        with self._lock:
            self._cancelled = True
            for tid, job in self._active_jobs.items():
                self._cancelled_jobs.add(tid)
                job.state = DownloadState.CANCELLED
                job.error = "Cancelled by user"

    def get_active_jobs(self) -> list[DownloadJob]:
        with self._lock:
            return list(self._active_jobs.values())

    def get_completed_jobs(self) -> list[DownloadJob]:
        with self._lock:
            return list(self._completed_jobs)

    def get_all_jobs(self) -> list[dict]:
        with self._lock:
            active = [j.to_dict() for j in self._active_jobs.values()]
            completed = [j.to_dict() for j in self._completed_jobs[-50:]]
            return active + completed

    def download(
        self,
        track: TrackResult,
        on_progress: Optional[Callable[[DownloadJob], None]] = None,
    ) -> DownloadJob:
        """Download a single track synchronously. Returns completed job."""
        with self._lock:
            self._cancelled = False
            self._cancelled_jobs.discard(track.id)
            job = DownloadJob(track=track)
            self._active_jobs[track.id] = job

        try:
            self._execute_download_with_retry(job, on_progress)
        finally:
            with self._lock:
                self._active_jobs.pop(track.id, None)
                self._completed_jobs.append(job)
        return job

    def download_batch(
        self,
        tracks: list[TrackResult],
        on_progress: Optional[Callable[[DownloadJob], None]] = None,
        on_complete: Optional[Callable[[DownloadJob], None]] = None,
    ) -> list[DownloadJob]:
        """Download multiple tracks concurrently."""
        self._cancelled = False
        jobs: list[DownloadJob] = []

        with self._lock:
            for t in tracks:
                self._cancelled_jobs.discard(t.id)
                job = DownloadJob(track=t)
                jobs.append(job)
                self._active_jobs[t.id] = job

        max_workers = max(1, min(self.config.concurrency, len(jobs)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._execute_download_with_retry, j, on_progress): j
                for j in jobs
            }
            for future in as_completed(futures):
                job = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    if self.is_cancelled(job.track.id):
                        job.state = DownloadState.CANCELLED
                        job.error = "Cancelled"
                    else:
                        job.state = DownloadState.FAILED
                        job.error = str(exc)
                if on_complete:
                    on_complete(job)
                with self._lock:
                    self._active_jobs.pop(job.track.id, None)
                    self._completed_jobs.append(job)
        return jobs

    def resolve_target_path(self, track: TrackResult) -> Path:
        """Compute the target file path for a track based on configuration and duplicate rules."""
        fmt = self.config.output_format.lower()
        outtmpl = _build_path(self.config.filename_template, track, fmt, self.config.download_dir)
        path = Path(outtmpl)
        dup_mode = self.config.get_value("duplicate_handling", "skip")
        if path.exists() and dup_mode == "rename":
            counter = 1
            candidate = path
            while candidate.exists():
                candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
                counter += 1
            return candidate
        return path

    def _execute_download_with_retry(
        self,
        job: DownloadJob,
        on_progress: Optional[Callable[[DownloadJob], None]] = None,
    ) -> None:
        """Execute download with automatic retry on transient failure."""
        max_attempts = 2
        for attempt in range(max_attempts):
            if self.is_cancelled(job.track.id):
                job.state = DownloadState.CANCELLED
                job.error = "Cancelled"
                if on_progress:
                    on_progress(job)
                return

            try:
                self._execute_download(job, on_progress)
            except Exception as exc:
                if self.is_cancelled(job.track.id):
                    job.state = DownloadState.CANCELLED
                    job.error = "Cancelled"
                else:
                    job.state = DownloadState.FAILED
                    job.error = str(exc)
                    job.status_text = f"Download error: {exc}"
                if on_progress:
                    on_progress(job)

            if job.state in (DownloadState.DONE, DownloadState.CANCELLED):
                return
            if attempt < max_attempts - 1 and not self.is_cancelled(job.track.id):
                time.sleep(1)

    def _execute_download(
        self,
        job: DownloadJob,
        on_progress: Optional[Callable[[DownloadJob], None]] = None,
    ) -> None:
        cfg = self.config
        out_dir = cfg.download_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        fmt = cfg.output_format.lower()
        quality = cfg.quality

        # Determine target file path based on template
        outtmpl = _build_path(cfg.filename_template, job.track, fmt, out_dir)
        final_path = Path(outtmpl)

        # Duplicate Handling (check if file already exists locally before making network requests)
        dup_mode = cfg.get_value("duplicate_handling", "skip")
        if final_path.exists() and not cfg.overwrite:
            if dup_mode == "skip":
                job.state = DownloadState.DONE
                job.filepath = str(final_path)
                job.progress = 100.0
                job.status_text = "Skipped (already exists)"
                if on_progress:
                    on_progress(job)
                return
            elif dup_mode == "rename":
                counter = 1
                candidate = final_path
                while candidate.exists():
                    candidate = final_path.with_name(f"{final_path.stem} ({counter}){final_path.suffix}")
                    counter += 1
                final_path = candidate

        # Ensure track URL is populated
        if not job.track.url and job.track.id:
            from zoink.providers import YouTubeProvider
            try:
                resolved = YouTubeProvider().resolve_track(job.track.id)
                if resolved and resolved.url:
                    job.track.url = resolved.url
                    if not job.track.title or job.track.title == "Unknown":
                        job.track.title = resolved.title
                    if not job.track.artist:
                        job.track.artist = resolved.artist
                    if not job.track.artwork_url:
                        job.track.artwork_url = resolved.artwork_url
            except Exception as exc:
                job.state = DownloadState.FAILED
                job.error = f"Provider resolution failed: {exc}"
                job.status_text = f"Failed: {exc}"
                if on_progress:
                    on_progress(job)
                return

        if not job.track.url:
            job.state = DownloadState.FAILED
            job.error = f"Could not resolve URL for track '{job.track.title or job.track.id}'"
            job.status_text = "Failed: No URL"
            if on_progress:
                on_progress(job)
            return

        job.state = DownloadState.DOWNLOADING
        job.status_text = "Downloading audio..."
        if on_progress:
            on_progress(job)

        # Create temporary directory for safe atomic download
        tmp_dir = Path(tempfile.mkdtemp(prefix="zoink_"))
        tmp_file = tmp_dir / f"download.{fmt}"

        quality_map = {
            "best": "0",
            "lossless": "0",
            "320": "320",
            "256": "256",
            "192": "192",
            "128": "128",
        }
        q = quality_map.get(quality, "0")

        postprocessors = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": fmt,
                "preferredquality": q,
            }
        ]

        def _hook(data: dict) -> None:
            if self.is_cancelled(job.track.id):
                raise yt_dlp.utils.DownloadError("Cancelled")
            status = data.get("status")
            if status == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                downloaded = data.get("downloaded_bytes") or 0
                job.bytes_downloaded = downloaded
                job.total_bytes = total
                job.speed = float(data.get("speed") or 0.0)
                job.eta = int(data.get("eta") or 0)
                job.progress = (downloaded / total * 100) if total else 0.0
                job.status_text = f"Downloading: {job.progress:.0f}%"
                if on_progress:
                    on_progress(job)
            elif status == "finished":
                job.progress = 100.0
                job.status_text = "Converting audio..."
                if on_progress:
                    on_progress(job)

        # Select best audio format query based on target container
        if fmt == "m4a":
            audio_format = "bestaudio[ext=m4a]/bestaudio/best"
        elif fmt == "opus":
            audio_format = "bestaudio[ext=webm]/bestaudio/best"
        else:
            audio_format = "bestaudio/best"

        # Pass multithreaded FFmpeg arguments for fast conversion
        pp_args = ["-threads", "0"]
        if fmt == "mp3":
            # LAME compression level 7 gives fast encoding while maintaining high audio fidelity
            pp_args.extend(["-compression_level", "7"])
        elif fmt in ("m4a", "aac"):
            pp_args.extend(["-threads", "0"])
        elif fmt == "flac":
            pp_args.extend(["-compression_level", "5"])

        opts = _base_opts(
            format=audio_format,
            outtmpl=str(tmp_file.with_suffix(".%(ext)s")),
            postprocessors=postprocessors,
            postprocessor_args={"default": pp_args},
            concurrent_fragment_downloads=4,
            progress_hooks=[_hook],
            ignoreerrors=False,
            keepvideo=False,
        )

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([job.track.url])
        except yt_dlp.utils.DownloadError as exc:
            if "Cancelled" in str(exc) or self.is_cancelled(job.track.id):
                job.state = DownloadState.CANCELLED
                job.error = "Cancelled by user"
                job.status_text = "Cancelled"
            else:
                job.state = DownloadState.FAILED
                job.error = str(exc)
                job.status_text = f"Download error: {exc}"
            _cleanup(tmp_dir)
            if on_progress:
                on_progress(job)
            return
        except Exception as exc:
            job.state = DownloadState.FAILED
            job.error = str(exc)
            job.status_text = f"Unexpected error: {exc}"
            _cleanup(tmp_dir)
            if on_progress:
                on_progress(job)
            return

        if self.is_cancelled(job.track.id):
            job.state = DownloadState.CANCELLED
            job.error = "Cancelled"
            job.status_text = "Cancelled"
            _cleanup(tmp_dir)
            if on_progress:
                on_progress(job)
            return

        # Locate converted audio file
        downloaded_file = None
        for f in tmp_dir.iterdir():
            if f.is_file() and (f.suffix.lower() == f".{fmt}" or f.suffix.lower() in (".mp3", ".m4a", ".flac", ".opus", ".ogg")):
                downloaded_file = f
                break
        if not downloaded_file or not downloaded_file.exists():
            for f in tmp_dir.iterdir():
                if f.is_file():
                    downloaded_file = f
                    break

        if not downloaded_file or not downloaded_file.exists():
            job.state = DownloadState.FAILED
            job.error = "Download produced no output file"
            job.status_text = "Failed: Missing output"
            _cleanup(tmp_dir)
            if on_progress:
                on_progress(job)
            return

        # Verification of media integrity before finalization
        job.state = DownloadState.VERIFYING
        job.status_text = "Verifying audio integrity..."
        if on_progress:
            on_progress(job)

        if not verify_audio_file(downloaded_file):
            job.state = DownloadState.FAILED
            job.error = "Downloaded audio file failed integrity verification"
            job.status_text = "Failed integrity check"
            _cleanup(tmp_dir)
            if on_progress:
                on_progress(job)
            return

        # Embed metadata, artwork, lyrics
        job.state = DownloadState.METADATA
        job.status_text = "Embedding metadata & artwork..."
        if on_progress:
            on_progress(job)

        artwork_data = None
        lyrics_text = None
        embed_art = cfg.get_value("embed_artwork", True)
        embed_lyr = cfg.get_value("embed_lyrics", True)

        if embed_art or embed_lyr:
            with ThreadPoolExecutor(max_workers=2) as pool:
                art_future = (
                    pool.submit(
                        fetch_artwork,
                        url=job.track.artwork_url,
                        title=job.track.title,
                        artist=job.track.artist,
                        album=job.track.album,
                    )
                    if embed_art
                    else None
                )
                lyr_future = (
                    pool.submit(
                        fetch_lyrics,
                        track_id=job.track.id,
                        source=job.track.source or "youtube",
                        title=job.track.title,
                        artist=job.track.artist,
                        album=job.track.album,
                        duration=job.track.duration,
                    )
                    if embed_lyr
                    else None
                )
                if art_future:
                    try:
                        artwork_data = art_future.result(timeout=10)
                    except Exception:
                        artwork_data = None
                if lyr_future:
                    try:
                        lyrics_text = lyr_future.result(timeout=10)
                    except Exception:
                        lyrics_text = None

        if cfg.get_value("embed_metadata", True):
            embed_metadata(downloaded_file, job.track, artwork_data, lyrics_text)

        # Atomic finalization
        job.state = DownloadState.FINALIZING
        job.status_text = "Finalizing file..."
        if on_progress:
            on_progress(job)

        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            final_path.unlink()
        shutil.move(str(downloaded_file), str(final_path))

        _cleanup(tmp_dir)

        job.state = DownloadState.DONE
        job.filepath = final_path
        job.progress = 100.0
        job.status_text = "Completed"
        if on_progress:
            on_progress(job)


def _build_path(template: str, track: TrackResult, ext: str, base: Path) -> str:
    """Build the output file path from a template."""
    track_num = str(track.track_number).zfill(2) if track.track_number else "00"
    disc_num = str(track.disc_number).zfill(2) if track.disc_number else "01"
    safe = lambda s: _sanitize(str(s)) if s else "Unknown"
    clean_ext = ext.lstrip(".")
    mapping = {
        "{artist}": safe(track.artist or "Unknown Artist"),
        "{album_artist}": safe(track.album_artist or track.artist or "Unknown Artist"),
        "{album}": safe(track.album or "Unknown Album"),
        "{title}": safe(track.title or "Unknown"),
        "{track}": track_num,
        "{disc}": disc_num,
        "{year}": str(track.year) if track.year else "0000",
        "{ext}": clean_ext,
    }
    result = template
    for k, v in mapping.items():
        result = result.replace(k, v)
    if not result.endswith(f".{clean_ext}"):
        result = f"{result}.{clean_ext}"
    return str(base / result)


def _sanitize(name: str) -> str:
    """Sanitize a string for use in filenames."""
    import re
    import unicodedata
    name = unicodedata.normalize("NFKD", name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" ._")
    return name[:200] if name else "Unknown"


def _cleanup(tmp_dir: Path) -> None:
    """Best-effort cleanup of temp directory."""
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass

