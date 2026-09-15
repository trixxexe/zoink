"""Configuration system with sensible defaults."""

import json
import os
import platform
from pathlib import Path
from typing import Any

APP_NAME = "zoink"

def _is_termux() -> bool:
    return (
        bool(os.environ.get("PREFIX"))
        and "com.termux" in str(Path(os.environ.get("PREFIX", "")).parts)
    ) or os.path.exists("/data/data/com.termux/files/usr/bin")


def _default_output_dir() -> Path:
    home = Path.home()
    if _is_termux():
        candidate = home / "storage" / "shared" / "Music"
        if candidate.exists():
            return candidate
        shared = home / "storage" / "shared"
        if shared.exists():
            return shared / "Music" if (shared / "Music").exists() else shared
        return home / "Music"
    if platform.system() == "Windows":
        return home / "Downloads" / "Music"
    if platform.system() == "Darwin":
        return home / "Downloads" / "Music"

    # Standard Linux / POSIX: check XDG Music Directory first
    xdg_music = os.environ.get("XDG_MUSIC_DIR", "").strip()
    if xdg_music:
        p = Path(xdg_music).expanduser()
        if p.exists():
            return p

    # Standard ~/Music folder (e.g. /root/Music or /home/<user>/Music)
    music_dir = home / "Music"
    if music_dir.exists():
        return music_dir

    xdg = os.environ.get("XDG_DOWNLOAD_DIR", "").strip()
    if xdg:
        p = Path(xdg).expanduser()
        if p.exists():
            return p / "Music"
    return home / "Music"


CONFIG_DIR = Path(
    os.environ.get("ZOINK_CONFIG_DIR")
    or (Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME)
)
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    "download_dir": "",
    "output_format": "mp3",
    "quality": "best",
    "concurrency": 3,
    "filename_template": "{artist}/{album}/{track} - {title}.{ext}",
    "embed_artwork": True,
    "embed_lyrics": True,
    "embed_metadata": True,
    "overwrite": False,
    "duplicate_handling": "skip",
    "server_port": 8080,
    "server_host": "127.0.0.1",
    "server_lan": False,
    "theme": "default",
    "log_level": "normal",
    "user_name": "Music Lover",
}


class Config:
    """Singleton-ish config backed by a JSON file."""

    _instance: "Config | None" = None
    _data: dict[str, Any]

    def __init__(self):
        self._data = dict(DEFAULTS)
        self._load()

    @classmethod
    def get(cls) -> "Config":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        if CONFIG_FILE.exists():
            try:
                with CONFIG_FILE.open("r", encoding="utf-8") as f:
                    stored = json.load(f)
                self._data.update(stored)
            except (json.JSONDecodeError, OSError):
                pass

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get_value(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def get_key(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set_key(self, key: str, value: Any) -> None:
        # Cast booleans and ints appropriately if key is in DEFAULTS
        if key in DEFAULTS:
            default_val = DEFAULTS[key]
            if isinstance(default_val, bool):
                if isinstance(value, str):
                    value = value.lower() in ("true", "1", "yes", "on")
                else:
                    value = bool(value)
            elif isinstance(default_val, int):
                value = int(value)
        self._data[key] = value
        self.save()

    def reset(self) -> None:
        self._data = dict(DEFAULTS)
        self.save()

    @property
    def download_dir(self) -> Path:
        d = self._data["download_dir"]
        if d:
            return Path(d).expanduser().resolve()
        return _default_output_dir()

    @property
    def output_format(self) -> str:
        return self._data["output_format"]

    @property
    def quality(self) -> str:
        return self._data["quality"]

    @property
    def concurrency(self) -> int:
        return int(self._data["concurrency"])

    @property
    def filename_template(self) -> str:
        return self._data["filename_template"]

    @property
    def server_port(self) -> int:
        return int(self._data["server_port"])

    @property
    def server_host(self) -> str:
        return self._data["server_host"]

    @property
    def server_lan(self) -> bool:
        return bool(self._data["server_lan"])

    @property
    def log_level(self) -> str:
        return self._data["log_level"]

    @property
    def embed_artwork(self) -> bool:
        return bool(self._data.get("embed_artwork", True))

    @property
    def embed_lyrics(self) -> bool:
        return bool(self._data.get("embed_lyrics", True))

    @property
    def embed_metadata(self) -> bool:
        return bool(self._data.get("embed_metadata", True))

    @property
    def overwrite(self) -> bool:
        return bool(self._data.get("overwrite", False))

    @property
    def duplicate_handling(self) -> str:
        return str(self._data.get("duplicate_handling", "skip"))

    @property
    def user_name(self) -> str:
        return str(self._data.get("user_name", "Music Lover"))

