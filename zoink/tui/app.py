"""ZoinK TUI Application Engine.

Centered, single-purpose, screen-based terminal music application inspired by
the visual restraint and interaction philosophy of Yoinks.
"""

from __future__ import annotations

import enum
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType

from zoink import __version__
from zoink.config import Config
from zoink.downloader import DownloadJob, DownloadManager, DownloadState
from zoink.library import Library
from zoink.provider import AlbumResult, TrackResult
from zoink.providers import YouTubeProvider
from zoink.tui.theme import THEME_MODES, next_theme_mode


class TUIPhase(enum.Enum):
    INPUT = "input"
    PROBING = "probing"
    SEARCHING = "searching"
    SEARCH_RESULTS = "search_results"
    PICKING = "picking"
    ALBUM = "album"
    DOWNLOADING = "downloading"
    DONE = "done"
    ERROR = "error"
    LIBRARY = "library"
    LIBRARY_DETAIL = "library_detail"
    HELP = "help"
    CONFIG = "config"
    CONVERT = "convert"


SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/library", "Browse and manage your downloaded music"),
    ("/help", "Show commands guide and keyboard controls"),
    ("/theme", "Toggle dark / amoled / cyberpunk / dracula / nord / emerald / rose themes"),
    ("/scan", "Rescan music folder and index tracks"),
    ("/web", "Launch local web player server"),
    ("/config", "Customise settings, download options, and web player name"),
    ("/convert", "Convert a library track to another audio format"),
    ("/quit", "Exit ZoinK cleanly"),
]


@dataclass
class AudioChoice:
    id: str
    label: str
    format: str
    quality: str
    transcode: bool
    badge: str
    description: str
    est_size_mb: Optional[float] = None


def is_probably_url(text: str) -> bool:
    """Check whether an input string looks like a media or playlist URL."""
    t = text.strip()
    return bool(
        t.startswith("http://")
        or t.startswith("https://")
        or t.startswith("www.")
        or "youtu.be/" in t
        or "youtube.com/" in t
    )


