"""Terminal UI for ZoinK built with prompt_toolkit and modern terminal ergonomics."""

from __future__ import annotations

import os
import shutil
import sys
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

    def on_refresh() -> None:
        if app_ref[0] and app_ref[0].is_running:
            if tui.should_exit:
                if app_ref[0].loop and not app_ref[0].loop.is_closed():
                    app_ref[0].loop.call_soon_threadsafe(lambda: app_ref[0].exit(result=0))
                else:
                    app_ref[0].exit(result=0)
                return
            try:
                app_ref[0].invalidate()
            except Exception:
                pass

    def on_theme_change(new_mode: str) -> None:
        if app_ref[0]:
            app_ref[0].style = get_style(new_mode)
            on_refresh()

    tui = ZoinKTUI(
        config=config,
        provider=provider,
        library=library,
        downloader=dl_manager,
        on_invalidate=on_refresh,
        on_refresh=on_refresh,
        on_theme_change=on_theme_change,
    )

    kb = KeyBindings()
    is_input_phase = Condition(lambda: tui.phase == TUIPhase.INPUT)
    not_input_phase = Condition(lambda: tui.phase != TUIPhase.INPUT)

    # --- INPUT PHASE KEYBINDINGS ---
    @kb.add("<any>", filter=is_input_phase)
    def _input_char(event):
        if event.data:
            tui.insert_text(event.data)

    @kb.add("up", filter=is_input_phase)
    def _input_up(event):
        if tui.command_suggestions:
            tui.handle_up()

    @kb.add("down", filter=is_input_phase)
    def _input_down(event):
        if tui.command_suggestions:
            tui.handle_down()

    @kb.add("tab", filter=is_input_phase)
    def _input_tab(event):
        if tui.command_suggestions:
            tui.handle_tab()

    @kb.add("backspace", filter=is_input_phase)
    def _input_backspace(event):
        tui.delete_backwards()

    @kb.add("delete", filter=is_input_phase)
    def _input_delete(event):
        tui.delete_forwards()

    @kb.add("left", filter=is_input_phase)
    def _input_left(event):
        tui.move_cursor_left()

    @kb.add("right", filter=is_input_phase)
    def _input_right(event):
        tui.move_cursor_right()

    @kb.add("home", filter=is_input_phase)
    @kb.add("c-a", filter=is_input_phase)
    def _input_home(event):
        tui.move_cursor_home()

    @kb.add("end", filter=is_input_phase)
    @kb.add("c-e", filter=is_input_phase)
    def _input_end(event):
        tui.move_cursor_end()

    @kb.add("c-u", filter=is_input_phase)
    def _input_clear(event):
        tui.clear_input()

    @kb.add("c-w", filter=is_input_phase)
    def _input_del_word(event):
        tui.delete_word_backwards()

    # --- NON-INPUT NAVIGATION & CONTROLS KEYBINDINGS ---
    @kb.add("up", filter=not_input_phase)
    @kb.add("k", filter=not_input_phase)
    def _up(event):
        tui.handle_up()

    @kb.add("down", filter=not_input_phase)
    @kb.add("j", filter=not_input_phase)
    def _down(event):
        tui.handle_down()

    @kb.add("pageup", filter=not_input_phase)
    def _page_up(event):
        tui.handle_page_up()

    @kb.add("pagedown", filter=not_input_phase)
    def _page_down(event):
        tui.handle_page_down()

    @kb.add("space", filter=not_input_phase)
    def _space(event):
        tui.handle_space()

    @kb.add("p", filter=not_input_phase)
    def _play(event):
        tui.handle_play()

    @kb.add("s", filter=not_input_phase)
    def _stop_or_search(event):
        if tui.phase in (TUIPhase.LIBRARY, TUIPhase.LIBRARY_DETAIL):
            tui.handle_stop()
        else:
            tui.go_home()

    @kb.add("d", filter=not_input_phase)
    def _delete(event):
        tui.handle_delete()

    @kb.add("y", filter=not_input_phase)
    def _confirm_yes(event):
        if tui.confirm_delete_id:
            tui.handle_confirm_yes()

    @kb.add("n", filter=not_input_phase)
    def _confirm_no(event):
        if tui.confirm_delete_id:
            tui.handle_confirm_no()

    @kb.add("r", filter=not_input_phase)
    def _rescan(event):
        tui.handle_rescan()

    @kb.add("o", filter=not_input_phase)
    def _sort(event):
        tui.handle_sort()

    @kb.add("i", filter=not_input_phase)
    def _inspect(event):
        tui.handle_inspect()

    @kb.add("?", filter=not_input_phase)
    def _help(event):
        tui.open_help()

    @kb.add("a", filter=not_input_phase)
    def _album(event):
        tui.handle_album_action()

    @kb.add("A", filter=not_input_phase)
    def _album_all(event):
        tui._select_all_album()

    @kb.add("w", filter=not_input_phase)
    def _web(event):
        tui.open_web_player()

    @kb.add("/", filter=not_input_phase)
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

    @kb.add("l", filter=not_input_phase)
    def _library_non_input(event):
        if tui.phase in (TUIPhase.LIBRARY, TUIPhase.LIBRARY_DETAIL):
            tui.go_home()
        else:
            tui.open_library()

    @kb.add("c-t")
    def _theme(event):
        tui.handle_cycle_theme()

    @kb.add("q", filter=not_input_phase)
    def _quit_non_input(event):
        if tui.phase in (TUIPhase.DONE, TUIPhase.ERROR, TUIPhase.SEARCH_RESULTS, TUIPhase.LIBRARY, TUIPhase.LIBRARY_DETAIL, TUIPhase.HELP):
            tui.go_home()
        else:
            tui.should_exit = True
            tui.cancel_current()
            tui.stop_audio()
            event.app.exit(result=0)

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
        tui.should_exit = True
        tui.cancel_current()
        tui.stop_audio()
        event.app.exit(result=0)

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
        tui.should_exit = True
        tui.cancel_current()
        tui.stop_audio()
        # Full terminal restoration (alternate screen, cursor, mouse modes)
        if not no_clear:
            sys.stdout.write("\033[?1049l\033[?25h\033[?1000l\033[?1002l\033[?1003l\033[?1006l")
            sys.stdout.flush()

        # Clean polite exit summary if something was downloaded
        if tui.download_outcome_path:
            print(f"\n✓ ZoinK: Downloaded {tui.download_outcome_title} to {tui.download_outcome_path}")
        print(f"\n✓ ZoinK stopped. Goodbye! {ZoinKTUI.WATERMARK}\n")
        sys.stdout.flush()


__all__ = ["run_tui", "ZoinKTUI", "TUIPhase"]
