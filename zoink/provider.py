"""Search provider abstraction.

The UI never understands provider-specific formats. All providers return
normalised TrackResult / AlbumResult objects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TrackResult:
    """Normalised search result for a single track."""

    id: str
    title: str
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    duration: int = 0
    year: int = 0
    track_number: int = 0
    disc_number: int = 0
    artwork_url: str = ""
    has_lyrics: bool = False
    source: str = ""
    url: str = ""
    genre: str = ""
    composer: str = ""
    total_tracks: int = 0
    total_discs: int = 0
    comment: str = ""
    isrc: str = ""
    lyrics: str = ""
    filepath: str = ""

    @property
    def duration_str(self) -> str:
        m, s = divmod(self.duration, 60)
        return f"{m}:{s:02d}" if self.duration else ""


@dataclass
class AlbumResult:
    """Normalised search result for an album."""

    id: str
    title: str
    artist: str = ""
    year: int = 0
    artwork_url: str = ""
    tracks: list[TrackResult] = field(default_factory=list)
    source: str = ""


@dataclass
class MediaStream:
    """Resolved downloadable media stream."""

    url: str
    format_id: str = ""
    ext: str = "mp3"
    audio_bitrate: int = 0
    audio_quality: str = ""
    is_video: bool = False


class SearchProvider(ABC):
    """Abstract base for music search providers."""

    name: str = "base"

    @abstractmethod
    def search_tracks(self, query: str, limit: int = 10) -> list[TrackResult]:
        ...

    @abstractmethod
    def resolve_track(self, track_id: str) -> Optional[TrackResult]:
        ...

    @abstractmethod
    def resolve_album(self, album_id: str) -> Optional[AlbumResult]:
        ...

    @abstractmethod
    def resolve_media(self, track_id: str, audio_format: str = "mp3", quality: str = "best") -> Optional[MediaStream]:
        ...

    def search_albums(self, query: str, limit: int = 10) -> list[AlbumResult]:
        return []
