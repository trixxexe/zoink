"""Pytest fixtures and configuration isolation for ZoinK tests."""

import os
import pytest
from pathlib import Path
from zoink.config import Config


@pytest.fixture(autouse=True)
def isolate_test_config(tmp_path, monkeypatch):
    """Ensure all tests run with an isolated, temporary config environment.

    This prevents tests from ever reading from or writing to ~/.config/zoink/config.json.
    """
    test_config_dir = tmp_path / "test_zoink_config"
    test_config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ZOINK_CONFIG_DIR", str(test_config_dir))
    Config._instance = None
    yield
    Config._instance = None
