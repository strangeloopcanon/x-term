"""Tests for the native host process detection logic."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add native-host to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "native-host"))

from process_gate import DEFAULT_CONFIG, Config, _block_x_now, _has_tty, _load_config


class TestHasTty:
    """Tests for TTY detection function."""

    def test_real_tty_macos(self):
        """macOS TTYs like ttys001 should be detected."""
        assert _has_tty("ttys001") is True
        assert _has_tty("ttys002") is True
        assert _has_tty("ttys123") is True

    def test_real_tty_linux(self):
        """Linux TTYs like pts/0 should be detected."""
        assert _has_tty("pts/0") is True
        assert _has_tty("pts/1") is True
        assert _has_tty("tty1") is True

    def test_no_tty_macos(self):
        """macOS uses ?? for no TTY."""
        assert _has_tty("??") is False

    def test_no_tty_linux(self):
        """Linux uses ? for no TTY."""
        assert _has_tty("?") is False

    def test_no_tty_with_question_mark(self):
        """Any string containing ? should be considered no TTY."""
        assert _has_tty("?something") is False
        assert _has_tty("something?") is False


class TestWatchRegex:
    """Tests for the default watch regex pattern."""

    @pytest.fixture
    def pattern(self):
        return re.compile(DEFAULT_CONFIG.watch_regex)

    @pytest.mark.parametrize("cmd,should_match", [
        # Should match - basic cases
        ("codex", True),
        ("Codex", True),
        ("CODEX", True),
        ("claude", True),
        ("Claude", True),
        ("CLAUDE", True),
        # Should match - with code suffix
        ("claude-code", True),
        ("claude_code", True),
        ("Claude-Code", True),
        ("Claude_Code", True),
        # Should match - in command paths
        ("/usr/bin/codex", True),
        ("node /path/to/codex", True),
        ("python claude-code --arg", True),
        ("/Users/me/.nvm/versions/node/v20/bin/codex resume", True),
        # Should NOT match - partial words
        ("xcodex", False),
        ("codextra", False),
        ("claudette", False),
        # Should NOT match - unrelated
        ("vim", False),
        ("python script.py", False),
        ("chrome --no-sandbox", False),
    ])
    def test_regex_matching(self, pattern, cmd, should_match):
        """Verify regex matches expected commands."""
        result = bool(pattern.search(cmd))
        assert result == should_match, f"Expected {cmd!r} to {'match' if should_match else 'not match'}"


class TestBlockXNow:
    """Tests for process detection with mocked subprocess."""

    @pytest.fixture
    def config(self):
        return DEFAULT_CONFIG

    @pytest.fixture
    def config_no_tty(self):
        return Config(
            watch_regex=DEFAULT_CONFIG.watch_regex,
            require_tty=False,
            poll_interval_seconds=1.0,
            heartbeat_seconds=15.0,
        )

    def test_detects_codex_with_tty(self, config):
        """Should detect codex process with TTY."""
        mock_ps_output = """\
  1234 ttys001 /bin/zsh
  5678 ttys002 node /path/to/codex resume abc123
  9999 ??      /usr/bin/some_daemon
"""
        with (
            patch("subprocess.check_output", return_value=mock_ps_output),
            patch("platform.system", return_value="Darwin"),
        ):
            assert _block_x_now(config) is True

    def test_ignores_codex_without_tty_when_required(self, config):
        """Should ignore codex if it has no TTY and require_tty=True."""
        mock_ps_output = """\
  1234 ttys001 /bin/zsh
  5678 ??      node /path/to/codex resume abc123
"""
        with (
            patch("subprocess.check_output", return_value=mock_ps_output),
            patch("platform.system", return_value="Darwin"),
        ):
            assert _block_x_now(config) is False

    def test_detects_codex_without_tty_when_not_required(self, config_no_tty):
        """Should detect codex without TTY when require_tty=False."""
        mock_ps_output = """\
  1234 ttys001 /bin/zsh
  5678 ??      node /path/to/codex resume abc123
"""
        with (
            patch("subprocess.check_output", return_value=mock_ps_output),
            patch("platform.system", return_value="Darwin"),
        ):
            assert _block_x_now(config_no_tty) is True

    def test_detects_claude(self, config):
        """Should detect claude process."""
        mock_ps_output = """\
  1234 ttys001 claude --model opus
"""
        with (
            patch("subprocess.check_output", return_value=mock_ps_output),
            patch("platform.system", return_value="Darwin"),
        ):
            assert _block_x_now(config) is True

    def test_detects_claude_code(self, config):
        """Should detect claude-code process."""
        mock_ps_output = """\
  1234 ttys001 /usr/local/bin/claude-code
"""
        with (
            patch("subprocess.check_output", return_value=mock_ps_output),
            patch("platform.system", return_value="Darwin"),
        ):
            assert _block_x_now(config) is True

    def test_no_matching_process(self, config):
        """Should return False when no matching process."""
        mock_ps_output = """\
  1234 ttys001 /bin/zsh
  5678 ttys002 vim file.py
  9999 ttys003 python script.py
"""
        with (
            patch("subprocess.check_output", return_value=mock_ps_output),
            patch("platform.system", return_value="Darwin"),
        ):
            assert _block_x_now(config) is False

    def test_empty_output(self, config):
        """Should return False for empty ps output."""
        with (
            patch("subprocess.check_output", return_value=""),
            patch("platform.system", return_value="Darwin"),
        ):
            assert _block_x_now(config) is False


class TestLoadConfig:
    """Tests for configuration loading."""

    def test_loads_defaults_when_file_missing(self, tmp_path, monkeypatch):
        """Should use defaults when config file doesn't exist."""
        monkeypatch.setenv("XTERM_PROCESS_GATE_CONFIG", str(tmp_path / "nonexistent.json"))
        config = _load_config()
        assert config.watch_regex == DEFAULT_CONFIG.watch_regex
        assert config.require_tty == DEFAULT_CONFIG.require_tty

    def test_loads_custom_config(self, tmp_path, monkeypatch):
        """Should load values from config file."""
        config_file = tmp_path / "config.json"
        config_file.write_text('{"require_tty": false, "poll_interval_seconds": 2.0}')
        monkeypatch.setenv("XTERM_PROCESS_GATE_CONFIG", str(config_file))

        config = _load_config()
        assert config.require_tty is False
        assert config.poll_interval_seconds == 2.0
        # Defaults should still apply for unspecified values
        assert config.watch_regex == DEFAULT_CONFIG.watch_regex

    def test_handles_invalid_json(self, tmp_path, monkeypatch):
        """Should use defaults when config file has invalid JSON."""
        config_file = tmp_path / "config.json"
        config_file.write_text("not valid json {{{")
        monkeypatch.setenv("XTERM_PROCESS_GATE_CONFIG", str(config_file))

        config = _load_config()
        assert config == DEFAULT_CONFIG
