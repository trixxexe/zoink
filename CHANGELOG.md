# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-09-15

### Added
- **Interactive `/config` TUI Screen**: Added a dedicated, interactive configuration editor to the terminal UI accessible via `/config`, `/cfg`, `/settings`, and `/preferences`.
- **Keyboard Navigation & Inline Editing**: Full keyboard navigation (`↑`/`↓`/`j`/`k`), instant option cycling (`↵`/`Space`/`←`/`→`), and inline text editing (`e`/`↵`) for configuration fields.
- **Customizable Web Player Greeting**: Added persistent `user_name` configuration setting (default: `"Music Lover"`), allowing users to personalize the web dashboard greeting banner (e.g., "Good evening, Alex").
- **Web Player Greeting Modal**: Interactive click-to-edit name prompt directly on the web player dashboard with instant local state update and background API synchronization.
- **`/api/config` REST Endpoints**: New `GET /api/config` and `POST /api/config` endpoints for querying and updating persistent configuration settings from the web interface.
- **Exclusive ZoinK Download Filtering**: Both the TUI library screen and the Web Player (`/api/library`) now strictly display only audio files downloaded through ZoinK, preventing external music tracks in the download directory from cluttering the library.
- **ZoinK Signature Fingerprinting**: Automated embedding and parsing of internal signature tags (`zoink_download=1`, ID3/Vorbis/MP4 comment markers) combined with SQLite tracking to identify ZoinK-managed audio files across scans and restarts.

### Fixed
- **Library Persistence Across Restarts**: Resolved an issue where downloaded tracks were omitted from the in-app library and web player after closing and restarting ZoinK.
- **Safe Library Pruning**: Updated `prune_stale()` in `zoink/library.py` to only remove database records when audio files are physically missing from disk, preserving existing ZoinK-downloaded library entries across re-scans.
- **Prompt-Toolkit Input Isolation**: Configured TUI keybindings to properly route text input during configuration editing without triggering global navigation shortcuts.

### Tests
- Expanded test suite to **101 passing tests**:
  - `test_library_persists_across_app_restarts`: Verifies database retention and file existence verification after restart.
  - `test_library_scan_does_not_ingest_external_files`: Ensures non-ZoinK audio files are excluded from the library.
  - `test_zoink_signature_tagging_roundtrip`: Verifies tag embedding and signature verification across container formats.
  - `test_tui_config_screen_interaction`: Tests `/config` opening, option cycling, value modification, and screen return.
  - `test_api_config_get_and_post`: Validates REST API configuration retrieval and updating.

---

## [0.1.0] - 2026-09-14

### Added
- **Terminal User Interface (TUI)**: Centered, distraction-free terminal interface inspired by Pablo Stanley's Yoinks TUI, built with `prompt_toolkit`.
- **Modern AMOLED Web Player**: Minimalist Spotify-style local web music player with dedicated desktop and mobile layouts, HTTP 206 partial-range audio streaming, track search, and ZIP library export.
- **Multi-Container Audio Support**: Native and converted support for MP3, M4A (AAC), FLAC, OGG, and Opus.
- **Automated Metadata & Cover Art**: Embedded high-resolution cover art from iTunes/web sources and synchronized/plain lyrics from LRCLIB with yt-dlp subtitle fallbacks.
- **Atomic Staging & Validation**: Staging in isolated temporary directories with container header verification before moving to final destinations.
- **SQLite Music Library**: Fast incremental library scanning with WAL mode, artist/album grouping, and full-text search.
- **Graceful Lifecycle Management**: Completely idempotent shutdown handling (`Ctrl+C`, `Ctrl+D`, `q`) with terminal state restoration and cooperative background task cancellation.
