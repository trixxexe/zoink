"""Tests for ZoinK centered, single-purpose TUI engine, navigation, and rendering."""

import pytest
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType, MouseButton

from zoink.config import Config
from zoink.library import Library
from zoink.provider import TrackResult, AlbumResult
from zoink.tui import ZoinKTUI, TUIPhase, run_tui
from zoink.tui.app import is_probably_url
from zoink.tui.theme import get_style, next_theme_mode


@pytest.fixture
def tui_instance(tmp_path):
    config = Config.get()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)
    tui = ZoinKTUI(config=config, library=lib)
    return tui


def test_tui_initial_state(tui_instance):
    tui = tui_instance
    assert tui.phase == TUIPhase.INPUT
    assert tui.input_text == ""
    assert tui.input_cursor == 0
    assert tui.theme_mode == "auto"


def test_is_probably_url():
    assert is_probably_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert is_probably_url("http://youtu.be/dQw4w9WgXcQ")
    assert is_probably_url("www.youtube.com/watch?v=123")
    assert is_probably_url("https://music.youtube.com/playlist?list=OLAK5uy_k")
    assert not is_probably_url("daft punk get lucky")
    assert not is_probably_url("radiohead ok computer")


def test_tui_input_editing(tui_instance):
    tui = tui_instance
    # Type "hello"
    tui.insert_text("hello")
    assert tui.input_text == "hello"
    assert tui.input_cursor == 5

    # Move cursor left twice
    tui.move_cursor_left()
    tui.move_cursor_left()
    assert tui.input_cursor == 3

    # Insert "y" at pos 3 -> "helylo"
    tui.insert_text("y")
    assert tui.input_text == "helylo"
    assert tui.input_cursor == 4

    # Delete backwards (deletes 'y') -> "hello"
    tui.delete_backwards()
    assert tui.input_text == "hello"
    assert tui.input_cursor == 3

    # Delete forwards (deletes 'l') -> "helo"
    tui.delete_forwards()
    assert tui.input_text == "helo"

    # Home and End
    tui.move_cursor_home()
    assert tui.input_cursor == 0
    tui.move_cursor_end()
    assert tui.input_cursor == 4

    # Delete word backwards
    tui.insert_text(" world test")
    assert tui.input_text == "helo world test"
    tui.delete_word_backwards()
    assert tui.input_text == "helo world"

    # Clear input
    tui.clear_input()
    assert tui.input_text == ""
    assert tui.input_cursor == 0


def test_tui_search_flow_and_navigation(tui_instance):
    tui = tui_instance
    sample_tracks = [
        TrackResult(id="t1", title="Song Alpha", artist="Artist A", duration=180),
        TrackResult(id="t2", title="Song Beta", artist="Artist B", duration=210),
        TrackResult(id="t3", title="Song Gamma", artist="Artist C", duration=240),
    ]

    # Directly populate search results for testing navigation
    tui.search_query = "daft punk"
    tui.search_results = sample_tracks
    tui.phase = TUIPhase.SEARCH_RESULTS
    tui.search_cursor = 0

    # Down navigation
    tui.handle_down()
    assert tui.search_cursor == 1
    tui.handle_down()
    assert tui.search_cursor == 2
    # Stays at lower boundary
    tui.handle_down()
    assert tui.search_cursor == 2

    # Up navigation
    tui.handle_up()
    assert tui.search_cursor == 1
    tui.handle_up()
    assert tui.search_cursor == 0
    # Stays at upper boundary
    tui.handle_up()
    assert tui.search_cursor == 0

    # Enter inspects current track (PICKING phase)
    tui.handle_enter()
    assert tui.phase == TUIPhase.PICKING
    assert tui.selected_track == sample_tracks[0]
    assert len(tui.audio_choices) >= 4

    # Escape returns back to SEARCH_RESULTS
    tui.handle_escape()
    assert tui.phase == TUIPhase.SEARCH_RESULTS

    # Escape again returns to INPUT
    tui.handle_escape()
    assert tui.phase == TUIPhase.INPUT