class ZoinKTUI:
    """Centered, screen-based TUI state controller and renderer for ZoinK."""

    WATERMARK = ": made by Ritam/Trixx"
    LOGO_LINES = [
        " ┌─┐ ┌─┐ ┬ ┌┐┌ ┬┌─",
        " ┌─┘ │ │ │ │││ ├┴┐",
        " └── └─┘ ┴ ┘└┘ ┴ ┴",
    ]
    TAGLINE = "music downloader for your terminal. search. zoink. done."

    def __init__(
        self,
        config: Optional[Config] = None,
        provider: Optional[YouTubeProvider] = None,
        library: Optional[Library] = None,
        downloader: Optional[DownloadManager] = None,
        dl_manager: Optional[DownloadManager] = None,
        on_invalidate: Optional[Callable[[], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        on_theme_change: Optional[Callable[[str], None]] = None,
        on_request_exit: Optional[Callable[[], None]] = None,
    ):
        self.config = config or Config.get()
        self.provider = provider or YouTubeProvider()
        self.library = library or Library(self.config)
        self.dl_manager = downloader or dl_manager or DownloadManager(self.config)
        self.on_invalidate = on_invalidate or on_refresh
        self.on_theme_change = on_theme_change
        self.on_request_exit = on_request_exit

        # State machine
        self.phase: TUIPhase = TUIPhase.INPUT
        self.prev_phase: TUIPhase = TUIPhase.INPUT
        self.theme_mode: str = "auto"
        self.should_exit: bool = False
        self._shutdown_lock = threading.Lock()
        self._is_shutting_down: bool = False

        # Input screen state
        self.input_text: str = ""
        self.input_cursor: int = 0

        # Probing / Searching state
        self.probing_text: str = "resolving..."

        # Search results state
        self.search_query: str = ""
        self.search_results: list[TrackResult] = []
        self.search_cursor: int = 0

        # Track details / Picking state
        self.selected_track: Optional[TrackResult] = None
        self.audio_choices: list[AudioChoice] = []
        self.choice_index: int = 0

        # Album state
        self.album_result: Optional[AlbumResult] = None
        self.album_cursor: int = 0
        self.album_selected_ids: set[str] = set()

        # Download progress state
        self.download_job: Optional[DownloadJob] = None
        self.download_progress: float = 0.0
        self.download_speed: str = ""
        self.download_eta: str = ""
        self.download_size: str = ""
        self.download_status_text: str = ""
        self.batch_current_idx: int = 1
        self.batch_total_count: int = 1

        # Outcome state
        self.download_outcome_path: str = ""
        self.download_outcome_title: str = ""
        self.download_outcome_artist: str = ""
        self.error_message: str = ""

        # Slash command state
        self.command_cursor: int = 0

        # Library screen state
        self.library_tracks: list[dict] = []
        self.library_cursor: int = 0
        self.library_scroll_offset: int = 0
        self.library_sort_mode: str = "recent"
        self.library_filter_query: str = ""
        self.library_status_message: str = ""
        self.confirm_delete_id: Optional[str] = None
        self.selected_library_track: Optional[dict] = None

        # Playback state
        self.playback_process: Optional[subprocess.Popen] = None
        self.playing_track: Optional[dict] = None
        self.playback_status_text: str = ""
        self._playing_with_termux: bool = False

        # Active background cancel flag
        self.is_cancelled: bool = False

        # Configuration screen state
        self.config_cursor: int = 0
        self.config_editing: bool = False
        self.config_edit_value: str = ""
        self.config_edit_cursor: int = 0
        self.config_status_message: str = ""

        # Converter tool state
        self.convert_track: Optional[dict] = None
        self.convert_target_formats: list[str] = ["mp3", "flac", "m4a", "opus", "ogg", "wav"]
        self.convert_format_index: int = 0
        self.convert_replace_original: bool = True
        self.convert_in_progress: bool = False
        self.convert_progress: float = 0.0
        self.convert_status_text: str = ""
        self.convert_error: str = ""

        # Initialize library tracks on startup
        try:
            self._reload_library_tracks()
        except Exception:
            pass

    def notify(self) -> None:
        """Request UI repaint. No-op if shutting down or exiting."""
        if self.should_exit or self._is_shutting_down:
            return
        if self.on_invalidate:
            try:
                self.on_invalidate()
            except Exception:
                pass

    @property
    def on_refresh(self) -> Optional[Callable[[], None]]:
        """Compatibility property for on_invalidate."""
        return self.on_invalidate

    @on_refresh.setter
    def on_refresh(self, value: Optional[Callable[[], None]]) -> None:
        self.on_invalidate = value

    @property
    def command_suggestions(self) -> list[tuple[str, str]]:
        """Return matching slash commands when input starts with '/'."""
        if not self.input_text.startswith("/"):
            return []
        prefix = self.input_text.strip().lower()
        if prefix == "/" or not prefix:
            return SLASH_COMMANDS
        matches = [c for c in SLASH_COMMANDS if c[0].startswith(prefix)]
        if not matches:
            clean = prefix.lstrip("/")
            matches = [c for c in SLASH_COMMANDS if clean in c[0]]
        return matches

    def request_exit(self) -> None:
        """Signal TUI application to exit cleanly."""
        if self.on_request_exit:
            self.on_request_exit()
        else:
            self.shutdown()

    def shutdown(self) -> None:
        """Perform a graceful, idempotent shutdown of all TUI background resources."""
        with self._shutdown_lock:
            if self._is_shutting_down:
                return
            self._is_shutting_down = True
            self.should_exit = True
            self.is_cancelled = True

        try:
            self.dl_manager.cancel_all()
        except Exception:
            pass

        try:
            self.stop_audio(silent=True)
        except Exception:
            pass

    def insert_text(self, text: str) -> None:
        """Insert text at current input cursor position."""
        if not text:
            return
        if self.phase == TUIPhase.CONFIG and self.config_editing:
            left = self.config_edit_value[:self.config_edit_cursor]
            right = self.config_edit_value[self.config_edit_cursor:]
            self.config_edit_value = left + text + right
            self.config_edit_cursor += len(text)
            self.notify()
            return
        left = self.input_text[:self.input_cursor]
        right = self.input_text[self.input_cursor:]
        self.input_text = left + text + right
        self.input_cursor += len(text)
        self.command_cursor = 0
        self.notify()

    def delete_backwards(self) -> None:
        """Delete character before cursor."""
        if self.phase == TUIPhase.CONFIG and self.config_editing:
            if self.config_edit_cursor > 0:
                left = self.config_edit_value[:self.config_edit_cursor - 1]
                right = self.config_edit_value[self.config_edit_cursor:]
                self.config_edit_value = left + right
                self.config_edit_cursor -= 1
                self.notify()
            return
        if self.input_cursor > 0:
            left = self.input_text[:self.input_cursor - 1]
            right = self.input_text[self.input_cursor:]
            self.input_text = left + right
            self.input_cursor -= 1
            self.command_cursor = 0
            self.notify()

    def delete_forwards(self) -> None:
        """Delete character at cursor."""
        if self.phase == TUIPhase.CONFIG and self.config_editing:
            if self.config_edit_cursor < len(self.config_edit_value):
                left = self.config_edit_value[:self.config_edit_cursor]
                right = self.config_edit_value[self.config_edit_cursor + 1:]
                self.config_edit_value = left + right
                self.notify()
            return
        if self.input_cursor < len(self.input_text):
            left = self.input_text[:self.input_cursor]
            right = self.input_text[self.input_cursor + 1:]
            self.input_text = left + right
            self.command_cursor = 0
            self.notify()

    def delete_word_backwards(self) -> None:
        """Delete word before cursor (Ctrl+W)."""
        if self.phase == TUIPhase.CONFIG and self.config_editing:
            if self.config_edit_cursor <= 0:
                return
            s = self.config_edit_value[:self.config_edit_cursor]
            i = len(s)
            while i > 0 and s[i - 1] == ' ':
                i -= 1
            while i > 0 and s[i - 1] != ' ':
                i -= 1
            new_prefix = s[:i].rstrip()
            self.config_edit_value = new_prefix + self.config_edit_value[self.config_edit_cursor:]
            self.config_edit_cursor = len(new_prefix)
            self.notify()
            return
        if self.input_cursor <= 0:
            return
        s = self.input_text[:self.input_cursor]
        i = len(s)
        while i > 0 and s[i - 1] == ' ':
            i -= 1
        while i > 0 and s[i - 1] != ' ':
            i -= 1
        new_prefix = s[:i].rstrip()
        self.input_text = new_prefix + self.input_text[self.input_cursor:]
        self.input_cursor = len(new_prefix)
        self.command_cursor = 0
        self.notify()

    def move_cursor_left(self) -> None:
        if self.phase == TUIPhase.CONFIG and self.config_editing:
            if self.config_edit_cursor > 0:
                self.config_edit_cursor -= 1
                self.notify()
            return
        if self.input_cursor > 0:
            self.input_cursor -= 1
            self.notify()

    def move_cursor_right(self) -> None:
        if self.phase == TUIPhase.CONFIG and self.config_editing:
            if self.config_edit_cursor < len(self.config_edit_value):
                self.config_edit_cursor += 1
                self.notify()
            return
        if self.input_cursor < len(self.input_text):
            self.input_cursor += 1
            self.notify()

    def move_cursor_home(self) -> None:
        if self.phase == TUIPhase.CONFIG and self.config_editing:
            self.config_edit_cursor = 0
            self.notify()
            return
        self.input_cursor = 0
        self.notify()

    def move_cursor_end(self) -> None:
        if self.phase == TUIPhase.CONFIG and self.config_editing:
            self.config_edit_cursor = len(self.config_edit_value)
            self.notify()
            return
        self.input_cursor = len(self.input_text)
        self.notify()

    def clear_input(self) -> None:
        self.input_text = ""
        self.input_cursor = 0
        self.command_cursor = 0
        self.notify()

    def handle_tab(self) -> None:
        """Autocomplete the highlighted slash command into the input box."""
        if self.phase == TUIPhase.INPUT and self.command_suggestions:
            if 0 <= self.command_cursor < len(self.command_suggestions):
                selected = self.command_suggestions[self.command_cursor][0]
                self.input_text = selected
                self.input_cursor = len(self.input_text)
                self.notify()

    def _click_handler(self, action: Callable[[], None]):
        """Helper to create a MouseEvent handler calling action on MOUSE_UP."""
        def _handler(mouse_event: MouseEvent):
            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                action()
                return None
            return NotImplemented
        return _handler

    # --- Flow Transitions ---

    def handle_submit(self, override_text: Optional[str] = None) -> None:
        """Handle Enter/Submit on the input field."""
        query = (override_text if override_text is not None else self.input_text).strip()
        if not query:
            return

        if query.startswith("/"):
            cmd_to_run = query
            suggs = self.command_suggestions
            if suggs and 0 <= self.command_cursor < len(suggs):
                exact = [c[0] for c in suggs if c[0] == query]
                if exact:
                    cmd_to_run = exact[0]
                else:
                    cmd_to_run = suggs[self.command_cursor][0]
            self._execute_slash_command(cmd_to_run)
            return

        if is_probably_url(query):
            self.start_url_probe(query)
        else:
            self.start_search(query)

    def start_url_probe(self, url: str) -> None:
        """Probe a media or album URL asynchronously."""
        self.is_cancelled = False
        self.prev_phase = self.phase
        self.phase = TUIPhase.PROBING
        self.probing_text = "resolving media url..."
        self.notify()

        def _worker():
            try:
                if "list=" in url or "/album" in url or "/playlist" in url:
                    alb = self.provider.resolve_album(url)
                    if self.is_cancelled or self.should_exit:
                        return
                    if alb and alb.tracks:
                        self.album_result = alb
                        self.album_cursor = 0
                        self.album_selected_ids = {t.id for t in alb.tracks}
                        self.phase = TUIPhase.ALBUM
                        self.notify()
                        return

                track = self.provider.resolve_track(url)
                if self.is_cancelled or self.should_exit:
                    return
                if track:
                    self.inspect_track(track)
                else:
                    self.show_error("Could not resolve media stream from this URL.")
            except Exception as e:
                if not (self.is_cancelled or self.should_exit):
                    self.show_error(f"Failed to inspect URL: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def start_search(self, query: str) -> None:
        """Search music catalog asynchronously."""
        self.is_cancelled = False
        self.search_query = query
        self.prev_phase = self.phase
        self.phase = TUIPhase.SEARCHING
        self.probing_text = f"searching for '{query}'..."
        self.notify()

        def _worker():
            try:
                results = self.provider.search_tracks(query, limit=10)
                if self.is_cancelled or self.should_exit:
                    return
                if not results:
                    self.show_error(f"No matching tracks found for '{query}'.")
                    return
                self.search_results = results
                self.search_cursor = 0
                self.phase = TUIPhase.SEARCH_RESULTS
                self.notify()
            except Exception as e:
                if not (self.is_cancelled or self.should_exit):
                    self.show_error(f"Search failed: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def inspect_track(self, track: TrackResult) -> None:
        """Open track details & download options screen (PICKING)."""
        self.selected_track = track
        self.audio_choices = self._build_audio_choices(track)
        self.choice_index = 0
        self.prev_phase = self.phase
        self.phase = TUIPhase.PICKING
        self.notify()

    def _build_audio_choices(self, track: TrackResult) -> list[AudioChoice]:
        """Construct music-first format and quality options, prioritizing user preferred format."""
        dur = track.duration or 200

        def _mb(kbps: int) -> float:
            return round((kbps * 1000 / 8) * dur / (1024 * 1024), 1)

        pref_fmt = (self.config.output_format or "mp3").lower().lstrip(".")
        pref_q = (self.config.quality or "best").lower()

        choices = [
            AudioChoice(
                id="best",
                label="Best Available Audio",
                format="opus",
                quality="best",
                transcode=False,
                badge="Direct Copy",
                description="Original audio stream · Fastest & highest fidelity",
                est_size_mb=_mb(160),
            ),
            AudioChoice(
                id="flac",
                label="Lossless FLAC",
                format="flac",
                quality="best",
                transcode=True,
                badge="Lossless",
                description="16-bit FLAC archive · Studio master preservation",
                est_size_mb=round(_mb(700), 1),
            ),
            AudioChoice(
                id="mp3_320",
                label="High Quality MP3 (320k)",
                format="mp3",
                quality="320",
                transcode=True,
                badge="320 kbps",
                description="LAME CBR 320 kbps · Maximum device compatibility",
                est_size_mb=_mb(320),
            ),
            AudioChoice(
                id="m4a_256",
                label="Balanced AAC / M4A (256k)",
                format="m4a",
                quality="256",
                transcode=True,
                badge="256 kbps",
                description="Apple / Android native AAC · Clear & balanced",
                est_size_mb=_mb(256),
            ),
            AudioChoice(
                id="opus_160",
                label="Compact Opus (160k)",
                format="opus",
                quality="160",
                transcode=True,
                badge="160 kbps",
                description="Modern Opus codec · Ultra-efficient file size",
                est_size_mb=_mb(160),
            ),
        ]

        # Prioritize preferred format to Choice #0
        pref_idx = -1
        for i, c in enumerate(choices):
            if c.format == pref_fmt:
                pref_idx = i
                break

        if pref_idx > 0:
            c = choices.pop(pref_idx)
            c.badge = f"{c.badge} ★"
            choices.insert(0, c)
        elif pref_idx == -1:
            # Container like ogg or wav
            custom = AudioChoice(
                id=f"{pref_fmt}_pref",
                label=f"{pref_fmt.upper()} (Preferred)",
                format=pref_fmt,
                quality=pref_q,
                transcode=True,
                badge=f"{pref_fmt.upper()} ★",
                description=f"Configured format preference: {pref_fmt.upper()}",
                est_size_mb=_mb(256),
            )
            choices.insert(0, custom)

        return choices

    def trigger_zoink(self) -> None:
        """Initiate download for current track or album."""
        if self.phase == TUIPhase.PICKING:
            if not self.selected_track:
                return
            choice = self.audio_choices[self.choice_index]
            target_fmt = choice.format
            target_q = choice.quality

            self.phase = TUIPhase.DOWNLOADING
            self.download_progress = 0.0
            self.download_speed = ""
            self.download_eta = ""
            self.download_size = ""
            self.download_status_text = "connecting to provider..."
            self.batch_current_idx = 1
            self.batch_total_count = 1
            self.is_cancelled = False
            self.notify()

            track = self.selected_track

            def _on_progress(job: DownloadJob):
                if self.should_exit or self._is_shutting_down:
                    return
                self.download_job = job
                self.download_progress = job.progress
                if job.speed > 0:
                    self.download_speed = f"{job.speed / (1024 * 1024):.1f} MB/s"
                if job.eta > 0:
                    self.download_eta = f"{job.eta}s left"
                if job.bytes_downloaded > 0:
                    self.download_size = f"{job.bytes_downloaded / (1024 * 1024):.1f} MB"
                self.download_status_text = job.status_text or "downloading audio..."

                if job.state == DownloadState.DONE:
                    self.download_outcome_path = str(job.filepath) if job.filepath else ""
                    self.download_outcome_title = track.title
                    self.download_outcome_artist = track.artist
                    if job.filepath:
                        self.library.add_track(Path(job.filepath), track)
                    self.phase = TUIPhase.DONE
                elif job.state == DownloadState.CANCELLED:
                    if self.phase == TUIPhase.DOWNLOADING:
                        self.phase = self.prev_phase if self.prev_phase != TUIPhase.DOWNLOADING else TUIPhase.INPUT
                elif job.state == DownloadState.FAILED:
                    self.show_error(job.error or "Download failed. Please check network.")
                self.notify()

            def _worker():
                try:
                    import inspect
                    sig = inspect.signature(self.dl_manager.download)
                    kwargs = {"on_progress": _on_progress}
                    if "output_format" in sig.parameters:
                        kwargs["output_format"] = target_fmt
                    if "quality" in sig.parameters:
                        kwargs["quality"] = target_q
                    self.config["output_format"] = target_fmt
                    self.config["quality"] = target_q
                    job = self.dl_manager.download(track, **kwargs)
                    if self.should_exit or self._is_shutting_down:
                        return
                    if job.state == DownloadState.DONE and self.phase != TUIPhase.DONE:
                        self.download_outcome_path = str(job.filepath) if job.filepath else ""
                        self.download_outcome_title = track.title
                        self.download_outcome_artist = track.artist
                        if job.filepath:
                            self.library.add_track(Path(job.filepath), track)
                        self.phase = TUIPhase.DONE
                        self.notify()
                    elif job.state == DownloadState.CANCELLED:
                        if self.phase == TUIPhase.DOWNLOADING:
                            self.phase = self.prev_phase if self.prev_phase != TUIPhase.DOWNLOADING else TUIPhase.INPUT
                            self.notify()
                    elif job.state == DownloadState.FAILED and self.phase != TUIPhase.ERROR:
                        self.show_error(job.error or "Download failed. Please check network.")
                except Exception as exc:
                    if self.is_cancelled or self.should_exit:
                        if self.phase == TUIPhase.DOWNLOADING:
                            self.phase = self.prev_phase if self.prev_phase != TUIPhase.DOWNLOADING else TUIPhase.INPUT
                            self.notify()
                    else:
                        self.show_error(f"Download error: {exc}")

            threading.Thread(target=_worker, daemon=True).start()

        elif self.phase == TUIPhase.ALBUM:
            if not self.album_result or not self.album_result.tracks:
                return
            selected = [t for t in self.album_result.tracks if t.id in self.album_selected_ids]
            if not selected:
                selected = list(self.album_result.tracks)

            self.phase = TUIPhase.DOWNLOADING
            self.download_progress = 0.0
            self.download_speed = ""
            self.download_eta = ""
            self.download_size = ""
            self.batch_current_idx = 0
            self.batch_total_count = len(selected)
            self.download_status_text = f"starting album download (0/{len(selected)})..."
            self.is_cancelled = False
            self.notify()

            def _on_batch_complete(job: DownloadJob):
                if self.should_exit or self._is_shutting_down:
                    return
                if job.state == DownloadState.DONE and job.filepath:
                    self.library.add_track(Path(job.filepath), job.track)
                self.batch_current_idx = min(self.batch_current_idx + 1, self.batch_total_count)
                self.download_progress = (self.batch_current_idx / self.batch_total_count) * 100
                self.download_status_text = f"downloaded {job.track.title} ({self.batch_current_idx}/{self.batch_total_count})"
                self.notify()

            def _batch_worker():
                try:
                    import inspect
                    sig = inspect.signature(self.dl_manager.download_batch)
                    kwargs = {"on_complete": _on_batch_complete}
                    if "output_format" in sig.parameters:
                        kwargs["output_format"] = self.config.output_format
                    if "quality" in sig.parameters:
                        kwargs["quality"] = self.config.quality
                    jobs = self.dl_manager.download_batch(
                        selected,
                        **kwargs,
                    )
                    if self.is_cancelled or self.should_exit:
                        if self.phase == TUIPhase.DOWNLOADING and not self.should_exit:
                            self.phase = self.prev_phase if self.prev_phase != TUIPhase.DOWNLOADING else TUIPhase.INPUT
                            self.notify()
                        return
                    self.download_outcome_title = self.album_result.title if self.album_result else "Album"
                    self.download_outcome_artist = self.album_result.artist if self.album_result else "Various Artists"
                    self.download_outcome_path = str(self.config.download_dir)
                    self.phase = TUIPhase.DONE
                    self.notify()
                except Exception as exc:
                    if self.is_cancelled or self.should_exit:
                        if self.phase == TUIPhase.DOWNLOADING and not self.should_exit:
                            self.phase = self.prev_phase if self.prev_phase != TUIPhase.DOWNLOADING else TUIPhase.INPUT
                            self.notify()
                    else:
                        self.show_error(f"Album download error: {exc}")

            threading.Thread(target=_batch_worker, daemon=True).start()

    def cancel_current(self, silent: bool = False) -> None:
        """Cancel the active operation and return to previous state."""
        self.is_cancelled = True
        try:
            self.dl_manager.cancel_all()
        except Exception:
            pass
        if self.phase == TUIPhase.DOWNLOADING:
            self.phase = self.prev_phase if self.prev_phase != TUIPhase.DOWNLOADING else TUIPhase.INPUT
        elif self.phase in (TUIPhase.PROBING, TUIPhase.SEARCHING):
            self.phase = self.prev_phase if self.prev_phase not in (TUIPhase.PROBING, TUIPhase.SEARCHING) else TUIPhase.INPUT
        else:
            self.phase = TUIPhase.INPUT
        if not silent and not self.should_exit:
            self.notify()

    def show_error(self, message: str) -> None:
        """Display an error screen with a human-readable explanation."""
        self.error_message = message
        self.phase = TUIPhase.ERROR
        self.notify()

    def go_home(self) -> None:
        """Reset input and return to the home screen."""
        self.phase = TUIPhase.INPUT
        self.input_text = ""
        self.input_cursor = 0
        self.command_cursor = 0
        self.selected_track = None
        self.album_result = None
        self.search_results.clear()
        self.notify()

    def _execute_slash_command(self, cmd: str) -> None:
        """Execute a slash command typed or selected in the input."""
        parts = cmd.strip().lower().split()
        if not parts:
            return
        c = parts[0]
        self.clear_input()

        if c in ("/library", "/lib"):
            self.open_library(rescan=True)
        elif c in ("/help", "/h", "/?"):
            self.open_help()
        elif c in ("/theme", "/t"):
            self.handle_cycle_theme()
        elif c in ("/scan", "/rescan"):
            try:
                count = self.library.scan_directory(prune=True)
                self.open_library(rescan=False)
                self.library_status_message = f"Scanned music folder: {count} new tracks added"
                self.notify()
            except Exception as e:
                self.show_error(f"Failed to scan directory: {e}")
        elif c in ("/web", "/server"):
            self.open_web_player()
        elif c in ("/config", "/cfg", "/settings", "/preferences"):
            self.open_config()
        elif c in ("/convert", "/transcode"):
            self.open_convert()
        elif c in ("/quit", "/exit", "/q"):
            self.request_exit()
        elif c in ("/clear", "/c"):
            self.clear_input()
        else:
            self.show_error(f"Unknown command '{c}'. Type /help for available commands.")

    def open_help(self) -> None:
        """Open the interactive help and commands reference screen."""
        self.prev_phase = self.phase
        self.phase = TUIPhase.HELP
        self.notify()

    def open_config(self) -> None:
        """Switch to the interactive configuration / settings view."""
        self.prev_phase = self.phase
        self.phase = TUIPhase.CONFIG
        self.config_cursor = 0
        self.config_editing = False
        self.config_edit_value = ""
        self.config_edit_cursor = 0
        self.config_status_message = ""
        self.notify()

    def open_convert(self, track: Optional[dict] = None) -> None:
        """Open the interactive audio format conversion screen for a track."""
        if track is None:
            if self.phase == TUIPhase.LIBRARY_DETAIL and self.selected_library_track:
                track = self.selected_library_track
            elif self.library_tracks and 0 <= self.library_cursor < len(self.library_tracks):
                track = self.library_tracks[self.library_cursor]
            else:
                self.library_status_message = "No track selected to convert. Browse library first."
                self.open_library(rescan=False)
                return

        self.convert_track = track
        self.convert_format_index = 0
        self.convert_replace_original = True
        self.convert_in_progress = False
        self.convert_progress = 0.0
        self.convert_status_text = ""
        self.convert_error = ""
        self.prev_phase = self.phase
        self.phase = TUIPhase.CONVERT
        self.notify()

    def cancel_convert(self) -> None:
        """Exit the converter screen and return to the previous view."""
        if self.convert_in_progress:
            return
        if self.prev_phase in (TUIPhase.LIBRARY, TUIPhase.LIBRARY_DETAIL):
            self.phase = self.prev_phase
        else:
            self.phase = TUIPhase.LIBRARY
        self.notify()

    def handle_convert_up(self) -> None:
        if not self.convert_in_progress and self.convert_format_index > 0:
            self.convert_format_index -= 1
            self.notify()

    def handle_convert_down(self) -> None:
        if not self.convert_in_progress and self.convert_format_index < len(self.convert_target_formats) - 1:
            self.convert_format_index += 1
            self.notify()

    def handle_toggle_convert_replace(self) -> None:
        if not self.convert_in_progress:
            self.convert_replace_original = not self.convert_replace_original
            self.notify()

    def _select_convert_format(self, idx: int) -> None:
        if not self.convert_in_progress and 0 <= idx < len(self.convert_target_formats):
            self.convert_format_index = idx
            self.notify()

    def start_convert(self) -> None:
        """Initiate audio conversion in a background thread."""
        if self.convert_in_progress or not self.convert_track:
            return
        self.convert_in_progress = True
        self.convert_error = ""
        self.convert_progress = 5.0
        target_fmt = self.convert_target_formats[self.convert_format_index]
        self.convert_status_text = f"Preparing to convert to {target_fmt.upper()}..."
        self.notify()

        track = self.convert_track
        replace = self.convert_replace_original
        track_id_or_path = track.get("filepath") or track.get("id")

        def _worker():
            try:
                from zoink.converter import convert_library_track

                def _on_prog(pct: float, msg: str):
                    self.convert_progress = pct
                    self.convert_status_text = msg
                    self.notify()

                success, dest_path, err = convert_library_track(
                    library=self.library,
                    track_id_or_path=track_id_or_path,
                    target_format=target_fmt,
                    quality=self.config.quality or "best",
                    replace_original=replace,
                    on_progress=_on_prog,
                )

                if self.should_exit or self._is_shutting_down:
                    return

                if success and dest_path:
                    self.convert_in_progress = False
                    self.convert_status_text = f"Converted to {target_fmt.upper()} successfully!"
                    self.convert_progress = 100.0
                    self._reload_library_tracks()
                    self.library_status_message = f"Converted '{track.get('title', 'track')}' to {target_fmt.upper()}"
                    self.phase = TUIPhase.LIBRARY
                else:
                    self.convert_in_progress = False
                    self.convert_error = err or f"Failed to convert audio to {target_fmt.upper()}."
                    self.convert_status_text = ""
            except Exception as exc:
                if not (self.should_exit or self._is_shutting_down):
                    self.convert_in_progress = False
                    self.convert_error = str(exc)
            finally:
                self.notify()

        threading.Thread(target=_worker, daemon=True).start()

    def _get_config_items(self) -> list[dict]:
        """Return structured configuration items for user customization."""
        return [
            {
                "key": "user_name",
                "label": "Web Player Name",
                "type": "text",
                "value": self.config.user_name,
                "desc": "Display name in web player greeting ('Good evening, <Name>')",
            },
            {
                "key": "output_format",
                "label": "Audio Format",
                "type": "choice",
                "choices": ["mp3", "m4a", "opus", "flac", "ogg", "wav"],
                "value": self.config.output_format,
                "desc": "Target container format for downloaded audio",
            },
            {
                "key": "quality",
                "label": "Audio Quality",
                "type": "choice",
                "choices": ["best", "320k", "256k", "192k", "128k"],
                "value": self.config.quality,
                "desc": "Bitrate / quality profile for conversion",
            },
            {
                "key": "theme",
                "label": "Theme Mode",
                "type": "choice",
                "choices": list(THEME_MODES),
                "value": self.theme_mode,
                "desc": "TUI color scheme (auto detects terminal background)",
            },
            {
                "key": "embed_artwork",
                "label": "Embed Artwork",
                "type": "toggle",
                "value": self.config.embed_artwork,
                "desc": "Embed cover art directly into downloaded audio tags",
            },
            {
                "key": "embed_lyrics",
                "label": "Embed Lyrics",
                "type": "toggle",
                "value": self.config.embed_lyrics,
                "desc": "Fetch and embed synced/plain lyrics into audio tags",
            },
            {
                "key": "download_dir",
                "label": "Music Folder",
                "type": "text",
                "value": str(self.config.download_dir),
                "desc": "Local folder where downloaded audio files are saved",
            },
            {
                "key": "server_lan",
                "label": "LAN Web Player",
                "type": "toggle",
                "value": self.config.server_lan,
                "desc": "Allow other devices on local network to access web player",
            },
            {
                "key": "duplicate_handling",
                "label": "Duplicate Files",
                "type": "choice",
                "choices": ["skip", "overwrite", "rename"],
                "value": self.config.duplicate_handling,
                "desc": "Action when target audio file already exists on disk",
            },
        ]

    def handle_cycle_config(self, forward: bool = True) -> None:
        """Cycle or toggle the currently selected configuration setting."""
        items = self._get_config_items()
        if not (0 <= self.config_cursor < len(items)):
            return
        item = items[self.config_cursor]
        key = item["key"]
        itype = item["type"]

        if itype == "toggle":
            new_val = not bool(item["value"])
            self._save_config_key(key, new_val, item["label"])
        elif itype == "choice":
            choices = item.get("choices", [])
            if not choices:
                return
            cur = str(item["value"]).lower()
            try:
                idx = choices.index(cur)
            except ValueError:
                idx = 0
            step = 1 if forward else -1
            new_idx = (idx + step) % len(choices)
            new_val = choices[new_idx]
            self._save_config_key(key, new_val, item["label"])
        elif itype == "text":
            self.handle_edit_config()

    def handle_edit_config(self) -> None:
        """Enter inline editing mode for text configuration fields."""
        items = self._get_config_items()
        if not (0 <= self.config_cursor < len(items)):
            return
        item = items[self.config_cursor]
        if item["type"] == "text":
            self.config_editing = True
            self.config_edit_value = str(item["value"])
            self.config_edit_cursor = len(self.config_edit_value)
            self.config_status_message = f"Editing {item['label']}: press Enter to save, Esc to cancel"
            self.notify()
        else:
            self.handle_cycle_config(forward=True)

    def _save_config_key(self, key: str, value: Any, label: str) -> None:
        """Save a setting to Config and update runtime state."""
        try:
            self.config.set_key(key, value)
            if key == "theme":
                self.theme_mode = str(value)
                if self.on_theme_change:
                    self.on_theme_change(self.theme_mode)
            display_val = "✓ enabled" if value is True else ("✗ disabled" if value is False else str(value))
            self.config_status_message = f"✓ Saved: {label} → {display_val}"
            self.notify()
        except Exception as e:
            self.config_status_message = f"Failed to save setting: {e}"
            self.notify()

    def handle_left(self) -> None:
        """Handle left arrow key in non-typing phases."""
        if self.phase == TUIPhase.CONFIG and not self.config_editing:
            self.handle_cycle_config(forward=False)

    def handle_right(self) -> None:
        """Handle right arrow key in non-typing phases."""
        if self.phase == TUIPhase.CONFIG and not self.config_editing:
            self.handle_cycle_config(forward=True)

    def open_library(self, rescan: bool = True) -> None:
        """Switch to the library view."""
        self.prev_phase = self.phase
        self.phase = TUIPhase.LIBRARY
        self.confirm_delete_id = None
        self.library_status_message = ""
        if rescan:
            try:
                self.library.scan_directory(prune=True)
            except Exception:
                pass
        self._reload_library_tracks()
        self.library_cursor = 0
        self.library_scroll_offset = 0
        self.notify()

    def _reload_library_tracks(self) -> None:
        """Reload tracks from SQLite DB according to sort and filter settings."""
        try:
            if self.library_filter_query:
                tracks = self.library.search(self.library_filter_query, limit=500)
            else:
                tracks = self.library.get_all(limit=500)
                if self.library_sort_mode == "title":
                    tracks.sort(key=lambda t: (t.get("title") or "").lower())
                elif self.library_sort_mode == "artist":
                    tracks.sort(key=lambda t: (t.get("artist") or "").lower())
            self.library_tracks = tracks
        except Exception:
            self.library_tracks = []

    def handle_inspect(self) -> None:
        """Open details screen for selected track in library."""
        if self.library_tracks and 0 <= self.library_cursor < len(self.library_tracks):
            self.selected_library_track = self.library_tracks[self.library_cursor]
            self.prev_phase = self.phase
            self.phase = TUIPhase.LIBRARY_DETAIL
            self.notify()

    def handle_play(self) -> None:
        """Toggle playback of the selected library track."""
        if self.playback_process:
            self.stop_audio()
            return
        track = None
        if self.phase == TUIPhase.LIBRARY and self.library_tracks and 0 <= self.library_cursor < len(self.library_tracks):
            track = self.library_tracks[self.library_cursor]
        elif self.phase == TUIPhase.LIBRARY_DETAIL:
            track = self.selected_library_track

        if track:
            self.play_audio(track)

    def handle_stop(self) -> None:
        """Stop playback immediately."""
        self.stop_audio()

    def play_audio(self, track: dict) -> None:
        """Play the selected track in background using system media player."""
        self.stop_audio()
        filepath = track.get("filepath")
        if not filepath or not os.path.exists(filepath):
            self.library_status_message = "File not found on disk."
            self.notify()
            return

        players = [
            ("mpv", ["mpv", "--no-video", "--really-quiet", filepath]),
            ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", filepath]),
            ("termux-media-player", ["termux-media-player", "play", filepath]),
            ("paplay", ["paplay", filepath]),
            ("aplay", ["aplay", filepath]),
        ]
        for name, cmd in players:
            if shutil.which(name):
                try:
                    self.playback_process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    self._playing_with_termux = (name == "termux-media-player")
                    self.playing_track = track
                    self.playback_status_text = f"▶ Playing: {track.get('title', 'Unknown')} — {track.get('artist', 'Unknown')}"
                    self.notify()
                    return
                except Exception:
                    continue

        self.library_status_message = "No media player found (mpv/ffplay/termux-media-player)."
        self.notify()

    def stop_audio(self, silent: bool = False) -> None:
        """Stop any active audio playback."""
        if self.playback_process:
            try:
                self.playback_process.terminate()
                self.playback_process.wait(timeout=0.1)
            except Exception:
                try:
                    self.playback_process.kill()
                except Exception:
                    pass
            self.playback_process = None

        if self._playing_with_termux and shutil.which("termux-media-player"):
            try:
                subprocess.run(
                    ["termux-media-player", "stop"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1,
                )
            except Exception:
                pass
            self._playing_with_termux = False

        self.playing_track = None
        self.playback_status_text = ""
        if not silent and not self.should_exit:
            self.notify()

    def handle_delete(self) -> None:
        """Request deletion confirmation for current track."""
        track = None
        if self.phase == TUIPhase.LIBRARY and self.library_tracks and 0 <= self.library_cursor < len(self.library_tracks):
            track = self.library_tracks[self.library_cursor]
        elif self.phase == TUIPhase.LIBRARY_DETAIL:
            track = self.selected_library_track

        if track:
            self.confirm_delete_id = track.get("id")
            self.library_status_message = f"Delete '{track.get('title')}'? [y] Yes  [n] No"
            self.notify()

    def handle_confirm_yes(self) -> None:
        """Confirm and execute track deletion from disk and library."""
        if not self.confirm_delete_id:
            return
        track = self.library.get_track_by_id(self.confirm_delete_id)
        if track:
            if self.playing_track and self.playing_track.get("id") == track.get("id"):
                self.stop_audio()
            fp_str = track.get("filepath", "")
            if fp_str:
                try:
                    p = Path(fp_str)
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass
            self.library.remove_track(track["id"])
            self.library_status_message = f"Deleted '{track.get('title')}'"

        self.confirm_delete_id = None
        self._reload_library_tracks()
        if self.library_cursor >= len(self.library_tracks):
            self.library_cursor = max(0, len(self.library_tracks) - 1)
        if self.phase == TUIPhase.LIBRARY_DETAIL:
            self.phase = TUIPhase.LIBRARY
        self.notify()

    def handle_confirm_no(self) -> None:
        """Cancel delete confirmation."""
        self.confirm_delete_id = None
        self.library_status_message = ""
        self.notify()

    def handle_sort(self) -> None:
        """Cycle sort order between recent, title, artist."""
        modes = ["recent", "title", "artist"]
        idx = modes.index(self.library_sort_mode) if self.library_sort_mode in modes else 0
        self.library_sort_mode = modes[(idx + 1) % len(modes)]
        self._reload_library_tracks()
        self.library_cursor = 0
        self.library_scroll_offset = 0
        self.library_status_message = f"Sort: {self.library_sort_mode}"
        self.notify()

    def handle_rescan(self) -> None:
        """Rescan music folder and reload tracks."""
        count = self.library.scan_directory(prune=True)
        self._reload_library_tracks()
        self.library_status_message = f"Rescanned: {count} new tracks ({len(self.library_tracks)} total)"
        self.notify()

    def handle_page_up(self) -> None:
        if self.phase == TUIPhase.LIBRARY:
            self.library_cursor = max(0, self.library_cursor - 8)
            if self.library_cursor < self.library_scroll_offset:
                self.library_scroll_offset = self.library_cursor
            self.notify()

    def handle_page_down(self) -> None:
        if self.phase == TUIPhase.LIBRARY and self.library_tracks:
            self.library_cursor = min(len(self.library_tracks) - 1, self.library_cursor + 8)
            max_vis = 8
            if self.library_cursor >= self.library_scroll_offset + max_vis:
                self.library_scroll_offset = self.library_cursor - max_vis + 1
            self.notify()

    def open_web_player(self) -> None:
        """Start background web player server."""
        try:
            from zoink.web import start_server_background
            started, port = start_server_background(self.config)
            self.download_status_text = f"Web player active at http://localhost:{port}"
        except Exception as e:
            self.download_status_text = f"Could not start web player: {e}"
        self.notify()

    def handle_cycle_theme(self) -> None:
        """Cycle visual theme between auto, dark, and light."""
        self.theme_mode = next_theme_mode(self.theme_mode)
        if self.on_theme_change:
            try:
                self.on_theme_change(self.theme_mode)
            except Exception:
                pass
        self.notify()

    # --- Navigation / Keyboard Actions ---

    def handle_up(self) -> None:
        if self.phase == TUIPhase.INPUT:
            suggs = self.command_suggestions
            if suggs:
                if self.command_cursor > 0:
                    self.command_cursor -= 1
                else:
                    self.command_cursor = len(suggs) - 1
        elif self.phase == TUIPhase.SEARCH_RESULTS:
            if self.search_cursor > 0:
                self.search_cursor -= 1
        elif self.phase == TUIPhase.PICKING:
            if self.choice_index > 0:
                self.choice_index -= 1
        elif self.phase == TUIPhase.ALBUM:
            if self.album_cursor > 0:
                self.album_cursor -= 1
        elif self.phase == TUIPhase.LIBRARY:
            if self.library_cursor > 0:
                self.library_cursor -= 1
                if self.library_cursor < self.library_scroll_offset:
                    self.library_scroll_offset = self.library_cursor
        elif self.phase == TUIPhase.CONFIG:
            if not self.config_editing:
                if self.config_cursor > 0:
                    self.config_cursor -= 1
        elif self.phase == TUIPhase.CONVERT:
            self.handle_convert_up()
        self.notify()

    def handle_down(self) -> None:
        if self.phase == TUIPhase.INPUT:
            suggs = self.command_suggestions
            if suggs:
                if self.command_cursor < len(suggs) - 1:
                    self.command_cursor += 1
                else:
                    self.command_cursor = 0
        elif self.phase == TUIPhase.SEARCH_RESULTS:
            if self.search_cursor < len(self.search_results) - 1:
                self.search_cursor += 1
        elif self.phase == TUIPhase.PICKING:
            if self.choice_index < len(self.audio_choices) - 1:
                self.choice_index += 1
        elif self.phase == TUIPhase.ALBUM:
            max_c = len(self.album_result.tracks) - 1 if self.album_result and self.album_result.tracks else 0
            if self.album_cursor < max_c:
                self.album_cursor += 1
        elif self.phase == TUIPhase.LIBRARY:
            if self.library_cursor < len(self.library_tracks) - 1:
                self.library_cursor += 1
                max_vis = 8
                if self.library_cursor >= self.library_scroll_offset + max_vis:
                    self.library_scroll_offset = self.library_cursor - max_vis + 1
        elif self.phase == TUIPhase.CONFIG:
            if not self.config_editing:
                if self.config_cursor < len(self._get_config_items()) - 1:
                    self.config_cursor += 1
        elif self.phase == TUIPhase.CONVERT:
            self.handle_convert_down()
        self.notify()

    def handle_enter(self) -> None:
        if self.should_exit or self._is_shutting_down:
            return
        if self.phase == TUIPhase.INPUT:
            self.handle_submit()
        elif self.phase == TUIPhase.SEARCH_RESULTS:
            if self.search_results and 0 <= self.search_cursor < len(self.search_results):
                self.inspect_track(self.search_results[self.search_cursor])
        elif self.phase == TUIPhase.PICKING:
            self.trigger_zoink()
        elif self.phase == TUIPhase.ALBUM:
            self.trigger_zoink()
        elif self.phase == TUIPhase.LIBRARY:
            if self.confirm_delete_id:
                self.handle_confirm_yes()
            else:
                self.handle_inspect()
        elif self.phase == TUIPhase.LIBRARY_DETAIL:
            self.handle_play()
        elif self.phase == TUIPhase.CONVERT:
            if not self.convert_in_progress:
                self.start_convert()
        elif self.phase == TUIPhase.CONFIG:
            if self.config_editing:
                items = self._get_config_items()
                if 0 <= self.config_cursor < len(items):
                    item = items[self.config_cursor]
                    new_val = self.config_edit_value.strip()
                    if item["key"] == "user_name" and not new_val:
                        new_val = "Music Lover"
                    self._save_config_key(item["key"], new_val, item["label"])
                self.config_editing = False
                self.notify()
            else:
                items = self._get_config_items()
                if 0 <= self.config_cursor < len(items):
                    item = items[self.config_cursor]
                    if item["type"] == "text":
                        self.handle_edit_config()
                    else:
                        self.handle_cycle_config(forward=True)
        elif self.phase in (TUIPhase.DONE, TUIPhase.ERROR, TUIPhase.HELP):
            self.go_home()

    def handle_escape(self) -> None:
        if self.should_exit or self._is_shutting_down:
            return
        if self.phase == TUIPhase.LIBRARY:
            if self.confirm_delete_id:
                self.handle_confirm_no()
            else:
                self.go_home()
        elif self.phase == TUIPhase.LIBRARY_DETAIL:
            self.phase = TUIPhase.LIBRARY
            self.notify()
        elif self.phase == TUIPhase.HELP:
            self.go_home()
        elif self.phase == TUIPhase.CONVERT:
            self.cancel_convert()
        elif self.phase == TUIPhase.CONFIG:
            if self.config_editing:
                self.config_editing = False
                self.config_status_message = "Cancelled editing."
                self.notify()
            else:
                self.go_home()
        elif self.phase == TUIPhase.SEARCH_RESULTS:
            self.go_home()
        elif self.phase == TUIPhase.PICKING:
            if self.search_results:
                self.phase = TUIPhase.SEARCH_RESULTS
            else:
                self.go_home()
        elif self.phase == TUIPhase.ALBUM:
            if self.search_results:
                self.phase = TUIPhase.SEARCH_RESULTS
            else:
                self.go_home()
        elif self.phase in (TUIPhase.DOWNLOADING, TUIPhase.PROBING, TUIPhase.SEARCHING):
            self.cancel_current()
        elif self.phase in (TUIPhase.DONE, TUIPhase.ERROR):
            self.go_home()
        self.notify()

    def handle_space(self) -> None:
        if self.phase == TUIPhase.ALBUM and self.album_result and self.album_result.tracks:
            track = self.album_result.tracks[self.album_cursor]
            if track.id in self.album_selected_ids:
                self.album_selected_ids.remove(track.id)
            else:
                self.album_selected_ids.add(track.id)
            self.notify()
        elif self.phase in (TUIPhase.LIBRARY, TUIPhase.LIBRARY_DETAIL):
            self.handle_play()
        elif self.phase == TUIPhase.CONVERT:
            self.handle_toggle_convert_replace()
        elif self.phase == TUIPhase.CONFIG:
            if not self.config_editing:
                self.handle_cycle_config(forward=True)

    def handle_album_action(self) -> None:
        """Resolve and open album for the currently selected track."""
        track = None
        if self.phase == TUIPhase.SEARCH_RESULTS and self.search_results:
            track = self.search_results[self.search_cursor]
        elif self.phase == TUIPhase.PICKING:
            track = self.selected_track

        if not track:
            return

        query = f"{track.artist} {track.album or track.title}".strip()
        self.prev_phase = self.phase
        self.phase = TUIPhase.PROBING
        self.probing_text = f"resolving album for '{track.title}'..."
        self.notify()

        def _alb_worker():
            try:
                alb = self.provider.resolve_album(query)
                if self.is_cancelled or self.should_exit:
                    return
                if alb and alb.tracks:
                    self.album_result = alb
                    self.album_cursor = 0
                    self.album_selected_ids = {t.id for t in alb.tracks}
                    self.phase = TUIPhase.ALBUM
                else:
                    self.show_error(f"Could not resolve full album for '{track.title}'.")
            except Exception as e:
                if not (self.is_cancelled or self.should_exit):
                    self.show_error(f"Album lookup error: {e}")
            if not (self.is_cancelled or self.should_exit):
                self.notify()

        threading.Thread(target=_alb_worker, daemon=True).start()

    # --- Screen Renderers ---

    def render(self, width: int = 80, height: int = 24) -> FormattedText:
        """Render the complete centered screen layout."""
        width = max(width, 40)
        height = max(height, 14)

        if self.phase == TUIPhase.INPUT:
            content_lines = self._render_input_screen(width, height)
            if self.command_suggestions:
                footer_hints = [("↑↓", "choose"), ("tab", "autocomplete"), ("↵", "run"), ("esc", "clear"), ("^c", "quit")]
            else:
                footer_hints = [("↵", "zoink"), ("/help", "commands"), ("^l", "library"), ("^t", "theme"), ("^c", "quit")]
        elif self.phase in (TUIPhase.PROBING, TUIPhase.SEARCHING):
            content_lines = self._render_probing_screen(width)
            footer_hints = [("esc", "cancel"), ("^c", "quit")]
        elif self.phase == TUIPhase.SEARCH_RESULTS:
            content_lines = self._render_search_results_screen(width)
            footer_hints = [("↑↓", "choose"), ("↵", "inspect"), ("a", "album"), ("esc", "back"), ("^c", "quit")]
        elif self.phase == TUIPhase.PICKING:
            content_lines = self._render_picking_screen(width)
            footer_hints = [("↑↓", "choose"), ("↵", "zoink"), ("a", "album"), ("esc", "back"), ("^c", "quit")]
        elif self.phase == TUIPhase.ALBUM:
            content_lines = self._render_album_screen(width)
            footer_hints = [("↑↓", "choose"), ("space", "toggle"), ("A", "all"), ("↵", "zoink"), ("esc", "back")]
        elif self.phase == TUIPhase.DOWNLOADING:
            content_lines = self._render_downloading_screen(width)
            footer_hints = [("esc", "cancel"), ("^c", "quit")]
        elif self.phase == TUIPhase.DONE:
            content_lines = self._render_done_screen(width)
            footer_hints = [("↵", "zoink another"), ("l", "library"), ("w", "web player"), ("^c", "quit")]
        elif self.phase == TUIPhase.ERROR:
            content_lines = self._render_error_screen(width)
            footer_hints = [("↵", "try again"), ("esc", "back"), ("^c", "quit")]
        elif self.phase == TUIPhase.LIBRARY:
            content_lines = self._render_library_screen(width, height)
            if self.confirm_delete_id:
                footer_hints = [("y", "confirm delete"), ("n", "cancel")]
            else:
                footer_hints = [("↑↓", "browse"), ("↵/i", "inspect"), ("c", "convert"), ("p/space", "play"), ("s", "stop"), ("d", "delete"), ("r", "rescan"), ("o", "sort"), ("esc", "home")]
        elif self.phase == TUIPhase.LIBRARY_DETAIL:
            content_lines = self._render_library_detail_screen(width)
            if self.confirm_delete_id:
                footer_hints = [("y", "confirm delete"), ("n", "cancel")]
            else:
                footer_hints = [("p/↵", "play"), ("c", "convert"), ("s", "stop"), ("d", "delete"), ("esc", "library")]
        elif self.phase == TUIPhase.CONVERT:
            content_lines = self._render_convert_screen(width)
            if self.convert_in_progress:
                footer_hints = [("converting...", "please wait"), ("^c", "quit")]
            else:
                footer_hints = [("↑↓", "format"), ("r/space", "replace"), ("↵", "convert"), ("esc", "cancel"), ("^c", "quit")]
        elif self.phase == TUIPhase.HELP:
            content_lines = self._render_help_screen(width)
            footer_hints = [("↵/esc", "home"), ("^c", "quit")]
        elif self.phase == TUIPhase.CONFIG:
            content_lines = self._render_config_screen(width)
            if self.config_editing:
                footer_hints = [("↵", "save"), ("esc", "cancel"), ("^w", "del word")]
            else:
                footer_hints = [("↑↓", "select"), ("↵/space", "change"), ("e", "edit text"), ("esc", "home"), ("^c", "quit")]
        else:
            content_lines = [("class:muted", "unknown state\n")]
            footer_hints = [("^c", "quit")]

        return self._assemble_full_screen(content_lines, footer_hints, width, height)

    def _assemble_full_screen(
        self,
        content_lines: list[tuple],
        footer_hints: list[tuple[str, str]],
        width: int,
        height: int,
    ) -> FormattedText:
        """Compose screen lines with vertical centering and a pinned footer."""
        total_content_lines = sum(text.count("\n") for item in content_lines for text in [item[1]])

        avail_for_content = max(height - 3, 5)
        pad_top = max(0, (avail_for_content - total_content_lines) // 2)
        pad_bottom = max(0, avail_for_content - total_content_lines - pad_top)

        result: list[tuple] = []

        for _ in range(pad_top):
            result.append(("", "\n"))

        result.extend(content_lines)

        for _ in range(pad_bottom):
            result.append(("", "\n"))

        result.append(("class:border", "─" * width + "\n"))
        footer_spans = self._render_footer_spans(footer_hints, width)
        result.extend(footer_spans)

        return FormattedText(result)

    def _render_footer_spans(self, hints: list[tuple[str, str]], width: int) -> list[tuple]:
        """Render concise, clickable footer hints."""
        spans: list[tuple] = [("", "  ")]

        for i, (key, action) in enumerate(hints):
            action_fn = self._map_footer_action(key)
            handler = self._click_handler(action_fn) if action_fn else None

            spans.append(("class:footer.key", key, handler))
            spans.append(("class:footer.action", f" {action}", handler))
            if i < len(hints) - 1:
                spans.append(("class:footer.sep", "  ·  "))

        raw_left_len = sum(len(text) for item in spans for text in [item[1]])
        watermark_str = f"{self.WATERMARK}  "
        spacing = max(1, width - raw_left_len - len(watermark_str))
        spans.append(("", " " * spacing))
        spans.append(("class:watermark", watermark_str + "\n"))
        return spans

    def _map_footer_action(self, key: str) -> Optional[Callable[[], None]]:
        if key in ("↵", "enter", "↵/esc", "↵/i", "p/↵"):
            return self.handle_enter
        elif key in ("esc", "cancel", "back", "home", "library"):
            return self.handle_escape
        elif key in ("^c", "quit"):
            return self.request_exit
        elif key == "^t":
            return self.handle_cycle_theme
        elif key in ("^l", "l"):
            return self.open_library
        elif key in ("/help", "commands"):
            return self.open_help
        elif key == "w":
            return self.open_web_player
        elif key == "a":
            return self.handle_album_action
        elif key == "A":
            return self._select_all_album
        elif key in ("p/space", "p"):
            return self.handle_play
        elif key == "s":
            return self.handle_stop
        elif key == "d":
            return self.handle_delete
        elif key == "y":
            return self.handle_confirm_yes
        elif key == "n":
            return self.handle_confirm_no
        elif key == "r":
            return self.handle_rescan
        elif key == "o":
            return self.handle_sort
        elif key in ("tab", "autocomplete"):
            return self.handle_tab
        return None

    def _select_all_album(self) -> None:
        if self.album_result and self.album_result.tracks:
            self.album_selected_ids = {t.id for t in self.album_result.tracks}
            self.notify()

    # --- Individual Screen Builders ---

    def _render_input_screen(self, width: int, height: int = 24) -> list[tuple]:
        out: list[tuple] = []
        box_w = min(width - 4, 66)
        pad_x = " " * max(0, (width - box_w) // 2)

        # 1. Logo
        for line in self.LOGO_LINES:
            logo_pad = " " * max(0, (width - len(line)) // 2)
            out.append(("", logo_pad))
            out.append(("class:logo", line + "\n"))

        out.append(("", "\n"))

        # 2. Tagline
        tagline_pad = " " * max(0, (width - len(self.TAGLINE)) // 2)
        out.append(("", tagline_pad))
        out.append(("class:tagline", self.TAGLINE + "\n"))
        out.append(("", "\n"))

        # 3. Framed Input Box
        inner_w = box_w - 4
        frame_top = pad_x + "╭" + "─" * (box_w - 2) + "╮\n"
        frame_bot = pad_x + "╰" + "─" * (box_w - 2) + "╯\n"

        out.append(("class:input.frame.focus", frame_top))

        if self.input_text:
            pos = max(0, min(self.input_cursor, len(self.input_text)))
            max_visible = max(inner_w - 2, 10)
            if len(self.input_text) <= max_visible:
                view_start = 0
                view_end = len(self.input_text)
            else:
                view_start = max(0, pos - max_visible + 4)
                view_end = min(len(self.input_text), view_start + max_visible)
                if view_end - view_start < max_visible and view_start > 0:
                    view_start = max(0, view_end - max_visible)

            visible_text = self.input_text[view_start:view_end]
            rel_cursor = pos - view_start

            before = visible_text[:rel_cursor]
            at_cursor = visible_text[rel_cursor] if rel_cursor < len(visible_text) else " "
            after = visible_text[rel_cursor + 1:] if rel_cursor < len(visible_text) else ""

            rendered_len = len(before) + 1 + len(after)
            rem = inner_w - rendered_len

            out.append(("class:input.frame.focus", f"{pad_x}│ "))
            if before:
                out.append(("class:input.text", before))
            out.append(("class:input.cursor", at_cursor))
            if after:
                out.append(("class:input.text", after))
            out.append(("", " " * max(0, rem)))
            out.append(("class:input.frame.focus", " │\n"))
        else:
            placeholder = "paste a link or search for a song, artist, album..."
            if len(placeholder) > inner_w - 2:
                placeholder = placeholder[:inner_w - 4] + "…"
            rem = inner_w - 1 - len(placeholder)
            out.append(("class:input.frame.focus", f"{pad_x}│ "))
            out.append(("class:input.cursor", " "))
            out.append(("class:input.placeholder", placeholder))
            out.append(("", " " * max(0, rem)))
            out.append(("class:input.frame.focus", " │\n"))

        out.append(("class:input.frame.focus", frame_bot))

        # 4. Commands Popup Menu (when typing '/')
        if self.command_suggestions:
            out.append(("", "\n"))
            s_top = pad_x + "╭─ commands " + "─" * max(0, box_w - 14) + "╮\n"
            s_bot = pad_x + "╰" + "─" * (box_w - 2) + "╯\n"
            out.append(("class:border.focus", s_top))

            cmd_col_w = 12
            desc_col_w = max(10, inner_w - cmd_col_w - 4)

            # Clamp command_cursor within suggestions
            if self.command_cursor >= len(self.command_suggestions):
                self.command_cursor = 0

            for idx, (cmd_str, cmd_desc) in enumerate(self.command_suggestions):
                is_sel = idx == self.command_cursor
                cursor_m = "❯ " if is_sel else "  "
                style = "class:choice.selected" if is_sel else "class:choice.item"

                cmd_part = f"{cursor_m}{cmd_str:<{cmd_col_w}}"
                desc_part = (cmd_desc[:desc_col_w - 2] + "..") if len(cmd_desc) > desc_col_w else cmd_desc

                row_str = f" {cmd_part} {desc_part}"
                row_str = row_str.ljust(inner_w)[:inner_w]

                handler = self._click_handler(lambda c=cmd_str: self._execute_slash_command(c))

                out.append(("class:border.focus", f"{pad_x}│"))
                out.append((style, row_str, handler))
                out.append(("class:border.focus", "│\n"))

            out.append(("class:border.focus", s_bot))

        return out

    def _render_probing_screen(self, width: int) -> list[tuple]:
        out: list[tuple] = []
        msg = f"  ⏳ {self.probing_text}"
        pad = " " * max(0, (width - len(msg)) // 2)

        out.append(("", "\n\n"))
        out.append(("", pad))
        out.append(("class:status.spinner", msg + "\n"))
        out.append(("", "\n"))
        return out

    def _render_search_results_screen(self, width: int) -> list[tuple]:
        out: list[tuple] = []
        box_w = min(width - 4, 74)
        pad_x = " " * max(0, (width - box_w) // 2)

        header_text = f"Results for \"{self.search_query}\""
        head_pad = " " * max(0, (width - len(header_text)) // 2)
        out.append(("", head_pad))
        out.append(("class:primary", header_text + "\n\n"))

        out.append(("class:border", pad_x + "╭" + "─" * (box_w - 2) + "╮\n"))
        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))

        inner_w = box_w - 4
        title_w = max(18, int(inner_w * 0.46))
        artist_w = max(12, int(inner_w * 0.32))
        dur_w = 6

        for idx, t in enumerate(self.search_results[:8]):
            is_cursor = idx == self.search_cursor
            cursor_mark = "❯ " if is_cursor else "  "

            title = (t.title[:title_w - 2] + "..") if len(t.title) > title_w else t.title
            artist = (t.artist[:artist_w - 2] + "..") if len(t.artist) > artist_w else t.artist
            duration = t.duration_str

            row_str = f" {cursor_mark}{idx + 1}. {title:<{title_w}} {artist:<{artist_w}} {duration:>{dur_w}} "
            rem = inner_w - len(row_str)
            row_str += " " * max(0, rem)

            handler = self._click_handler(lambda i=idx: self._select_search_index(i))
            style = "class:choice.selected" if is_cursor else "class:choice.item"

            out.append(("class:border", f"{pad_x}│"))
            out.append((style, row_str[:inner_w], handler))
            out.append(("class:border", "│\n"))

        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))
        out.append(("class:border", pad_x + "╰" + "─" * (box_w - 2) + "╯\n"))
        return out

    def _select_search_index(self, idx: int) -> None:
        if 0 <= idx < len(self.search_results):
            self.search_cursor = idx
            self.inspect_track(self.search_results[idx])

    def _render_picking_screen(self, width: int) -> list[tuple]:
        """Render the dedicated Track Details & Download Options screen."""
        out: list[tuple] = []
        track = self.selected_track
        if not track:
            return out

        if width >= 72:
            return self._render_picking_two_column(width, track)
        else:
            return self._render_picking_stacked(width, track)

    def _render_picking_two_column(self, width: int, track: TrackResult) -> list[tuple]:
        out: list[tuple] = []
        col_w = min((width - 8) // 2, 36)
        total_w = col_w * 2 + 2
        pad_x = " " * max(0, (width - total_w) // 2)

        # 1. Left Card Lines (Track Metadata)
        left_top = "╭─ track " + "─" * (col_w - 10) + "╮"
        left_bot = "╰" + "─" * (col_w - 2) + "╯"

        title_trunc = track.title[:col_w - 4]
        artist_trunc = track.artist[:col_w - 4]
        album_str = f"album: {track.album or '(single)'}"[:col_w - 4]
        len_str = f"length: {track.duration_str}"[:col_w - 4]
        year_str = f"year: {track.year or 'N/A'}"[:col_w - 4]
        badge_str = "[✓ audio] [✓ art] [✓ tags]"[:col_w - 4]

        left_rows = [
            left_top,
            "│ " + " " * (col_w - 4) + " │",
            "│ " + title_trunc.ljust(col_w - 4) + " │",
            "│ " + artist_trunc.ljust(col_w - 4) + " │",
            "│ " + " " * (col_w - 4) + " │",
            "│ " + album_str.ljust(col_w - 4) + " │",
            "│ " + len_str.ljust(col_w - 4) + " │",
            "│ " + year_str.ljust(col_w - 4) + " │",
            "│ " + " " * (col_w - 4) + " │",
            "│ " + badge_str.ljust(col_w - 4) + " │",
            "│ " + " " * (col_w - 4) + " │",
            left_bot,
        ]

        # 2. Right Card Lines (Format Choices & Zoink Button)
        right_top = "╭─ quality " + "─" * (col_w - 12) + "╮"
        right_bot = "╰" + "─" * (col_w - 2) + "╯"

        choice_rows: list[tuple[str, str, Optional[Callable]]] = []
        choice_rows.append(("class:border", right_top, None))

        for idx, c in enumerate(self.audio_choices[:4]):
            is_sel = idx == self.choice_index
            radio = "● " if is_sel else "○ "
            size_tag = f"~{c.est_size_mb}M" if c.est_size_mb else ""
            right_part = f"{size_tag} " if size_tag else ""

            inner_choice_w = col_w - 2
            avail_for_left = inner_choice_w - len(right_part) - 1
            raw_label = f" {radio}{c.label}"
            if len(raw_label) > avail_for_left:
                left_part = raw_label[:avail_for_left - 2] + ".."
            else:
                left_part = raw_label

            spacing = inner_choice_w - len(left_part) - len(right_part)
            row_content = left_part + " " * max(0, spacing) + right_part

            handler = self._click_handler(lambda i=idx: self._select_choice_index(i))
            style = "class:choice.selected" if is_sel else "class:choice.item"
            choice_rows.append((style, "│" + row_content[:inner_choice_w] + "│", handler))

        btn_box_w = 15
        pad_btn = (col_w - 2 - btn_box_w) // 2
        rem_btn = col_w - 2 - btn_box_w - pad_btn
        btn_str = " " * pad_btn + "╭─────────────╮" + " " * rem_btn
        btn_txt = " " * pad_btn + "│   zoink ↵   │" + " " * rem_btn
        btn_bot = " " * pad_btn + "╰─────────────╯" + " " * rem_btn

        btn_handler = self._click_handler(self.trigger_zoink)

        choice_rows.append(("class:border", "│ " + " " * (col_w - 4) + " │", None))
        choice_rows.append(("class:border", "│" + btn_str + "│", None))
        choice_rows.append(("class:button.zoink", "│" + btn_txt + "│", btn_handler))
        choice_rows.append(("class:border", "│" + btn_bot + "│", None))
        choice_rows.append(("class:border", right_bot, None))

        # 3. Stitch Left & Right Columns side by side
        max_len = max(len(left_rows), len(choice_rows))
        while len(left_rows) < max_len:
            left_rows.insert(-1, "│ " + " " * (col_w - 4) + " │")
        while len(choice_rows) < max_len:
            choice_rows.insert(-1, ("class:border", "│ " + " " * (col_w - 4) + " │", None))

        for l_txt, r_item in zip(left_rows, choice_rows):
            r_style, r_txt, r_handler = r_item
            out.append(("", pad_x))
            out.append(("class:border", l_txt))
            out.append(("", "  "))
            out.append((r_style, r_txt + "\n", r_handler))

        return out

    def _render_picking_stacked(self, width: int, track: TrackResult) -> list[tuple]:
        """Stacked single-column layout for narrow / mobile screens."""
        out: list[tuple] = []
        box_w = min(width - 2, 60)
        pad_x = " " * max(0, (width - box_w) // 2)

        out.append(("class:border", pad_x + "╭─ track " + "─" * (box_w - 10) + "╮\n"))
        t_title = track.title[:box_w - 4]
        t_meta = f"{track.artist} · {track.duration_str}"[:box_w - 4]
        out.append(("class:primary", f"{pad_x}│ {t_title:<{box_w - 4}} │\n"))
        out.append(("class:muted", f"{pad_x}│ {t_meta:<{box_w - 4}} │\n"))
        out.append(("class:border", pad_x + "╰" + "─" * (box_w - 2) + "╯\n"))

        out.append(("class:border", pad_x + "╭─ quality " + "─" * (box_w - 12) + "╮\n"))
        for idx, c in enumerate(self.audio_choices[:4]):
            is_sel = idx == self.choice_index
            radio = "● " if is_sel else "○ "
            row_txt = f" {radio}{c.label} (~{c.est_size_mb}M) "
            style = "class:choice.selected" if is_sel else "class:choice.item"
            handler = self._click_handler(lambda i=idx: self._select_choice_index(i))
            out.append(("class:border", f"{pad_x}│"))
            out.append((style, row_txt.ljust(box_w - 2)[:box_w - 2], handler))
            out.append(("class:border", "│\n"))

        btn_handler = self._click_handler(self.trigger_zoink)
        out.append(("class:button.zoink", f"{pad_x}│" + " [ zoink ↵ ] ".center(box_w - 2) + "│\n", btn_handler))
        out.append(("class:border", pad_x + "╰" + "─" * (box_w - 2) + "╯\n"))
        return out

    def _select_choice_index(self, idx: int) -> None:
        if 0 <= idx < len(self.audio_choices):
            self.choice_index = idx
            self.notify()

    def _render_album_screen(self, width: int) -> list[tuple]:
        out: list[tuple] = []
        album = self.album_result
        if not album:
            return out

        box_w = min(width - 4, 72)
        pad_x = " " * max(0, (width - box_w) // 2)

        header = f"{album.title} ({album.year or 'N/A'}) — {album.artist}"
        head_pad = " " * max(0, (width - len(header)) // 2)
        out.append(("", head_pad))
        out.append(("class:primary", header + "\n\n"))

        out.append(("class:border", pad_x + "╭" + "─" * (box_w - 2) + "╮\n"))

        inner_w = box_w - 4
        title_w = max(18, inner_w - 16)

        for idx, t in enumerate(album.tracks[:8]):
            is_cursor = idx == self.album_cursor
            is_checked = t.id in self.album_selected_ids
            check = "[✓] " if is_checked else "[ ] "
            cursor_m = "❯ " if is_cursor else "  "

            title = (t.title[:title_w - 2] + "..") if len(t.title) > title_w else t.title
            row_str = f" {cursor_m}{check}{idx + 1:02d}. {title:<{title_w}} {t.duration_str:>6} "

            handler = self._click_handler(lambda i=idx: self._toggle_album_index(i))
            style = "class:choice.selected" if is_cursor else "class:choice.item"

            out.append(("class:border", f"{pad_x}│"))
            out.append((style, row_str.ljust(inner_w)[:inner_w], handler))
            out.append(("class:border", "│\n"))

        sel_count = len(self.album_selected_ids)
        btn_text = f" [ zoink album ({sel_count} tracks) ↵ ] "
        btn_handler = self._click_handler(self.trigger_zoink)

        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))
        out.append(("class:button.zoink", f"{pad_x}│" + btn_text.center(box_w - 2) + "│\n", btn_handler))
        out.append(("class:border", pad_x + "╰" + "─" * (box_w - 2) + "╯\n"))
        return out

    def _toggle_album_index(self, idx: int) -> None:
        if self.album_result and 0 <= idx < len(self.album_result.tracks):
            self.album_cursor = idx
            tid = self.album_result.tracks[idx].id
            if tid in self.album_selected_ids:
                self.album_selected_ids.remove(tid)
            else:
                self.album_selected_ids.add(tid)
            self.notify()

    def _render_downloading_screen(self, width: int) -> list[tuple]:
        out: list[tuple] = []
        box_w = min(width - 4, 64)
        pad_x = " " * max(0, (width - box_w) // 2)

        out.append(("class:border", pad_x + "╭" + "─" * (box_w - 2) + "╮\n"))
        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))

        title = self.selected_track.title if self.selected_track else "Audio track"
        artist = self.selected_track.artist if self.selected_track else ""
        head_line = f"  {title} — {artist}"[:box_w - 4]
        out.append(("class:primary", f"{pad_x}│ {head_line:<{box_w - 4}} │\n"))

        sub_line = f"  {self.download_status_text}"[:box_w - 4]
        out.append(("class:muted", f"{pad_x}│ {sub_line:<{box_w - 4}} │\n"))
        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))

        bar_w = box_w - 14
        pct = max(0.0, min(self.download_progress, 100.0))
        filled = int(bar_w * pct / 100)
        empty = bar_w - filled
        bar_filled_str = "█" * filled
        bar_empty_str = "░" * empty

        out.append(("class:border", f"{pad_x}│  ["))
        out.append(("class:progress.bar.filled", bar_filled_str))
        out.append(("class:progress.bar.empty", bar_empty_str))
        out.append(("class:progress.pct", f"]  {pct:4.0f}% │\n"))

        speed_str = self.download_speed or "---"
        eta_str = self.download_eta or "---"
        size_str = self.download_size or ""
        metric_line = f"  speed: {speed_str}   eta: {eta_str}   {size_str}".strip()[:box_w - 4]
        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))
        out.append(("class:progress.meta", f"{pad_x}│ {metric_line:<{box_w - 4}} │\n"))

        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))
        out.append(("class:border", pad_x + "╰" + "─" * (box_w - 2) + "╯\n"))
        return out

    def _render_done_screen(self, width: int) -> list[tuple]:
        out: list[tuple] = []
        box_w = min(width - 4, 66)
        pad_x = " " * max(0, (width - box_w) // 2)

        out.append(("class:border", pad_x + "╭" + "─" * (box_w - 2) + "╮\n"))
        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))

        success_msg = "  ✓ Successfully zoinked!"
        out.append(("class:success", f"{pad_x}│ {success_msg:<{box_w - 4}} │\n"))

        title_str = f"  {self.download_outcome_title} — {self.download_outcome_artist}"[:box_w - 4]
        out.append(("class:primary", f"{pad_x}│ {title_str:<{box_w - 4}} │\n"))
        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))

        path_short = self.download_outcome_path
        home = str(Path.home())
        if path_short.startswith(home):
            path_short = "~" + path_short[len(home):]
        path_line = f"  Saved to: {path_short}"[:box_w - 4]
        out.append(("class:muted", f"{pad_x}│ {path_line:<{box_w - 4}} │\n"))

        badge_line = "  [✓ audio verified] [✓ metadata tags] [✓ lyrics embedded]"[:box_w - 4]
        out.append(("class:badge", f"{pad_x}│ {badge_line:<{box_w - 4}} │\n"))
        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))

        another_btn = " [ ↵ zoink another ] "
        lib_btn = " [ l library ] "
        h_another = self._click_handler(self.go_home)
        h_lib = self._click_handler(self.open_library)

        btn_row = f"{another_btn}  {lib_btn}"
        pad_btn = " " * max(0, (box_w - 2 - len(btn_row)) // 2)
        out.append(("class:border", f"{pad_x}│{pad_btn}"))
        out.append(("class:button.zoink", another_btn, h_another))
        out.append(("", "  "))
        out.append(("class:button.secondary", lib_btn, h_lib))
        rem_btn = box_w - 2 - len(pad_btn) - len(btn_row)
        out.append(("class:border", " " * max(0, rem_btn) + "│\n"))

        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))
        out.append(("class:border", pad_x + "╰" + "─" * (box_w - 2) + "╯\n"))
        return out

    def _render_error_screen(self, width: int) -> list[tuple]:
        out: list[tuple] = []
        box_w = min(width - 4, 64)
        pad_x = " " * max(0, (width - box_w) // 2)

        out.append(("class:border", pad_x + "╭" + "─" * (box_w - 2) + "╮\n"))
        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))

        err_title = "  ✗ Could not zoink track"
        out.append(("class:error", f"{pad_x}│ {err_title:<{box_w - 4}} │\n"))
        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))

        reason_str = f"  Reason: {self.error_message}"[:box_w - 4]
        out.append(("class:muted", f"{pad_x}│ {reason_str:<{box_w - 4}} │\n"))
        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))

        retry_btn = " [ ↵ try again ] "
        back_btn = " [ esc back ] "
        h_retry = self._click_handler(self.go_home)
        h_back = self._click_handler(self.handle_escape)

        btn_row = f"{retry_btn}  {back_btn}"
        pad_btn = " " * max(0, (box_w - 2 - len(btn_row)) // 2)
        out.append(("class:border", f"{pad_x}│{pad_btn}"))
        out.append(("class:button.zoink", retry_btn, h_retry))
        out.append(("", "  "))
        out.append(("class:button.secondary", back_btn, h_back))
        rem = box_w - 2 - len(pad_btn) - len(btn_row)
        out.append(("class:border", " " * max(0, rem) + "│\n"))

        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))
        out.append(("class:border", pad_x + "╰" + "─" * (box_w - 2) + "╯\n"))
        return out

    def _render_library_screen(self, width: int, height: int = 24) -> list[tuple]:
        out: list[tuple] = []
        box_w = min(width - 4, 76)
        pad_x = " " * max(0, (width - box_w) // 2)

        total_tracks = len(self.library_tracks)
        pos_str = f"[{self.library_cursor + 1}/{total_tracks}]" if total_tracks else "[empty]"
        header = f"Music Library ({total_tracks} tracks) · {pos_str} · [sort: {self.library_sort_mode}]"
        head_pad = " " * max(0, (width - len(header)) // 2)
        out.append(("", head_pad))
        out.append(("class:primary", header + "\n\n"))

        out.append(("class:border", pad_x + "╭" + "─" * (box_w - 2) + "╮\n"))

        # Status / Playback bar inside box if active
        if self.playback_status_text:
            pb_text = f"  {self.playback_status_text}"
            out.append(("class:badge", f"{pad_x}│ {pb_text:<{box_w - 4}} │\n"))
            out.append(("class:border", f"{pad_x}│" + "─" * (box_w - 2) + "│\n"))
        elif self.library_status_message:
            st_text = f"  ℹ {self.library_status_message}"
            style = "class:error" if self.confirm_delete_id else "class:muted"
            out.append((style, f"{pad_x}│ {st_text:<{box_w - 4}} │\n"))
            out.append(("class:border", f"{pad_x}│" + "─" * (box_w - 2) + "│\n"))

        inner_w = box_w - 4
        title_w = max(18, int(inner_w * 0.44))
        artist_w = max(12, int(inner_w * 0.30))

        if not self.library_tracks:
            empty_msg = "  No downloaded music found in library yet."
            empty_hint = "  Download a song with ZoinK or press 'r' to rescan."
            out.append(("class:muted", f"{pad_x}│ {empty_msg:<{inner_w}} │\n"))
            out.append(("class:dim", f"{pad_x}│ {empty_hint:<{inner_w}} │\n"))
        else:
            max_visible = max(5, min(12, height - 14)) if height > 16 else 8
            # Scroll window
            if self.library_cursor < self.library_scroll_offset:
                self.library_scroll_offset = self.library_cursor
            elif self.library_cursor >= self.library_scroll_offset + max_visible:
                self.library_scroll_offset = self.library_cursor - max_visible + 1

            # Up indicator if scrolled
            if self.library_scroll_offset > 0:
                up_hint = f"  ▲ ... {self.library_scroll_offset} more tracks above"
                out.append(("class:dim", f"{pad_x}│ {up_hint:<{inner_w}} │\n"))

            for offset_idx in range(max_visible):
                idx = self.library_scroll_offset + offset_idx
                if idx >= len(self.library_tracks):
                    break

                t = self.library_tracks[idx]
                is_cursor = idx == self.library_cursor
                cursor_m = "❯ " if is_cursor else "  "

                # Check if this track is currently playing
                is_playing = bool(self.playing_track and self.playing_track.get("id") == t.get("id"))
                play_icon = "▶ " if is_playing else "  "

                title = (t.get("title") or "Unknown")[:title_w - 2]
                artist = (t.get("artist") or "Unknown")[:artist_w - 2]

                dur_s = t.get("duration", 0)
                dur_fmt = f"{dur_s // 60}:{dur_s % 60:02d}" if dur_s else "--:--"

                fp = t.get("filepath", "")
                ext = Path(fp).suffix.lstrip(".").upper() if fp else "AUDIO"

                row_str = f" {cursor_m}{play_icon}{idx + 1:2d}. {title:<{title_w}} {artist:<{artist_w}} {dur_fmt:>5}  {ext:>4} "
                style = "class:choice.selected" if is_cursor else "class:choice.item"
                handler = self._click_handler(lambda i=idx: self._select_library_index(i))

                out.append(("class:border", f"{pad_x}│"))
                out.append((style, row_str.ljust(inner_w)[:inner_w], handler))
                out.append(("class:border", "│\n"))

            # Down indicator if more below
            remaining = total_tracks - (self.library_scroll_offset + max_visible)
            if remaining > 0:
                dn_hint = f"  ▼ ... {remaining} more tracks below"
                out.append(("class:dim", f"{pad_x}│ {dn_hint:<{inner_w}} │\n"))

        out.append(("class:border", pad_x + "╰" + "─" * (box_w - 2) + "╯\n"))
        return out

    def _render_library_detail_screen(self, width: int) -> list[tuple]:
        out: list[tuple] = []
        track = self.selected_library_track
        if not track:
            return out

        box_w = min(width - 4, 72)
        pad_x = " " * max(0, (width - box_w) // 2)
        inner_w = box_w - 4

        header = "Track Inspection"
        head_pad = " " * max(0, (width - len(header)) // 2)
        out.append(("", head_pad))
        out.append(("class:primary", header + "\n\n"))

        out.append(("class:border", pad_x + "╭─ info " + "─" * (box_w - 10) + "╮\n"))

        title = track.get("title", "Unknown")
        artist = track.get("artist", "Unknown")
        album = track.get("album", "") or "(single)"
        genre = track.get("genre", "") or "Music"
        year = track.get("year", 0) or "N/A"
        dur_s = track.get("duration", 0)
        dur_str = f"{dur_s // 60}:{dur_s % 60:02d}" if dur_s else "Unknown"

        file_size = track.get("file_size", 0)
        size_str = f"{file_size / (1024 * 1024):.1f} MB" if file_size else "Unknown"

        fp = track.get("filepath", "")
        home = str(Path.home())
        fp_short = ("~" + fp[len(home):]) if fp.startswith(home) else fp
        ext = Path(fp).suffix.lstrip(".").upper() if fp else "AUDIO"

        art_tag = "[✓ artwork embedded]" if track.get("has_artwork") else "[no artwork]"
        lyr_tag = "[✓ lyrics embedded]" if track.get("has_lyrics") else "[no lyrics]"

        rows = [
            ("Title", title),
            ("Artist", artist),
            ("Album", album),
            ("Year", str(year)),
            ("Genre", genre),
            ("Duration", dur_str),
            ("Format", f"{ext} · {size_str}"),
            ("Location", fp_short),
            ("Tags", f"{art_tag} {lyr_tag}"),
        ]

        if self.playback_status_text:
            out.append(("class:badge", f"{pad_x}│ {self.playback_status_text:<{inner_w}} │\n"))
            out.append(("class:border", f"{pad_x}│" + "─" * (box_w - 2) + "│\n"))
        elif self.library_status_message:
            st_text = f"ℹ {self.library_status_message}"
            style = "class:error" if self.confirm_delete_id else "class:muted"
            out.append((style, f"{pad_x}│ {st_text:<{inner_w}} │\n"))
            out.append(("class:border", f"{pad_x}│" + "─" * (box_w - 2) + "│\n"))

        for label, val in rows:
            line = f"  {label:<10}: {val}"[:inner_w]
            out.append(("class:secondary", f"{pad_x}│ {line:<{inner_w}} │\n"))

        out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))

        # Action buttons row
        p_btn = " [ p / ↵ play ] " if not self.playback_process else " [ s stop ] "
        d_btn = " [ d delete ] "
        b_btn = " [ esc back ] "
        h_play = self._click_handler(self.handle_play)
        h_del = self._click_handler(self.handle_delete)
        h_back = self._click_handler(self.handle_escape)

        btns = f"{p_btn}  {d_btn}  {b_btn}"
        pad_btns = " " * max(0, (inner_w - len(btns)) // 2)
        out.append(("class:border", f"{pad_x}│ {pad_btns}"))
        out.append(("class:button.zoink", p_btn, h_play))
        out.append(("", "  "))
        out.append(("class:button.secondary", d_btn, h_del))
        out.append(("", "  "))
        out.append(("class:button.secondary", b_btn, h_back))
        rem = max(0, inner_w - len(pad_btns) - len(btns))
        out.append(("class:border", " " * rem + " │\n"))

        out.append(("class:border", pad_x + "╰" + "─" * (box_w - 2) + "╯\n"))
        return out

    def _render_help_screen(self, width: int) -> list[tuple]:
        out: list[tuple] = []
        box_w = min(width - 4, 74)
        pad_x = " " * max(0, (width - box_w) // 2)
        inner_w = box_w - 4

        header = "ZoinK Guide & Commands"
        head_pad = " " * max(0, (width - len(header)) // 2)
        out.append(("", head_pad))
        out.append(("class:primary", header + "\n\n"))

        out.append(("class:border", pad_x + "╭─ slash commands " + "─" * max(0, box_w - 20) + "╮\n"))

        for cmd, desc in SLASH_COMMANDS:
            line = f"  {cmd:<10}  {desc}"
            out.append(("class:choice.selected", f"{pad_x}│ {line:<{inner_w}} │\n"))

        out.append(("class:border", f"{pad_x}│" + "─" * (box_w - 2) + "│\n"))
        out.append(("class:primary", f"{pad_x}│ {'  keyboard shortcuts':<{inner_w}} │\n"))

        shortcuts = [
            ("↵ / Enter", "Accept selection, trigger download, or run command"),
            ("↑ / ↓", "Navigate suggestions, tracks, formats, or library"),
            ("Tab", "Autocomplete slash command suggestion in input"),
            ("p / Space", "Play / pause selected library track in background"),
            ("s", "Stop currently playing audio immediately"),
            ("d", "Delete track from disk and library (with confirm)"),
            ("r", "Rescan music download directory for new tracks"),
            ("o", "Cycle library sort order (recent / title / artist)"),
            ("a / A", "Inspect album / toggle all tracks in album view"),
            ("esc", "Go back / cancel active download or operation"),
            ("^c", "Quit ZoinK cleanly"),
        ]

        for key, act in shortcuts:
            k_part = f"  {key:<12}"
            line = f"{k_part} {act}"[:inner_w]
            out.append(("class:secondary", f"{pad_x}│ {line:<{inner_w}} │\n"))

        out.append(("class:border", f"{pad_x}│" + "─" * (box_w - 2) + "│\n"))

        home_btn = " [ ↵ back to home ] "
        h_home = self._click_handler(self.go_home)
        pad_btn = " " * max(0, (inner_w - len(home_btn)) // 2)
        out.append(("class:border", f"{pad_x}│ {pad_btn}"))
        out.append(("class:button.zoink", home_btn, h_home))
        rem = max(0, inner_w - len(pad_btn) - len(home_btn))
        out.append(("class:border", " " * rem + " │\n"))

        out.append(("class:border", pad_x + "╰" + "─" * (box_w - 2) + "╯\n"))
        return out

    def _render_config_screen(self, width: int) -> list[tuple]:
        out: list[tuple] = []
        box_w = min(width - 4, 76)
        pad_x = " " * max(0, (width - box_w) // 2)
        inner_w = box_w - 4

        header = "ZoinK Settings & Preferences"
        head_pad = " " * max(0, (width - len(header)) // 2)
        out.append(("", head_pad))
        out.append(("class:primary", header + "\n\n"))

        out.append(("class:border", pad_x + "╭─ configuration " + "─" * max(0, box_w - 19) + "╮\n"))

        if self.config_status_message:
            st_style = "class:badge" if self.config_status_message.startswith("✓") else "class:error"
            st_text = f" {self.config_status_message} "
            out.append((st_style, f"{pad_x}│ {st_text:<{inner_w}} │\n"))
            out.append(("class:border", f"{pad_x}│" + "─" * (box_w - 2) + "│\n"))

        items = self._get_config_items()
        for i, it in enumerate(items):
            is_sel = (i == self.config_cursor)
            label = it["label"]
            itype = it["type"]
            val = it["value"]

            prefix = " > " if is_sel else "   "
            line_style = "class:choice.selected" if is_sel else "class:secondary"

            if is_sel and self.config_editing:
                cur_pos = self.config_edit_cursor
                v_left = self.config_edit_value[:cur_pos]
                v_right = self.config_edit_value[cur_pos:]
                val_disp = f"[ {v_left}▌{v_right} ]"
                desc_line = "Type new value · Enter save · Esc cancel"
            else:
                if itype == "toggle":
                    val_disp = "[ ✓ enabled ]" if val else "[ ✗ disabled ]"
                elif itype == "choice":
                    choices_hint = " · ".join(it.get("choices", []))
                    val_disp = f"[ {val} ]  ({choices_hint})"
                else:
                    val_str = str(val)
                    if len(val_str) > 28:
                        val_str = "..." + val_str[-25:]
                    val_disp = f"[ {val_str} ]"
                desc_line = it["desc"]

            handler = self._click_handler(lambda idx=i: self._select_config_index(idx))

            row_str = f"{prefix}{label:<18} {val_disp}"
            out.append((line_style, f"{pad_x}│ {row_str:<{inner_w}} │\n", handler))

            sub_style = "class:primary" if is_sel else "class:muted"
            sub_str = f"      └ {desc_line}"
            out.append((sub_style, f"{pad_x}│ {sub_str:<{inner_w}} │\n", handler))

            if i < len(items) - 1:
                out.append(("class:border", f"{pad_x}│" + " " * (box_w - 2) + "│\n"))

        out.append(("class:border", f"{pad_x}│" + "─" * (box_w - 2) + "│\n"))

        if self.config_editing:
            save_btn = " [ ↵ save ] "
            cancel_btn = " [ esc cancel ] "
            h_save = self._click_handler(self.handle_enter)
            h_cancel = self._click_handler(self.handle_escape)
            btns = f"{save_btn}  {cancel_btn}"
            pad_btn = " " * max(0, (inner_w - len(btns)) // 2)
            out.append(("class:border", f"{pad_x}│ {pad_btn}"))
            out.append(("class:button.zoink", save_btn, h_save))
            out.append(("", "  "))
            out.append(("class:button.secondary", cancel_btn, h_cancel))
            rem = max(0, inner_w - len(pad_btn) - len(btns))
            out.append(("class:border", " " * rem + " │\n"))
        else:
            chg_btn = " [ ↵ / space change ] "
            edit_btn = " [ e edit ] "
            home_btn = " [ esc back to home ] "
            h_chg = self._click_handler(lambda: self.handle_cycle_config(True))
            h_edit = self._click_handler(self.handle_edit_config)
            h_home = self._click_handler(self.go_home)
            btns = f"{chg_btn}  {edit_btn}  {home_btn}"
            pad_btn = " " * max(0, (inner_w - len(btns)) // 2)
            out.append(("class:border", f"{pad_x}│ {pad_btn}"))
            out.append(("class:button.zoink", chg_btn, h_chg))
            out.append(("", "  "))
            out.append(("class:button.secondary", edit_btn, h_edit))
            out.append(("", "  "))
            out.append(("class:button.secondary", home_btn, h_home))
            rem = max(0, inner_w - len(pad_btn) - len(btns))
            out.append(("class:border", " " * rem + " │\n"))

        out.append(("class:border", pad_x + "╰" + "─" * (box_w - 2) + "╯\n"))
        return out

    def _select_config_index(self, idx: int) -> None:
        items = self._get_config_items()
        if 0 <= idx < len(items):
            if self.config_cursor == idx:
                self.handle_cycle_config(forward=True)
            else:
                self.config_cursor = idx
                self.config_editing = False
                self.notify()

    def _select_library_index(self, idx: int) -> None:
        if 0 <= idx < len(self.library_tracks):
            if self.library_cursor == idx:
                self.handle_inspect()
            else:
                self.library_cursor = idx
                self.notify()

    def _render_convert_screen(self, width: int) -> list[tuple]:
        out: list[tuple] = []
        track = self.convert_track or {}
        box_w = min(width - 4, 76)
        pad_x = " " * max(0, (width - box_w) // 2)
        inner_w = box_w - 4

        header = "Audio Format Converter"
        head_pad = " " * max(0, (width - len(header)) // 2)
        out.append(("", head_pad))
        out.append(("class:primary", header + "\n\n"))

        out.append(("class:border", pad_x + "╭" + "─" * (box_w - 2) + "╮\n"))

        # Error banner if any
        if self.convert_error:
            err_msg = f"  ✗ Error: {self.convert_error}"
            out.append(("class:error", f"{pad_x}│ {err_msg:<{inner_w}} │\n"))
            out.append(("class:border", f"{pad_x}│" + "─" * (box_w - 2) + "│\n"))

        # Track metadata summary
        title = (track.get("title") or "Unknown Title")[:inner_w - 14]
        artist = (track.get("artist") or "Unknown Artist")[:inner_w - 14]
        src_path = Path(track.get("filepath", "")) if track.get("filepath") else None
        current_fmt = src_path.suffix.lstrip(".").upper() if src_path else "UNKNOWN"

        out.append(("class:secondary", f"{pad_x}│ Track:   {title:<{inner_w - 9}} │\n"))
        out.append(("class:muted", f"{pad_x}│ Artist:  {artist:<{inner_w - 9}} │\n"))
        out.append(("class:dim", f"{pad_x}│ Current: {current_fmt:<{inner_w - 9}} │\n"))
        out.append(("class:border", f"{pad_x}│" + "─" * (box_w - 2) + "│\n"))

        # Format Selection
        format_info = {
            "mp3": ("MP3", "LAME CBR 320k · Universal compatibility"),
            "flac": ("FLAC", "16-bit lossless studio archive preservation"),
            "m4a": ("M4A / AAC", "Clean Apple & Android native AAC"),
            "opus": ("Opus", "Ultra-efficient modern voice & music codec"),
            "ogg": ("OGG Vorbis", "Open-source Vorbis container"),
            "wav": ("WAV", "Uncompressed studio PCM stream"),
        }

        out.append(("class:primary", f"{pad_x}│ Choose Target Format:{' ' * max(0, inner_w - 21)} │\n"))
        for i, fmt in enumerate(self.convert_target_formats):
            is_sel = (i == self.convert_format_index)
            prefix = " > " if is_sel else "   "
            chk = "[*]" if is_sel else "[ ]"
            name, desc = format_info.get(fmt, (fmt.upper(), ""))
            row = f"{prefix}{chk} {name:<10} {desc}"
            style = "class:choice.selected" if is_sel else "class:choice.item"
            handler = self._click_handler(lambda idx=i: self._select_convert_format(idx))
            out.append(("class:border", f"{pad_x}│"))
            out.append((style, row.ljust(inner_w)[:inner_w], handler))
            out.append(("class:border", "│\n"))

        out.append(("class:border", f"{pad_x}│" + "─" * (box_w - 2) + "│\n"))

        # Replace original option
        rep_mark = "[✓]" if self.convert_replace_original else "[✗]"
        rep_text = f"  {rep_mark} Replace original file (press 'r' to toggle)"
        h_rep = self._click_handler(self.handle_toggle_convert_replace)
        out.append(("class:border", f"{pad_x}│"))
        out.append(("class:secondary", rep_text.ljust(inner_w)[:inner_w], h_rep))
        out.append(("class:border", "│\n"))

        # Conversion in progress view
        if self.convert_in_progress:
            out.append(("class:border", f"{pad_x}│" + "─" * (box_w - 2) + "│\n"))
            pct = int(self.convert_progress)
            bar_len = min(28, inner_w - 12)
            fill = int((pct / 100.0) * bar_len)
            bar_str = "█" * fill + "░" * max(0, bar_len - fill)
            st_text = self.convert_status_text or f"Converting... {pct}%"
            out.append(("class:progress.bar.filled", f"{pad_x}│  [{bar_str}] {pct:3d}%{' ' * max(0, inner_w - bar_len - 11)} │\n"))
            out.append(("class:status.spinner", f"{pad_x}│  {st_text:<{inner_w - 2}} │\n"))

        out.append(("class:border", f"{pad_x}│" + "─" * (box_w - 2) + "│\n"))

        # Action buttons
        if self.convert_in_progress:
            conv_btn = " [ Converting... ] "
            pad_btn = " " * max(0, (inner_w - len(conv_btn)) // 2)
            out.append(("class:border", f"{pad_x}│ {pad_btn}"))
            out.append(("class:button.secondary", conv_btn))
            rem = max(0, inner_w - len(pad_btn) - len(conv_btn))
            out.append(("class:border", " " * rem + " │\n"))
        else:
            conv_btn = " [ ↵ convert ] "
            toggle_btn = " [ r replace ] "
            cancel_btn = " [ esc cancel ] "
            h_conv = self._click_handler(self.start_convert)
            h_tog = self._click_handler(self.handle_toggle_convert_replace)
            h_canc = self._click_handler(self.cancel_convert)
            btns = f"{conv_btn}  {toggle_btn}  {cancel_btn}"
            pad_btn = " " * max(0, (inner_w - len(btns)) // 2)
            out.append(("class:border", f"{pad_x}│ {pad_btn}"))
            out.append(("class:button.zoink", conv_btn, h_conv))
            out.append(("", "  "))
            out.append(("class:button.secondary", toggle_btn, h_tog))
            out.append(("", "  "))
            out.append(("class:button.secondary", cancel_btn, h_canc))
            rem = max(0, inner_w - len(pad_btn) - len(btns))
            out.append(("class:border", " " * rem + " │\n"))

        out.append(("class:border", pad_x + "╰" + "─" * (box_w - 2) + "╯\n"))
        return out
