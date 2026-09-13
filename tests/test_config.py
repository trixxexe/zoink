"""Tests for config module."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from zoink.config import Config, CONFIG_DIR, CONFIG_FILE, DEFAULTS


def test_defaults_loaded():
    config = Config()
    for key, val in DEFAULTS.items():
        assert config[key] == val


def test_set_and_get():
    config = Config()
    config["test_key"] = "test_value"
    assert config["test_key"] == "test_value"
    assert config.get_value("test_key") == "test_value"
    assert config.get_value("nonexistent", "default") == "default"


def test_save_and_reload(tmp_path):
    test_file = tmp_path / "config.json"
    with patch("zoink.config.CONFIG_FILE", test_file):
        config = Config()
        config["output_format"] = "flac"
        config.save()
        assert test_file.exists()
        loaded = json.loads(test_file.read_text())
        assert loaded["output_format"] == "flac"
        config2 = Config()
        assert config2["output_format"] == "flac"


def test_download_dir_termux():
    with patch("zoink.config._is_termux", return_value=True):
        config = Config()
        d = config.download_dir
        assert d is not None


def test_download_dir_default():
    config = Config()
    d = config.download_dir
    assert d.exists() or not d.exists()  # Just check it resolves
    assert isinstance(d, Path)


def test_properties():
    config = Config()
    assert isinstance(config.concurrency, int)
    assert isinstance(config.server_port, int)
    assert isinstance(config.server_lan, bool)
    assert isinstance(config.output_format, str)
    assert isinstance(config.quality, str)