def test_tui_audio_choices_and_picking(tui_instance):
    tui = tui_instance
    track = TrackResult(
        id="t10",
        title="Midnight City",
        artist="M83",
        album="Hurry Up, We're Dreaming",
        duration=244,
    )
    tui.inspect_track(track)
    assert tui.phase == TUIPhase.PICKING
    assert tui.selected_track == track

    choices = tui.audio_choices
    assert len(choices) >= 5
    # Music-first options
    assert any(c.id == "best" for c in choices)
    assert any(c.id == "flac" for c in choices)
    assert any(c.id == "mp3_320" for c in choices)
    assert any(c.id == "m4a_256" for c in choices)
    assert any(c.id == "opus_160" for c in choices)

    # Size estimates should be calculated based on duration
    for c in choices:
        assert c.est_size_mb is not None
        assert c.est_size_mb > 0

    # Navigate choices
    assert tui.choice_index == 0
    tui.handle_down()
    assert tui.choice_index == 1
    tui.handle_up()
    assert tui.choice_index == 0


def test_tui_album_view_and_track_toggle(tui_instance):
    tui = tui_instance
    album = AlbumResult(
        id="alb1",
        title="Discovery",
        artist="Daft Punk",
        year=2001,
        tracks=[
            TrackResult(id="trk1", title="One More Time", artist="Daft Punk", duration=320),
            TrackResult(id="trk2", title="Aerodynamic", artist="Daft Punk", duration=212),
            TrackResult(id="trk3", title="Digital Love", artist="Daft Punk", duration=301),
        ],
    )
    tui.album_result = album
    tui.album_selected_ids = {"trk1", "trk2", "trk3"}
    tui.album_cursor = 0
    tui.phase = TUIPhase.ALBUM

    # Toggle trk1 off
    tui.handle_space()
    assert "trk1" not in tui.album_selected_ids
    assert len(tui.album_selected_ids) == 2

    # Toggle trk1 back on
    tui.handle_space()
    assert "trk1" in tui.album_selected_ids
    assert len(tui.album_selected_ids) == 3

    # Select all helper
    tui.album_selected_ids.clear()
    assert len(tui.album_selected_ids) == 0
    tui._select_all_album()
    assert len(tui.album_selected_ids) == 3


def test_tui_mouse_clicks(tui_instance):
    tui = tui_instance
    clicked_action = []

    def sample_action():
        clicked_action.append(True)

    handler = tui._click_handler(sample_action)
    dummy_pos = type("Point", (), {"x": 0, "y": 0})()

    # MOUSE_UP triggers action
    mouse_up = MouseEvent(position=dummy_pos, event_type=MouseEventType.MOUSE_UP, button=MouseButton.LEFT, modifiers=frozenset())
    res = handler(mouse_up)
    assert clicked_action == [True]
    assert res is None

    # MOUSE_DOWN or MOUSE_MOVE returns NotImplemented and does not trigger action
    mouse_move = MouseEvent(position=dummy_pos, event_type=MouseEventType.MOUSE_MOVE, button=MouseButton.NONE, modifiers=frozenset())
    res_move = handler(mouse_move)
    assert clicked_action == [True]
    assert res_move is NotImplemented


def test_tui_theme_cycling(tui_instance):
    tui = tui_instance
    assert tui.theme_mode == "auto"

    theme_updates = []
    tui.on_theme_change = lambda m: theme_updates.append(m)

    tui.handle_cycle_theme()
    assert tui.theme_mode == "dark"
    assert theme_updates == ["dark"]

    tui.handle_cycle_theme()
    assert tui.theme_mode == "light"
    assert theme_updates == ["dark", "light"]

    tui.handle_cycle_theme()
    assert tui.theme_mode == "auto"

    # Ensure get_style works for each mode
    for mode in ["auto", "dark", "light"]:
        style = get_style(mode)
        assert style is not None


def test_tui_render_watermark_and_centering(tui_instance):
    tui = tui_instance
    # Test all phases render watermark and content cleanly
    phases_to_test = [
        TUIPhase.INPUT,
        TUIPhase.PROBING,
        TUIPhase.SEARCH_RESULTS,
        TUIPhase.PICKING,
        TUIPhase.ALBUM,
        TUIPhase.DOWNLOADING,
        TUIPhase.DONE,
        TUIPhase.ERROR,
        TUIPhase.LIBRARY,
    ]

    tui.search_query = "Test Search"
    tui.search_results = [TrackResult(id="s1", title="Title", artist="Artist")]
    tui.selected_track = tui.search_results[0]
    tui.audio_choices = tui._build_audio_choices(tui.selected_track)
    tui.album_result = AlbumResult(id="a1", title="Album", artist="Artist", tracks=tui.search_results)
    tui.error_message = "Test network timeout"

    for phase in phases_to_test:
        tui.phase = phase
        rendered = tui.render(80, 24)
        full_text = "".join(text for item in rendered for text in [item[1]])
        assert ": made by Ritam/Trixx" in full_text
        assert len(full_text) > 0


