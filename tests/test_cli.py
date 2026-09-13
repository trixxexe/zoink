"""Tests for CLI subcommands, argument parsing, and handlers."""

import pytest
from zoink import __version__
from zoink.cli import main, WATERMARK


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert __version__ in out
    assert WATERMARK in out


def test_cli_config_commands(capsys, tmp_path):
    # --path
    code = main(["config", "--path"])
    assert code == 0
    out = capsys.readouterr().out
    assert "config.json" in out

    # --set and --get
    code_set = main(["config", "--set", "quality", "192"])
    assert code_set == 0
    capsys.readouterr()

    code_get = main(["config", "--get", "quality"])
    assert code_get == 0
    out_get = capsys.readouterr().out
    assert "192" in out_get

    # --reset
    code_reset = main(["config", "--reset"])
    assert code_reset == 0
    out_reset = capsys.readouterr().out
    assert "reset" in out_reset


def test_cli_scan(tmp_path, capsys):
    # Scan empty directory
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    code = main(["scan", "--dir", str(music_dir)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Indexed 0" in out


def test_cli_search_argparse(monkeypatch):
    from unittest.mock import patch, MagicMock
    from zoink.provider import TrackResult

    mock_provider = MagicMock()
    mock_provider.search_tracks.return_value = [
        TrackResult(id="mock1", title="Mock Title", artist="Mock Artist", duration=120)
    ]

    with patch("zoink.providers.YouTubeProvider", return_value=mock_provider):
        with patch("zoink.cli._download_and_save", return_value=0) as mock_dl:
            code = main(["search", "Test Query", "--yes"])
            assert code == 0
            assert mock_dl.called
