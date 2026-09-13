"""CLI entry point for ZoinK."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from zoink import __version__
from zoink.config import Config, CONFIG_FILE

console = Console()
WATERMARK = ": made by Ritam/Trixx"


def _print_header(subtitle: str = "") -> None:
    text = f"[bold cyan]ZoinK v{__version__}[/bold cyan] [dim]{WATERMARK}[/dim]"
    if subtitle:
        text += f" — [dim]{subtitle}[/dim]"
    console.print(text)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zoink",
        description=f"ZoinK v{__version__} — TUI Song Downloader + Web Music Player {WATERMARK}",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ZoinK {__version__} {WATERMARK}",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Don't clear screen on launch",
    )

    sub = parser.add_subparsers(dest="command")

    # tui subcommand (optional explicit alias)
    sub.add_parser("tui", help="Launch interactive Terminal UI (default)")

    # search subcommand
    search_p = sub.add_parser("search", help="Search for music tracks")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("-n", "--limit", type=int, default=10, help="Number of results (default: 10)")
    search_p.add_argument("-f", "--format", choices=["mp3", "m4a", "flac", "opus"], help="Audio format")
    search_p.add_argument("-q", "--quality", choices=["best", "320", "256", "192", "128"], help="Bitrate/quality")
    search_p.add_argument("-y", "--yes", action="store_true", help="Automatically download top result")

    # download subcommand
    dl_p = sub.add_parser("download", help="Download a track by search query or URL")
    dl_p.add_argument("target", help="Song name, YouTube URL, or video ID")
    dl_p.add_argument("-f", "--format", choices=["mp3", "m4a", "flac", "opus"], help="Audio format")
    dl_p.add_argument("-q", "--quality", choices=["best", "320", "256", "192", "128"], help="Bitrate/quality")
    dl_p.add_argument("-o", "--output-dir", help="Output directory")

    # album subcommand
    album_p = sub.add_parser("album", help="Search and download full album")
    album_p.add_argument("query", help="Album name or playlist URL")
    album_p.add_argument("-f", "--format", choices=["mp3", "m4a", "flac", "opus"], help="Audio format")
    album_p.add_argument("-q", "--quality", choices=["best", "320", "256", "192", "128"], help="Bitrate/quality")
    album_p.add_argument("-y", "--yes", action="store_true", help="Download entire album without prompt")

    # serve subcommand
    # serve subcommand (also aliased as 'web')
    serve_p = sub.add_parser("serve", aliases=["web"], help="Start the web music player")
    serve_p.add_argument("-p", "--port", type=int, help="Port (default: 5050)")
    serve_p.add_argument("--host", help="Bind address (default: 127.0.0.1)")
    serve_p.add_argument("--lan", action="store_true", help="Allow LAN access (binds 0.0.0.0)")
    serve_p.add_argument("--open", action="store_true", help="Open web player in default browser")

    # scan subcommand
    scan_p = sub.add_parser("scan", help="Scan download directory and update music library index")
    scan_p.add_argument("-d", "--dir", help="Directory to scan (default: configured download_dir)")
    scan_p.add_argument("--no-prune", action="store_true", help="Do not prune missing files from database")

    # config subcommand
    config_p = sub.add_parser("config", help="View or modify configuration")
    config_p.add_argument("action", nargs="?", choices=["get", "set", "show", "path", "reset"], help="Action to perform")
    config_p.add_argument("key", nargs="?", help="Configuration key")
    config_p.add_argument("value", nargs="?", help="Configuration value (for set)")
    config_p.add_argument("--get", metavar="KEY", help="Get a specific config value")
    config_p.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="Set a specific config value")
    config_p.add_argument("--path", action="store_true", help="Show config file path")
    config_p.add_argument("--reset", action="store_true", help="Reset configuration to defaults")

    args = parser.parse_args(argv)

    if args.command == "search":
        return _cmd_search(args)
    elif args.command == "download":
        return _cmd_download(args)
    elif args.command == "album":
        return _cmd_album(args)
    elif args.command in ("serve", "web"):
        return _cmd_serve(args)
    elif args.command == "scan":
        return _cmd_scan(args)
    elif args.command == "config":
        return _cmd_config(args)
    else:
        # Default: launch TUI
        from zoink.tui import run_tui
        try:
            run_tui(no_clear=args.no_clear)
        except (KeyboardInterrupt, SystemExit):
            pass
        return 0


def _cmd_search(args) -> int:
    _print_header("Search")
    from zoink.config import Config
    from zoink.downloader import DownloadManager, DownloadJob, DownloadState
    from zoink.library import Library
    from zoink.providers import YouTubeProvider

    config = Config.get()
    if args.format:
        config["output_format"] = args.format
    if args.quality:
        config["quality"] = args.quality

    provider = YouTubeProvider()
    console.print(f"Searching for: [bold]{args.query}[/bold]...")
    results = provider.search_tracks(args.query, limit=args.limit)
    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return 1

    table = Table(box=None, show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", width=3)
    table.add_column("Title", ratio=3)
    table.add_column("Artist", ratio=2)
    table.add_column("Duration", justify="right", width=8)

    for i, t in enumerate(results, 1):
        table.add_row(str(i), t.title, t.artist, t.duration_str)

    console.print(Panel(table, border_style="bright_black"))

    if args.yes:
        track = results[0]
        return _download_and_save(track, config)

    console.print("[dim]Enter number to download, 'all' for all, or 'q' to quit:[/dim]")
    try:
        choice = input("  > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return 130

    if choice in ("q", "quit", ""):
        return 0

    if choice == "all":
        return _download_batch_cli(results, config)

    if choice.isdigit() and 1 <= int(choice) <= len(results):
        track = results[int(choice) - 1]
        return _download_and_save(track, config)

    console.print("[red]Invalid selection.[/red]")
    return 1


def _cmd_download(args) -> int:
    _print_header("Download")
    from zoink.config import Config
    from zoink.providers import YouTubeProvider

    config = Config.get()
    if args.format:
        config["output_format"] = args.format
    if args.quality:
        config["quality"] = args.quality
    if args.output_dir:
        config["download_dir"] = args.output_dir

    provider = YouTubeProvider()
    target = args.target.strip()

    if target.startswith("http://") or target.startswith("https://"):
        console.print(f"Resolving URL: [bold]{target}[/bold]...")
        track = provider.resolve_track(target)
        if not track:
            console.print("[red]Failed to resolve track from URL.[/red]")
            return 1
    else:
        console.print(f"Searching for top match: [bold]{target}[/bold]...")
        results = provider.search_tracks(target, limit=1)
        if not results:
            console.print("[red]No match found for query.[/red]")
            return 1
        track = results[0]

    return _download_and_save(track, config)


def _cmd_album(args) -> int:
    _print_header("Album")
    from zoink.config import Config
    from zoink.providers import YouTubeProvider

    config = Config.get()
    if args.format:
        config["output_format"] = args.format
    if args.quality:
        config["quality"] = args.quality

    provider = YouTubeProvider()
    console.print(f"Resolving album: [bold]{args.query}[/bold]...")
    album = provider.resolve_album(args.query)

    if not album or not album.tracks:
        console.print("[red]Could not find or resolve album tracks.[/red]")
        return 1

    console.print(f"\n[bold]{album.title}[/bold] — {album.artist} ({album.year or 'N/A'})")
    console.print(f"[dim]{len(album.tracks)} tracks found[/dim]\n")

    table = Table(box=None, show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", width=3)
    table.add_column("Title", ratio=3)
    table.add_column("Duration", justify="right", width=8)

    for i, t in enumerate(album.tracks, 1):
        table.add_row(str(i), t.title, t.duration_str)

    console.print(Panel(table, border_style="bright_black"))

    if not args.yes:
        console.print("[dim]Download entire album? [Y/n]:[/dim]")
        try:
            choice = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 130
        if choice not in ("y", "yes", ""):
            console.print("[dim]Aborted.[/dim]")
            return 0

    return _download_batch_cli(album.tracks, config)


def _download_and_save(track, config) -> int:
    from zoink.downloader import DownloadManager, DownloadJob, DownloadState
    from zoink.library import Library

    console.print(f"\n[cyan]Downloading:[/cyan] [bold]{track.title}[/bold] — {track.artist}")
    dl = DownloadManager(config)
    library = Library(config)

    def on_progress(job: DownloadJob):
        if job.state == DownloadState.DOWNLOADING:
            bar_len = 28
            filled = int(bar_len * job.progress / 100)
            bar = "█" * filled + "░" * (bar_len - filled)
            sys.stdout.write(f"\r  [{bar}] {job.progress:5.1f}%")
            sys.stdout.flush()
        elif job.state == DownloadState.DONE:
            sys.stdout.write(f"\r  [green]✓[/green] Saved to {job.filepath}          \n")
            sys.stdout.flush()
        elif job.state == DownloadState.FAILED:
            sys.stdout.write(f"\r  [red]✗[/red] Failed: {job.error}          \n")
            sys.stdout.flush()

    job = dl.download(track, on_progress=on_progress)
    if job.state == DownloadState.DONE and job.filepath:
        library.add_track(job.filepath, track)
        return 0
    return 1


def _download_batch_cli(tracks: list, config) -> int:
    from zoink.downloader import DownloadManager, DownloadJob, DownloadState
    from zoink.library import Library

    console.print(f"\n[cyan]Starting batch download for {len(tracks)} tracks...[/cyan]")
    dl = DownloadManager(config)
    library = Library(config)
    completed = 0

    def on_complete(job: DownloadJob):
        nonlocal completed
        completed += 1
        if job.state == DownloadState.DONE:
            console.print(f"  [green]✓[/green] [{completed}/{len(tracks)}] {job.track.title}")
            if job.filepath:
                library.add_track(job.filepath, job.track)
        else:
            console.print(f"  [red]✗[/red] [{completed}/{len(tracks)}] {job.track.title} ({job.error})")

    jobs = dl.download_batch(tracks, on_complete=on_complete)
    done = sum(1 for j in jobs if j.state == DownloadState.DONE)
    failed = sum(1 for j in jobs if j.state == DownloadState.FAILED)
    console.print(f"\n[bold green]{done} succeeded[/bold green], [bold red]{failed} failed[/bold red]")
    return 0 if failed == 0 else 1


def _cmd_serve(args) -> int:
    _print_header("Web Player")
    from zoink.config import Config
    from zoink.web import start_server

    config = Config.get()
    if getattr(args, "port", None):
        config["server_port"] = args.port
    if getattr(args, "host", None):
        config["server_host"] = args.host
    if getattr(args, "lan", False):
        config["server_lan"] = True

    if getattr(args, "open", False):
        import webbrowser
        host = "127.0.0.1" if config.server_host in ("0.0.0.0", "127.0.0.1") else config.server_host
        webbrowser.open(f"http://{host}:{config.server_port}")

    try:
        start_server(config)
    except KeyboardInterrupt:
        console.print("\n[dim]Web server stopped.[/dim]")
    return 0


def _cmd_scan(args) -> int:
    _print_header("Library Scanner")
    from zoink.config import Config
    from zoink.library import Library

    config = Config.get()
    scan_dir = Path(args.dir) if args.dir else config.download_dir
    prune = not args.no_prune

    console.print(f"Scanning directory: [bold]{scan_dir}[/bold] (prune={prune})...")
    lib = Library(config)
    count = lib.scan_directory(directory=scan_dir, prune=prune)
    console.print(f"[green]✓[/green] Indexed [bold]{count}[/bold] new or updated tracks.")
    console.print(f"Total library size: [bold]{lib.count()}[/bold] tracks.")
    return 0


def _cmd_config(args) -> int:
    _print_header("Configuration")
    config = Config.get()

    action = getattr(args, "action", None)
    if action == "path" or args.path:
        console.print(f"Config path: [bold]{CONFIG_FILE}[/bold]")
        return 0

    if action == "reset" or args.reset:
        config.reset()
        console.print("[green]✓[/green] Configuration reset to defaults.")
        return 0

    get_key = args.get or (args.key if action == "get" else None)
    if get_key:
        val = config.get_key(get_key)
        console.print(f"{get_key}: [bold]{val}[/bold]")
        return 0

    if args.set:
        key, val = args.set
        config.set_key(key, val)
        console.print(f"[green]✓[/green] Set [bold]{key}[/bold] = [bold]{val}[/bold]")
        return 0
    elif action == "set" and args.key and args.value:
        config.set_key(args.key, args.value)
        console.print(f"[green]✓[/green] Set [bold]{args.key}[/bold] = [bold]{args.value}[/bold]")
        return 0

    table = Table(box=None, show_header=True, header_style="bold cyan")
    table.add_column("Setting", ratio=1)
    table.add_column("Value", ratio=2)

    for k, v in sorted(config._data.items()):
        table.add_row(k, str(v))

    console.print(Panel(table, title=f"Config ({CONFIG_FILE})", border_style="bright_black"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n✓ ZoinK stopped. Goodbye! {WATERMARK}\n")
        sys.exit(130)