def test_tui_responsive_breakpoints(tui_instance):
    tui = tui_instance
    track = TrackResult(id="t1", title="Sample Title", artist="Sample Artist", duration=200)
    tui.inspect_track(track)
    assert tui.phase == TUIPhase.PICKING

    # Narrow screen (< 72 cols) uses single-column stacked layout
    rendered_narrow = tui.render(50, 24)
    narrow_text = "".join(text for item in rendered_narrow for text in [item[1]])
    assert "[ zoink ↵ ]" in narrow_text

    # Wide screen (>= 72 cols) uses side-by-side 2-column layout
    rendered_wide = tui.render(80, 24)
    wide_text = "".join(text for item in rendered_wide for text in [item[1]])
    assert "zoink ↵" in wide_text


def test_run_tui_non_interactive(capsys):
    run_tui(non_interactive=True)
    out = capsys.readouterr().out
    assert "ZoinK" in out
    assert ": made by Ritam/Trixx" in out


def test_tui_init_with_on_refresh():
    refreshes = []
    tui = ZoinKTUI(on_refresh=lambda: refreshes.append(1))
    assert tui.on_invalidate is not None
    assert tui.on_refresh is not None
    tui.notify()
    assert len(refreshes) == 1

    # Reassignment via property
    tui.on_refresh = lambda: refreshes.append(2)
    tui.notify()
    assert refreshes == [1, 2]


def test_tui_download_full_flow_completion(tmp_path):
    import threading
    import time
    from zoink.downloader import DownloadJob, DownloadState

    config = Config.get()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)

    class MockDownloadManager:
        def __init__(self, config):
            self.config = config
            self.cancelled = False

        def cancel_all(self):
            self.cancelled = True

        def download(self, track, on_progress=None):
            job = DownloadJob(track=track)
            job.state = DownloadState.DOWNLOADING
            job.progress = 50.0
            job.speed = 1048576  # 1.0 MB/s
            job.eta = 5
            job.bytes_downloaded = 5242880  # 5.0 MB
            job.status_text = "Downloading audio: 50%"
            if on_progress:
                on_progress(job)

            # Finalize
            out_file = tmp_path / f"{track.title}.mp3"
            out_file.write_bytes(b"dummy audio data")
            job.filepath = out_file
            job.progress = 100.0
            job.state = DownloadState.DONE
            job.status_text = "Completed"
            if on_progress:
                on_progress(job)
            return job

    mock_dl = MockDownloadManager(config)
    notifications = []
    tui = ZoinKTUI(
        config=config,
        library=lib,
        downloader=mock_dl,
        on_refresh=lambda: notifications.append(1),
    )

    # 1. Start at INPUT
    assert tui.phase == TUIPhase.INPUT

    # 2. Enter search query
    tui.insert_text("golden brown")
    assert tui.input_text == "golden brown"

    # 3. Simulate search result arrival
    sample_track = TrackResult(
        id="gb123",
        title="Golden Brown",
        artist="The Stranglers",
        duration=210,
    )
    tui.search_results = [sample_track]
    tui.search_cursor = 0
    tui.phase = TUIPhase.SEARCH_RESULTS

    # 4. Press Enter to select track -> PICKING phase
    tui.handle_enter()
    assert tui.phase == TUIPhase.PICKING
    assert tui.selected_track == sample_track
    assert len(tui.audio_choices) > 0

    # 5. Navigate quality choices
    tui.handle_down()
    assert tui.choice_index == 1
    tui.handle_up()
    assert tui.choice_index == 0

    # 6. Trigger download by pressing Enter
    tui.handle_enter()

    # Wait briefly for background thread worker to complete
    for _ in range(50):
        if tui.phase == TUIPhase.DONE:
            break
        time.sleep(0.02)

    assert tui.phase == TUIPhase.DONE
    assert tui.download_progress == 100.0
    assert tui.download_outcome_title == "Golden Brown"
    assert tui.download_outcome_artist == "The Stranglers"
    assert str(tmp_path) in tui.download_outcome_path

    # Verify track was recorded in library
    lib_tracks = lib.get_all()
    assert len(lib_tracks) == 1
    assert lib_tracks[0]["title"] == "Golden Brown"

    # 7. Press Enter on DONE screen returns home to INPUT
    tui.handle_enter()
    assert tui.phase == TUIPhase.INPUT
    assert tui.input_text == ""


