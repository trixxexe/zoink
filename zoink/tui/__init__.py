"""Terminal UI for ZoinK built with prompt_toolkit and modern terminal ergonomics."""

from __future__ import annotations

import os
import shutil
import sys
import threading
from typing import Optional

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl

from zoink import __version__
from zoink.config import Config
from zoink.downloader import DownloadManager
from zoink.library import Library
from zoink.providers import YouTubeProvider
from zoink.tui.app import TUIPhase, ZoinKTUI, is_probably_url
from zoink.tui.theme import get_style


def run_tui(no_clear: bool = False, non_interactive: bool = False) -> None:
    """Launch the interactive ZoinK TUI application."""
    config = Config.get()
    provider = YouTubeProvider()
    library = Library(config)
    dl_manager = DownloadManager(config)

    # Non-interactive fallback (e.g. redirected stdin/pipes or test suites)
    if non_interactive or not sys.stdin.isatty():
        print(f"ZoinK v{__version__}  ♪ Music Downloader {ZoinKTUI.WATERMARK}")
        print(f"Ready. Configured download dir: {config.download_dir}")
        return

    app_ref: list[Optional[Application]] = [None]
    exit_lock = threading.Lock()
    has_exited = False

    def safe_exit(result: int = 0) -> None:
        nonlocal has_exited
        with exit_lock:
            if has_exited:
                return
            has_exited = True

        # Idempotently shutdown all TUI background tasks and audio
        tui.shutdown()

        app = app_ref[0]
        if app is None:
            return

        def _do_exit():
            if app.is_running:
                try:
                    if hasattr(app, "future") and app.future and not app.future.done():
                        app.exit(result=result)
                except Exception:
                    pass

        if app.is_running:
            loop = getattr(app, "loop", None)
            if loop and not loop.is_closed():
                try:
                    import asyncio
                    try:
                        current_loop = asyncio.get_running_loop()
                    except RuntimeError:
                        current_loop = None
                    if current_loop is loop:
                        _do_exit()
                    else:
                        loop.call_soon_threadsafe(_do_exit)
                except Exception:
                    _do_exit()
            else:
                _do_exit()

    def on_refresh() -> None:
        app = app_ref[0]
        if not app or not app.is_running or tui.should_exit:
            return
        try:
            app.invalidate()
        except Exception:
            pass

    def on_theme_change(new_mode: str) -> None:
        app = app_ref[0]
        if app and app.is_running:
            app.style = get_style(new_mode)
            on_refresh()

    tui = ZoinKTUI(
        config=config,
        provider=provider,
        library=library,
        downloader=dl_manager,
        on_invalidate=on_refresh,
        on_refresh=on_refresh,
        on_theme_change=on_theme_change,
        on_request_exit=lambda: safe_exit(0),
    )

    kb = KeyBindings()
    is_typing_active = Condition(
        lambda: tui.phase == TUIPhase.INPUT
        or (tui.phase == TUIPhase.CONFIG and getattr(tui, "config_editing", False))
    )
    not_typing_active = Condition(
        lambda: not (
            tui.phase == TUIPhase.INPUT
            or (tui.phase == TUIPhase.CONFIG and getattr(tui, "config_editing", False))
        )
    )

    # --- TEXT ENTRY KEYBINDINGS (INPUT OR INLINE CONFIG EDITING) ---
    @kb.add("<any>", filter=is_typing_active)
    def _input_char(event):
        if event.data:
            tui.insert_text(event.data)

    @kb.add("up", filter=is_typing_active)
    def _input_up(event):
        if tui.phase == TUIPhase.INPUT and tui.command_suggestions:
            tui.handle_up()

    @kb.add("down", filter=is_typing_active)
    def _input_down(event):
        if tui.phase == TUIPhase.INPUT and tui.command_suggestions:
            tui.handle_down()

    @kb.add("tab", filter=is_typing_active)
    def _input_tab(event):
        if tui.phase == TUIPhase.INPUT and tui.command_suggestions:
            tui.handle_tab()

    @kb.add("backspace", filter=is_typing_active)
    def _input_backspace(event):
        tui.delete_backwards()

    @kb.add("delete", filter=is_typing_active)
    def _input_delete(event):
        tui.delete_forwards()

    @kb.add("left", filter=is_typing_active)
    def _input_left(event):
        tui.move_cursor_left()

    @kb.add("right", filter=is_typing_active)
    def _input_right(event):
        tui.move_cursor_right()

    @kb.add("home", filter=is_typing_active)
    @kb.add("c-a", filter=is_typing_active)
    def _input_home(event):
        tui.move_cursor_home()

    @kb.add("end", filter=is_typing_active)
    @kb.add("c-e", filter=is_typing_active)
    def _input_end(event):
        tui.move_cursor_end()

    @kb.add("c-u", filter=is_typing_active)
    def _input_clear(event):
        tui.clear_input()

    @kb.add("c-w", filter=is_typing_active)
    def _input_del_word(event):
        tui.delete_word_backwards()

    # --- NON-TYPING NAVIGATION & CONTROLS KEYBINDINGS ---
    @kb.add("up", filter=not_typing_active)
    @kb.add("k", filter=not_typing_active)
    def _up(event):
        tui.handle_up()

    @kb.add("down", filter=not_typing_active)
    @kb.add("j", filter=not_typing_active)
    def _down(event):
        tui.handle_down()

    @kb.add("left", filter=not_typing_active)
    def _left_nav(event):
        tui.handle_left()

    @kb.add("right", filter=not_typing_active)
    def _right_nav(event):
        tui.handle_right()

    @kb.add("e", filter=not_typing_active)
    def _edit(event):
        if tui.phase == TUIPhase.CONFIG:
            tui.handle_edit_config()

    @kb.add("pageup", filter=not_typing_active)
    def _page_up(event):
        tui.handle_page_up()

    @kb.add("pagedown", filter=not_typing_active)
    def _page_down(event):
        tui.handle_page_down()

    @kb.add("space", filter=not_typing_active)
    def _space(event):
        tui.handle_space()

    @kb.add("p", filter=not_typing_active)
    def _play(event):
        tui.handle_play()

    @kb.add("s", filter=not_typing_active)
    def _stop_or_search(event):
        if tui.phase in (TUIPhase.LIBRARY, TUIPhase.LIBRARY_DETAIL):
            tui.handle_stop()
        else:
            tui.go_home()

    @kb.add("d", filter=not_typing_active)
    def _delete(event):
        tui.handle_delete()

    @kb.add("y", filter=not_typing_active)
    def _confirm_yes(event):
        if tui.confirm_delete_id:
            tui.handle_confirm_yes()

    @kb.add("n", filter=not_typing_active)
    def _confirm_no(event):
        if tui.confirm_delete_id:
            tui.handle_confirm_no()

    @kb.add("c", filter=not_typing_active)
    def _convert(event):
        if tui.phase in (TUIPhase.LIBRARY, TUIPhase.LIBRARY_DETAIL):
            tui.open_convert()

    @kb.add("r", filter=not_typing_active)
    def _rescan(event):
        if tui.phase == TUIPhase.CONVERT:
            tui.handle_toggle_convert_replace()
        else:
            tui.handle_rescan()

    @kb.add("o", filter=not_typing_active)
    def _sort(event):
        tui.handle_sort()

    @kb.add("i", filter=not_typing_active)
    def _inspect(event):
        tui.handle_inspect()

    @kb.add("?", filter=not_typing_active)
    def _help(event):
        tui.open_help()

    @kb.add("a", filter=not_typing_active)
    def _album(event):
        tui.handle_album_action()

    @kb.add("A", filter=not_typing_active)
    def _album_all(event):
        tui._select_all_album()

    @kb.add("w", filter=not_typing_active)
    def _web(event):
        tui.open_web_player()

    @kb.add("/", filter=not_typing_active)
    def _search_slash(event):
        tui.go_home()
        tui.insert_text("/")

    # --- UNIVERSAL KEYBINDINGS ---
    @kb.add("enter")
    def _enter(event):
        tui.handle_enter()

    @kb.add("escape")
    def _escape(event):
        tui.handle_escape()

    @kb.add("c-l")
    def _library(event):
        if tui.phase == TUIPhase.LIBRARY:
            tui.go_home()
        else:
            tui.open_library()

    @kb.add("l", filter=not_typing_active)
    def _library_non_input(event):
        if tui.phase in (TUIPhase.LIBRARY, TUIPhase.LIBRARY_DETAIL):
            tui.go_home()
        else:
            tui.open_library()

    @kb.add("c-t")
    def _theme(event):
        tui.handle_cycle_theme()

    @kb.add("q", filter=not_typing_active)
    def _quit_non_input(event):
        if tui.phase in (TUIPhase.DONE, TUIPhase.ERROR, TUIPhase.SEARCH_RESULTS, TUIPhase.LIBRARY, TUIPhase.LIBRARY_DETAIL, TUIPhase.HELP, TUIPhase.CONFIG, TUIPhase.CONVERT):
            tui.go_home()
        else:
            safe_exit(0)

    @kb.add(Keys.BracketedPaste)
    def _paste(event):
        data = event.data
        if not data:
            return
        if is_probably_url(data):
            tui.input_text = data.strip()
            tui.input_cursor = len(tui.input_text)
            tui.handle_submit()
        elif tui.phase == TUIPhase.INPUT:
            tui.insert_text(data)

    @kb.add("c-c")
    @kb.add("c-d")
    def _exit(event):
        safe_exit(0)

    # --- Screen Content & Layout ---
    def get_screen_content():
        width, height = shutil.get_terminal_size((80, 24))
        return tui.render(width, height)

    main_control = FormattedTextControl(get_screen_content)
    main_window = Window(content=main_control)
    layout = Layout(HSplit([main_window]), focused_element=main_window)

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=get_style(tui.theme_mode),
        full_screen=True,
        mouse_support=True,
    )
    app_ref[0] = app

    try:
        app.run()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        safe_exit(0)
        # Full terminal restoration (alternate screen, cursor, mouse modes, bracketed paste)
        if not no_clear:
            sys.stdout.write("\033[?1049l\033[?25h\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?2004l")
            sys.stdout.flush()

        # Clean polite exit summary if something was downloaded
        if tui.download_outcome_path:
            print(f"\n✓ ZoinK: Downloaded {tui.download_outcome_title} to {tui.download_outcome_path}")
        print("\nGoodbye from ZoinK.\n")
        sys.stdout.flush()


__all__ = ["run_tui", "ZoinKTUI", "TUIPhase"]
