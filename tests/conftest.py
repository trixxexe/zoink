"""Pytest fixtures and configuration isolation for ZoinK tests."""

import os
import sys
import pytest
from pathlib import Path
from zoink.config import Config


@pytest.fixture(autouse=True)
def isolate_test_config(tmp_path, monkeypatch):
    """Ensure all tests run with an isolated, temporary config environment.

    This prevents tests from ever reading from or writing to ~/.config/zoink/config.json
    or touching the user's host music directory.
    """
    test_config_dir = tmp_path / "test_zoink_config"
    test_config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ZOINK_CONFIG_DIR", str(test_config_dir))

    test_download_dir = tmp_path / "test_zoink_music"
    test_download_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ZOINK_DOWNLOAD_DIR", str(test_download_dir))

    # Ensure venv Scripts/bin directory is in PATH for ffmpeg
    venv_bin = Path(sys.executable).parent
    curr_path = os.environ.get("PATH", "")
    if str(venv_bin) not in curr_path:
        monkeypatch.setenv("PATH", f"{venv_bin}{os.pathsep}{curr_path}")

    Config._instance = None
    yield
    Config._instance = None