def test_tui_download_cancellation_flow(tmp_path):
    import threading
    from zoink.downloader import DownloadJob, DownloadState

    config = Config.get()
    config["download_dir"] = str(tmp_path)

    cancel_called = threading.Event()
    download_started = threading.Event()

    class StallingDownloadManager:
        def __init__(self, config):
            self.config = config
            self.cancelled = False

        def cancel_all(self):
            self.cancelled = True
            cancel_called.set()

        def download(self, track, on_progress=None):
            download_started.set()
            job = DownloadJob(track=track, state=DownloadState.DOWNLOADING, progress=15.0)
            if on_progress:
                on_progress(job)
            # Wait for cancel
            cancel_called.wait(timeout=2.0)
            job.state = DownloadState.CANCELLED
            if on_progress:
                on_progress(job)
            return job

    mock_dl = StallingDownloadManager(config)
    tui = ZoinKTUI(config=config, downloader=mock_dl)

    track = TrackResult(id="t1", title="Golden Brown", artist="The Stranglers")
    tui.inspect_track(track)
    assert tui.phase == TUIPhase.PICKING

    # Trigger zoink
    tui.trigger_zoink()
    assert tui.phase == TUIPhase.DOWNLOADING

    download_started.wait(timeout=2.0)
    assert tui.download_progress == 15.0

    # Cancel via escape
    tui.handle_escape()
    assert cancel_called.is_set()
    assert tui.is_cancelled is True
    # Should have returned to PICKING (prev_phase) or INPUT
    assert tui.phase in (TUIPhase.PICKING, TUIPhase.INPUT)


def test_tui_download_failure_flow(tmp_path):
    import time
    from zoink.downloader import DownloadJob, DownloadState

    config = Config.get()

    class FailingDownloadManager:
        def __init__(self, config):
            self.config = config

        def cancel_all(self):
            pass

        def download(self, track, on_progress=None):
            job = DownloadJob(track=track, state=DownloadState.FAILED, error="Network socket timeout")
            if on_progress:
                on_progress(job)
            return job

    mock_dl = FailingDownloadManager(config)
    tui = ZoinKTUI(config=config, downloader=mock_dl)

    track = TrackResult(id="t1", title="Song", artist="Artist")
    tui.inspect_track(track)
    tui.trigger_zoink()

    for _ in range(50):
        if tui.phase == TUIPhase.ERROR:
            break
        time.sleep(0.02)

    assert tui.phase == TUIPhase.ERROR
    assert "Network socket timeout" in tui.error_message

    # Esc or Enter returns to INPUT
    tui.handle_escape()
    assert tui.phase == TUIPhase.INPUT


def test_tui_download_worker_exception_handled(tmp_path):
    import time

    config = Config.get()

    class ExplodingDownloadManager:
        def __init__(self, config):
            self.config = config

        def cancel_all(self):
            pass

        def download(self, track, on_progress=None):
            raise ConnectionResetError("Remote server closed connection unexpectedly")

    mock_dl = ExplodingDownloadManager(config)
    tui = ZoinKTUI(config=config, downloader=mock_dl)

    track = TrackResult(id="t1", title="Song", artist="Artist")
    tui.inspect_track(track)
    tui.trigger_zoink()

    for _ in range(50):
        if tui.phase == TUIPhase.ERROR:
            break
        time.sleep(0.02)

    assert tui.phase == TUIPhase.ERROR
    assert "Remote server closed connection" in tui.error_message


def test_tui_album_download_flow(tmp_path):
    import time
    from zoink.downloader import DownloadJob, DownloadState

    config = Config.get()
    config["download_dir"] = str(tmp_path)
    lib = Library(config)

    class MockBatchDownloadManager:
        def __init__(self, config):
            self.config = config

        def cancel_all(self):
            pass

        def download_batch(self, tracks, on_progress=None, on_complete=None):
            jobs = []
            for t in tracks:
                out = tmp_path / f"{t.title}.mp3"
                out.write_bytes(b"data")
                job = DownloadJob(track=t, state=DownloadState.DONE, filepath=out)
                jobs.append(job)
                if on_complete:
                    on_complete(job)
            return jobs

    mock_dl = MockBatchDownloadManager(config)
    tui = ZoinKTUI(config=config, library=lib, downloader=mock_dl)

    album = AlbumResult(
        id="alb1",
        title="Test Album",
        artist="Test Artist",
        tracks=[
            TrackResult(id="t1", title="Track 1", artist="Test Artist"),
            TrackResult(id="t2", title="Track 2", artist="Test Artist"),
        ],
    )
    tui.album_result = album
    tui.album_selected_ids = {"t1", "t2"}
    tui.phase = TUIPhase.ALBUM

    tui.handle_enter()
    assert tui.phase == TUIPhase.DOWNLOADING

    for _ in range(50):
        if tui.phase == TUIPhase.DONE:
            break
        time.sleep(0.02)

    assert tui.phase == TUIPhase.DONE
    assert tui.download_outcome_title == "Test Album"
    assert len(lib.get_all()) == 2


