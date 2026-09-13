"""Local music library backed by SQLite with fast incremental indexing."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from zoink.config import Config
from zoink.metadata import read_metadata
from zoink.provider import TrackResult

_DB_LOCK = threading.Lock()
_AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aac"}


class Library:
    """Lightweight, fast music library tracker."""

    def __init__(self, config: Config):
        self.config = config
        self._db_path = config.download_dir / ".zoink_library.db"
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        self.config.download_dir.mkdir(parents=True, exist_ok=True)
        with _DB_LOCK:
            conn = self._conn()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS tracks (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        artist TEXT DEFAULT '',
                        album TEXT DEFAULT '',
                        album_artist TEXT DEFAULT '',
                        composer TEXT DEFAULT '',
                        genre TEXT DEFAULT '',
                        duration INTEGER DEFAULT 0,
                        year INTEGER DEFAULT 0,
                        track_number INTEGER DEFAULT 0,
                        total_tracks INTEGER DEFAULT 0,
                        disc_number INTEGER DEFAULT 0,
                        total_discs INTEGER DEFAULT 0,
                        source TEXT DEFAULT '',
                        filepath TEXT NOT NULL UNIQUE,
                        has_artwork INTEGER DEFAULT 0,
                        has_lyrics INTEGER DEFAULT 0,
                        file_size INTEGER DEFAULT 0,
                        mtime REAL DEFAULT 0,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_artist ON tracks(artist);
                    CREATE INDEX IF NOT EXISTS idx_album ON tracks(album);
                    CREATE INDEX IF NOT EXISTS idx_title ON tracks(title);
                    CREATE INDEX IF NOT EXISTS idx_filepath ON tracks(filepath);
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_filepath_unique ON tracks(filepath);
                    """
                )
                # Auto-migrate any existing database schema
                existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(tracks)").fetchall()}
                col_defs = [
                    ("album_artist", "TEXT DEFAULT ''"),
                    ("composer", "TEXT DEFAULT ''"),
                    ("genre", "TEXT DEFAULT ''"),
                    ("total_tracks", "INTEGER DEFAULT 0"),
                    ("disc_number", "INTEGER DEFAULT 0"),
                    ("total_discs", "INTEGER DEFAULT 0"),
                    ("has_artwork", "INTEGER DEFAULT 0"),
                    ("has_lyrics", "INTEGER DEFAULT 0"),
                    ("file_size", "INTEGER DEFAULT 0"),
                    ("mtime", "REAL DEFAULT 0"),
                ]
                for col_name, col_def in col_defs:
                    if col_name not in existing_cols:
                        conn.execute(f"ALTER TABLE tracks ADD COLUMN {col_name} {col_def}")
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_filepath_unique ON tracks(filepath);")
                conn.commit()
            finally:
                conn.close()

    def _generate_track_id(self, filepath: Path, raw_id: Optional[str] = None) -> str:
        """Generate a stable, unique ID for a track."""
        if raw_id and raw_id.strip():
            # Check if this raw_id already exists for a DIFFERENT filepath
            with self._conn() as conn:
                existing = conn.execute("SELECT filepath FROM tracks WHERE id = ?", (raw_id,)).fetchone()
                if not existing or existing[0] == str(filepath):
                    return raw_id
        # Fallback to hash of filepath
        return hashlib.sha1(str(filepath).encode("utf-8")).hexdigest()[:16]

    def add_track(self, filepath: Path | str, track: Optional[TrackResult] = None) -> bool:
        """Add or update a track in the library. Reads metadata from file if track is None."""
        filepath = Path(filepath)
        if not filepath.exists() or not filepath.is_file():
            return False
        if track is None:
            track = read_metadata(filepath)
        if track is None:
            return False

        try:
            stat = filepath.stat()
            file_size = stat.st_size
            mtime = stat.st_mtime
        except OSError:
            file_size = 0
            mtime = 0

        track_id = self._generate_track_id(filepath, track.id)
        has_artwork = 1 if (track.artwork_url or getattr(track, "has_artwork", False)) else 0
        has_lyrics = 1 if (track.has_lyrics or track.lyrics) else 0

        with _DB_LOCK:
            conn = self._conn()
            try:
                conn.execute(
                    """INSERT INTO tracks
                    (id, title, artist, album, album_artist, composer, genre, duration, year,
                     track_number, total_tracks, disc_number, total_discs, source, filepath,
                     has_artwork, has_lyrics, file_size, mtime)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(filepath) DO UPDATE SET
                        id = excluded.id,
                        title = excluded.title,
                        artist = excluded.artist,
                        album = excluded.album,
                        album_artist = excluded.album_artist,
                        composer = excluded.composer,
                        genre = excluded.genre,
                        duration = excluded.duration,
                        year = excluded.year,
                        track_number = excluded.track_number,
                        total_tracks = excluded.total_tracks,
                        disc_number = excluded.disc_number,
                        total_discs = excluded.total_discs,
                        source = excluded.source,
                        has_artwork = excluded.has_artwork,
                        has_lyrics = excluded.has_lyrics,
                        file_size = excluded.file_size,
                        mtime = excluded.mtime
                    """,
                    (
                        track_id,
                        track.title or filepath.stem,
                        track.artist or "",
                        track.album or "",
                        track.album_artist or "",
                        track.composer or "",
                        track.genre or "",
                        track.duration or 0,
                        track.year or 0,
                        track.track_number or 0,
                        track.total_tracks or 0,
                        track.disc_number or 0,
                        track.total_discs or 0,
                        track.source or "local",
                        str(filepath),
                        has_artwork,
                        has_lyrics,
                        file_size,
                        mtime,
                    ),
                )
                conn.commit()
                return True
            except Exception:
                return False
            finally:
                conn.close()

    def scan_directory(self, directory: Optional[Path] = None, prune: bool = True) -> int:
        """Scan a directory for audio files incrementally. Prunes deleted files if prune=True."""
        d = directory or self.config.download_dir
        if not d.exists():
            return 0

        # Load existing indexed filepaths and mtimes
        existing_mtimes: dict[str, float] = {}
        with _DB_LOCK:
            conn = self._conn()
            try:
                rows = conn.execute("SELECT filepath, mtime FROM tracks").fetchall()
                existing_mtimes = {r[0]: r[1] for r in rows}
            finally:
                conn.close()

        count = 0
        seen_files: set[str] = set()

        for root, _, files in os.walk(d):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in _AUDIO_EXTS:
                    fp = Path(root) / fname
                    fp_str = str(fp)
                    seen_files.add(fp_str)
                    try:
                        cur_mtime = fp.stat().st_mtime
                    except OSError:
                        continue

                    # If mtime matches, file is unchanged — skip expensive tag parsing
                    if fp_str in existing_mtimes and abs(existing_mtimes[fp_str] - cur_mtime) < 0.01:
                        continue

                    if self.add_track(fp):
                        count += 1

        # Prune missing files from library
        if prune:
            missing = set(existing_mtimes.keys()) - seen_files
            if missing:
                with _DB_LOCK:
                    conn = self._conn()
                    try:
                        conn.executemany("DELETE FROM tracks WHERE filepath = ?", [(m,) for m in missing])
                        conn.commit()
                    finally:
                        conn.close()

        return count

    def search(self, query: str, limit: int = 50) -> list[dict]:
        """Search the library by title, artist, or album."""
        q = f"%{query}%"
        with _DB_LOCK:
            conn = self._conn()
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """SELECT * FROM tracks
                    WHERE title LIKE ? OR artist LIKE ? OR album LIKE ?
                    ORDER BY artist, album, track_number
                    LIMIT ?""",
                    (q, q, q, limit),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_all(self, limit: int = 500, offset: int = 0) -> list[dict]:
        """Get all tracks."""
        with _DB_LOCK:
            conn = self._conn()
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """SELECT * FROM tracks
                    ORDER BY added_at DESC
                    LIMIT ? OFFSET ?""",
                    (limit, offset),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_recent(self, limit: int = 20) -> list[dict]:
        """Get recently added tracks."""
        return self.get_all(limit=limit, offset=0)

    def get_artists(self) -> list[dict]:
        """Get distinct artists with track counts."""
        with _DB_LOCK:
            conn = self._conn()
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """SELECT artist, COUNT(*) as track_count
                    FROM tracks WHERE artist != ''
                    GROUP BY artist ORDER BY artist COLLATE NOCASE"""
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_albums(self) -> list[dict]:
        """Get distinct albums with track counts."""
        with _DB_LOCK:
            conn = self._conn()
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """SELECT album, artist, COUNT(*) as track_count, MIN(id) as cover_track_id, MIN(year) as year
                    FROM tracks WHERE album != ''
                    GROUP BY album, artist ORDER BY album COLLATE NOCASE"""
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_tracks_by_artist(self, artist: str) -> list[dict]:
        """Get all tracks by a specific artist."""
        with _DB_LOCK:
            conn = self._conn()
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """SELECT * FROM tracks
                    WHERE artist = ? OR album_artist = ?
                    ORDER BY album, track_number, title""",
                    (artist, artist),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_tracks_by_album(self, album: str, artist: str = "") -> list[dict]:
        """Get all tracks from a specific album."""
        with _DB_LOCK:
            conn = self._conn()
            conn.row_factory = sqlite3.Row
            try:
                if artist:
                    rows = conn.execute(
                        """SELECT * FROM tracks
                        WHERE album = ? AND (artist = ? OR album_artist = ?)
                        ORDER BY disc_number, track_number, title""",
                        (album, artist, artist),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT * FROM tracks
                        WHERE album = ?
                        ORDER BY disc_number, track_number, title""",
                        (album,),
                    ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_track_by_id(self, track_id: str) -> Optional[dict]:
        """Get a single track by ID."""
        with _DB_LOCK:
            conn = self._conn()
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT * FROM tracks WHERE id = ?", (track_id,)
                ).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def has_track_id(self, track_id: str) -> bool:
        """Check if a track ID exists in the library."""
        with _DB_LOCK:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT 1 FROM tracks WHERE id = ? LIMIT 1", (track_id,)
                ).fetchone()
                return row is not None
            finally:
                conn.close()

    def get_track_by_path(self, filepath: str | Path) -> Optional[dict]:
        """Get a single track by its file path."""
        with _DB_LOCK:
            conn = self._conn()
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT * FROM tracks WHERE filepath = ?", (str(filepath),)
                ).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def remove_track(self, track_id: str) -> bool:
        """Remove a track from the library."""
        with _DB_LOCK:
            conn = self._conn()
            try:
                conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
                conn.commit()
                return True
            except Exception:
                return False
            finally:
                conn.close()

    def count(self) -> int:
        """Total track count."""
        with _DB_LOCK:
            conn = self._conn()
            try:
                row = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()
                return row[0] if row else 0
            finally:
                conn.close()

