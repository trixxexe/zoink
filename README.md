# ZoinK 🎵

> **Fast, Termux/Android-first & Linux Music Downloader + Minimal AMOLED Web Player**

ZoinK is a standalone, terminal-first music downloader and local audio streaming player designed for performance and reliability on Android (Termux) and Linux desktop/server environments.

It is a **yt-dlp wrapper in TUI** with a **modern AMOLED Spotify-style local web player**, underpinned by a multi-format audio conversion and tagging engine.

---

## ✨ Features

- **⚡ Blazing Fast Architecture**: In-memory caching for artwork and lyrics, optimized pipe-based conversion, and WAL-mode SQLite indexing.
- **🎨 Minimalistic TUI**: Distraction-free, centered terminal interface with smooth animations, audio playback preview, slash commands, and keyboard/mouse navigation.
- **📱 Minimal AMOLED Web Player**: Clean Spotify-style web interface with dedicated responsive layouts for mobile and desktop, HTTP 206 partial-range streaming, instant search, and background download management.
- **📦 Multi-Container Audio Support**: Native and converted support for **MP3**, **M4A (AAC)**, **FLAC**, **OGG**, and **Opus**.
- **🏷️ Automated Tagging & Cover Art**: Embedded high-resolution cover artwork from iTunes/sources and synchronized/plain lyrics from LRCLIB with yt-dlp subtitle fallbacks.
- **🔒 Atomic Staging & Integrity Checks**: Files are staged in temporary isolation, validated against real audio container headers, and atomically moved to destination paths to prevent corrupt or partial files.
- **🗂️ SQLite Music Library**: Fast incremental library scanning with mtime cache checks, album and artist grouping, and ZIP export.
- **⏹️ Graceful Lifecycle Management**: Completely idempotent shutdown handling (`Ctrl+C`, `Ctrl+D`, `q`), clean terminal restoration, and cooperative background cancellation.

---

## 🛠️ Requirements

- **Python**: `>= 3.10`
- **FFmpeg**: Required for audio extraction, container transcoding, and artwork processing.

---

## 🚀 Installation

### Android (Termux)

```bash
# 1. Update packages and install dependencies
pkg update && pkg upgrade -y
pkg install -y python ffmpeg git

# (Optional) For terminal audio playback inside Termux:
pkg install -y termux-api

# 2. Clone repository and install
git clone https://github.com/zoink-music/zoink.git
cd zoink
pip install -e .
zoink
```

### Debian / Ubuntu / Raspberry Pi OS

```bash
# 1. Install system dependencies
sudo apt update
sudo apt install -y python3 python3-pip ffmpeg git

# 2. Clone repository and install
git clone https://github.com/zoink-music/zoink.git
cd zoink
pip install -e .
zoink
```

### Arch Linux

```bash
sudo pacman -S python python-pip ffmpeg git
git clone https://github.com/zoink-music/zoink.git
cd zoink
pip install -e .
zoink
```

---

## 🎯 Quick Start & CLI Usage

### 1. Interactive Terminal UI (Default)

Launch the interactive centered TUI:

```bash
zoink
```

Directly launch with a search query or URL:

```bash
zoink "Daft Punk Get Lucky"
zoink "https://www.youtube.com/watch?v=5NV6Rdv1a3I"
```

### 2. Local Web Player & Server

Launch the local web player at `http://127.0.0.1:5050`:

```bash
zoink web --open
```

Expose across your Local Area Network (LAN):

```bash
zoink web --host 0.0.0.0 --port 5050
```

> [!WARNING]
> **LAN Security Notice**: Running `zoink web --host 0.0.0.0` allows any device on your local network (Wi-Fi/LAN) to browse your library, stream audio, and trigger downloads. Only use this on trusted private networks.

### 3. CLI Search

```bash
zoink search "Pink Floyd Time"
```

### 4. Incremental Library Scanning

Scan your configured download folder (or an arbitrary folder) into the local SQLite database:

```bash
zoink scan
zoink scan /path/to/my/music --prune
```

### 5. Configuration Management

View or modify persistent settings:

```bash
# Show full configuration
zoink config show

# Get a specific value
zoink config get output_format

# Set configuration options
zoink config set output_format flac
zoink config set quality lossless
zoink config set download_dir ~/Music
```

---

## ⌨️ TUI Keybindings & Slash Commands

| Key / Command | Action |
|---|---|
| <kbd>Enter</kbd> | Search / Select track / Trigger download |
| <kbd>Esc</kbd> | Go back / Cancel active background operation |
| <kbd>↑</kbd> / <kbd>↓</kbd> or <kbd>k</kbd> / <kbd>j</kbd> | Navigate search results and menus |
| <kbd>Space</kbd> | Play / Stop audio preview |
| <kbd>Ctrl+C</kbd> / <kbd>Ctrl+D</kbd> / <kbd>q</kbd> | Graceful exit with terminal state restoration |
| `/theme` | Cycle UI theme (`auto`, `dark`, `amoled`, `light`) |
| `/format` | Quick toggle output format (`mp3`, `m4a`, `flac`, `opus`, `ogg`) |
| `/quality` | Set audio quality preference |
| `/config` | Open interactive configuration editor |
| `/help` | Show command and keybinding cheat sheet |
| `/quit` | Exit ZoinK |

---

## ⚙️ Configuration Reference

Settings are stored in `~/.config/zoink/config.json`:

| Key | Default | Options / Description |
|---|---|---|
| `download_dir` | `~/storage/shared/Music` (Termux) or `~/Music` | Target directory for completed audio files. |
| `output_format` | `mp3` | `mp3`, `m4a`, `flac`, `ogg`, `opus`. |
| `quality` | `best` | `best`, `320k`, `256k`, `192k`, `128k`, `lossless`. |
| `embed_metadata` | `true` | Embed standard metadata (title, artist, album, track number, etc.). |
| `embed_artwork` | `true` | Fetch and embed high-resolution album cover art. |
| `embed_lyrics` | `true` | Fetch and embed synchronized/plain lyrics. |
| `filename_template` | `{artist}/{album}/{track} - {title}.{ext}` | Custom naming scheme for output files. |
| `duplicate_handling` | `skip` | `skip`, `overwrite`, or `rename`. |
| `theme` | `auto` | `auto`, `dark`, `amoled`, `light`. |

---

## 🏗️ Architecture

```mermaid
flowchart TD
    User([User]) -->|Interactive| TUI[Terminal UI (prompt_toolkit)]
    User -->|CLI Command| CLI[CLI Dispatcher (zoink)]
    User -->|Web Browser| Web[Flask Web Player & API]

    TUI --> App[Application State & Engine]
    CLI --> App
    Web --> App

    App --> DM[DownloadManager]
    App --> Lib[(SQLite Library / WAL)]

    DM --> Provider[Provider Abstraction (YouTube)]
    DM --> YTDL[yt-dlp Core]
    YTDL --> FFmpeg[FFmpeg Transcoding & Extraction]
    FFmpeg --> Verify[Container Integrity Verification]
    Verify --> Meta[Metadata / Mutagen Engine]
    Meta --> Art[Artwork Pipeline (Cache + iTunes)]
    Meta --> Lyr[Lyrics Pipeline (Cache + LRCLIB)]
    Meta --> Atomic[Atomic Staging & Finalization]
    Atomic --> Lib
```

---

## 🧪 Testing

Run the test suite with `pytest`:

```bash
# Run all tests
pytest

# Run regression tests specifically
pytest tests/test_regressions.py -v
```

---

## ⚖️ Legal & Privacy Boundaries

ZoinK is an open-source tool intended for downloading public audio streams, creative commons content, and personal media backup. It does not include authentication bypasses, DRM circumvention mechanisms, or reverse-engineered proprietary decryption keys. Please respect copyright laws and the intellectual property rights of artists and content owners.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