def test_tui_cancel_probing_and_searching():
    tui = ZoinKTUI()
    tui.phase = TUIPhase.PROBING
    tui.handle_escape()
    assert tui.phase == TUIPhase.INPUT
    assert tui.is_cancelled is True

    tui.phase = TUIPhase.SEARCHING
    tui.handle_escape()
    assert tui.phase == TUIPhase.INPUT
    assert tui.is_cancelled is True


def test_slash_commands_popup_and_filtering(tui_instance):
    tui = tui_instance
    assert tui.command_suggestions == []

    # Typing '/' triggers suggestion list of all commands
    tui.insert_text("/")
    assert len(tui.command_suggestions) == 7
    rendered = tui.render(80, 24)
    rendered_text = "".join(text for item in rendered for text in [item[1]])
    assert "commands" in rendered_text
    assert "/library" in rendered_text
    assert "/help" in rendered_text

    # Filtering by typing "li"
    tui.insert_text("li")
    assert tui.input_text == "/li"
    assert len(tui.command_suggestions) == 1
    assert tui.command_suggestions[0][0] == "/library"

    # Clearing input removes suggestions
    tui.clear_input()
    assert tui.command_suggestions == []


def test_slash_commands_navigation_and_tab_autocomplete(tui_instance):
    tui = tui_instance
    tui.insert_text("/")
    assert tui.command_cursor == 0

    # Down navigation wraps around
    tui.handle_down()
    assert tui.command_cursor == 1
    tui.handle_down()
    assert tui.command_cursor == 2

    # Up navigation
    tui.handle_up()
    assert tui.command_cursor == 1

    # Up from 0 wraps to bottom
    tui.command_cursor = 0
    tui.handle_up()
    assert tui.command_cursor == len(tui.command_suggestions) - 1

    # Tab autocompletes the highlighted command into input
    tui.command_cursor = 0  # /library
    tui.handle_tab()
    assert tui.input_text == "/library"
    assert tui.input_cursor == len("/library")


def test_slash_command_execution(tui_instance, tmp_path):
    tui = tui_instance

    # 1. /library opens library phase
    tui.insert_text("/library")
    tui.handle_enter()
    assert tui.phase == TUIPhase.LIBRARY

    # 2. /help opens help phase
    tui.go_home()
    tui.insert_text("/help")
    tui.handle_enter()
    assert tui.phase == TUIPhase.HELP
    help_rendered = tui.render(80, 24)
    help_text = "".join(text for item in help_rendered for text in [item[1]])
    assert "ZoinK Guide & Commands" in help_text
    assert "/library" in help_text

    # 3. /theme cycles theme
    tui.go_home()
    initial_theme = tui.theme_mode
    tui.insert_text("/theme")
    tui.handle_enter()
    assert tui.theme_mode != initial_theme

    # 4. /quit requests exit
    tui.go_home()
    tui.insert_text("/quit")
    tui.handle_enter()
    assert tui.should_exit is True


def test_library_full_controls_scrolling_inspection_and_sorting(tui_instance, tmp_path):
    tui = tui_instance
    lib = tui.library

    # Create dummy audio files on disk and index them
    for i in range(15):
        audio_file = tmp_path / f"track_{i:02d}.mp3"
        audio_file.write_bytes(b"dummy mp3 data")
        t = TrackResult(
            id=f"id_{i}",
            title=f"Track {i:02d}",
            artist="Artist " + ("B" if i % 2 == 0 else "A"),
            album="Album Alpha",
            duration=180 + i * 10,
        )
        lib.add_track(audio_file, t)

    tui.open_library()
    assert tui.phase == TUIPhase.LIBRARY
    assert len(tui.library_tracks) == 15
    assert tui.library_cursor == 0
    assert tui.library_scroll_offset == 0

    # Scrolling down beyond page size
    for _ in range(10):
        tui.handle_down()
    assert tui.library_cursor == 10
    assert tui.library_scroll_offset > 0

    # Page up and Page down
    tui.handle_page_up()
    assert tui.library_cursor == 2
    tui.handle_page_down()
    assert tui.library_cursor == 10

    # Sort cycling (recent -> title -> artist -> recent)
    assert tui.library_sort_mode == "recent"
    tui.handle_sort()
    assert tui.library_sort_mode == "title"
    assert tui.library_tracks[0]["title"] <= tui.library_tracks[1]["title"]
    tui.handle_sort()
    assert tui.library_sort_mode == "artist"
    tui.handle_sort()
    assert tui.library_sort_mode == "recent"

    # Track inspection: Enter or i opens LIBRARY_DETAIL
    tui.handle_inspect()
    assert tui.phase == TUIPhase.LIBRARY_DETAIL
    assert tui.selected_library_track is not None

    rendered = tui.render(80, 24)
    rendered_text = "".join(text for item in rendered for text in [item[1]])
    assert "Track Inspection" in rendered_text
    assert tui.selected_library_track["title"] in rendered_text

    # Escape returns to LIBRARY phase
    tui.handle_escape()
    assert tui.phase == TUIPhase.LIBRARY


def test_library_playback_and_stop(tui_instance, tmp_path, monkeypatch):
    import subprocess
    tui = tui_instance
    lib = tui.library

    audio_file = tmp_path / "song.mp3"
    audio_file.write_bytes(b"data")
    t = TrackResult(id="s1", title="Song", artist="Artist", duration=200)
    lib.add_track(audio_file, t)
    tui.open_library()

    # Mock media player
    class DummyPopen:
        def __init__(self, *args, **kwargs):
            pass
        def terminate(self):
            pass
        def wait(self, timeout=None):
            pass
        def kill(self):
            pass

    monkeypatch.setattr(subprocess, "Popen", DummyPopen)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/mpv" if name == "mpv" else None)

    # Play track via handle_play / Space
    tui.handle_play()
    assert tui.playback_process is not None
    assert "Song" in tui.playback_status_text

    # Stop playback via handle_stop / s
    tui.handle_stop()
    assert tui.playback_process is None
    assert tui.playback_status_text == ""


def test_library_delete_confirmation_flow(tui_instance, tmp_path):
    tui = tui_instance
    lib = tui.library

    audio_file = tmp_path / "delete_me.mp3"
    audio_file.write_bytes(b"data")
    t = TrackResult(id="del_id", title="To Delete", artist="Artist", duration=100)
    lib.add_track(audio_file, t)
    tui.open_library()
    assert len(tui.library_tracks) == 1

    # Press delete -> enters confirmation state
    tui.handle_delete()
    assert tui.confirm_delete_id == "del_id"
    assert "Delete 'To Delete'?" in tui.library_status_message

    # 'n' cancels confirmation
    tui.handle_confirm_no()
    assert tui.confirm_delete_id is None
    assert audio_file.exists()
    assert len(tui.library_tracks) == 1

    # Press delete again and confirm with 'y'
    tui.handle_delete()
    assert tui.confirm_delete_id == "del_id"
    tui.handle_confirm_yes()
    assert tui.confirm_delete_id is None
    assert not audio_file.exists()
    assert len(tui.library_tracks) == 0


def test_tui_config_screen_interaction(tui_instance):
    tui = tui_instance
    cfg = tui.config

    # 1. Open config via slash command
    tui.insert_text("/config")
    tui.handle_enter()
    assert tui.phase == TUIPhase.CONFIG
    assert tui.config_cursor == 0

    # 2. Check items
    items = tui._get_config_items()
    assert len(items) >= 8
    assert items[0]["key"] == "user_name"
    assert items[0]["label"] == "Web Player Name"

    # 3. Edit user_name
    tui.handle_edit_config()
    assert tui.config_editing is True
    tui.config_edit_value = ""
    tui.config_edit_cursor = 0
    tui.insert_text("Custom Listener")
    tui.handle_enter()
    assert tui.config_editing is False
    assert cfg.user_name == "Custom Listener"
    assert "Custom Listener" in tui.config_status_message

    # 4. Navigate to Audio Format and cycle choice
    tui.handle_down()
    assert tui.config_cursor == 1
    orig_fmt = cfg.output_format
    tui.handle_space()
    assert cfg.output_format != orig_fmt

    # 5. Render screen
    rendered = tui.render(80, 24)
    text = "".join(chunk[1] for chunk in rendered)
    assert "Settings & Preferences" in text
    assert "Custom Listener" in text

    # 6. Escape back to home
    tui.handle_escape()
    assert tui.phase == TUIPhase.INPUT



