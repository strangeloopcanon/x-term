"""Tests for the process detection logic."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from unittest.mock import patch

import pytest

from xgate.config import DEFAULT_CONFIG, ensure_config, load_config
from xgate.process_gate import ProcessGate, ProcessInfo, _has_tty, _process_active


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
        return re.compile(DEFAULT_CONFIG.process.watch_regex)

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
        return replace(DEFAULT_CONFIG.process, enable_nettop=False)

    @pytest.fixture
    def config_no_tty(self):
        return replace(DEFAULT_CONFIG.process, require_tty=False, enable_nettop=False)

    def test_detects_codex_with_tty(self, config):
        """Should detect codex process with TTY."""
        mock_ps_output = """\
  1234 1 ttys001 0.0 /bin/zsh
  5678 1 ttys002 0.1 node /path/to/codex resume abc123
  9999 1 ??      0.0 /usr/bin/some_daemon
"""
        with (
            patch("subprocess.check_output", return_value=mock_ps_output),
            patch("platform.system", return_value="Darwin"),
        ):
            gate = ProcessGate(config)
            running, _active, _debug = gate.poll()
            assert running is True

    def test_ignores_codex_without_tty_when_required(self, config):
        """Should ignore codex if it has no TTY and require_tty=True."""
        mock_ps_output = """\
  1234 1 ttys001 0.0 /bin/zsh
  5678 1 ??      0.0 node /path/to/codex resume abc123
"""
        with (
            patch("subprocess.check_output", return_value=mock_ps_output),
            patch("platform.system", return_value="Darwin"),
        ):
            gate = ProcessGate(config)
            running, _active, _debug = gate.poll()
            assert running is False

    def test_detects_codex_without_tty_when_not_required(self, config_no_tty):
        """Should detect codex without TTY when require_tty=False."""
        mock_ps_output = """\
  1234 1 ttys001 0.0 /bin/zsh
  5678 1 ??      0.0 node /path/to/codex resume abc123
"""
        with (
            patch("subprocess.check_output", return_value=mock_ps_output),
            patch("platform.system", return_value="Darwin"),
        ):
            gate = ProcessGate(config_no_tty)
            running, _active, _debug = gate.poll()
            assert running is True

    def test_detects_claude(self, config):
        """Should detect claude process."""
        mock_ps_output = """\
  1234 1 ttys001 0.0 claude --model opus
"""
        with (
            patch("subprocess.check_output", return_value=mock_ps_output),
            patch("platform.system", return_value="Darwin"),
        ):
            gate = ProcessGate(config)
            running, _active, _debug = gate.poll()
            assert running is True

    def test_detects_claude_code(self, config):
        """Should detect claude-code process."""
        mock_ps_output = """\
  1234 1 ttys001 0.0 /usr/local/bin/claude-code
"""
        with (
            patch("subprocess.check_output", return_value=mock_ps_output),
            patch("platform.system", return_value="Darwin"),
        ):
            gate = ProcessGate(config)
            running, _active, _debug = gate.poll()
            assert running is True

    def test_no_matching_process(self, config):
        """Should return False when no matching process."""
        mock_ps_output = """\
  1234 1 ttys001 0.0 /bin/zsh
  5678 1 ttys002 0.0 vim file.py
  9999 1 ttys003 0.0 python script.py
"""
        with (
            patch("subprocess.check_output", return_value=mock_ps_output),
            patch("platform.system", return_value="Darwin"),
        ):
            gate = ProcessGate(config)
            running, _active, _debug = gate.poll()
            assert running is False

    def test_empty_output(self, config):
        """Should return False for empty ps output."""
        with (
            patch("subprocess.check_output", return_value=""),
            patch("platform.system", return_value="Darwin"),
        ):
            gate = ProcessGate(config)
            running, _active, _debug = gate.poll()
            assert running is False


class TestLoadConfig:
    """Tests for configuration loading."""

    def test_loads_defaults_when_file_missing(self, tmp_path, monkeypatch):
        """Should use defaults when config file doesn't exist."""
        config_file = tmp_path / "config.json"
        config = ensure_config(config_file)
        assert config.process.watch_regex == DEFAULT_CONFIG.process.watch_regex
        assert config.process.require_tty == DEFAULT_CONFIG.process.require_tty

    def test_loads_custom_config(self, tmp_path):
        """Should load values from config file."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            '{"process": {"require_tty": false}, "poll_interval_seconds": 2.0}',
            encoding="utf-8",
        )

        config = load_config(config_file)
        assert config.process.require_tty is False
        assert config.poll_interval_seconds == 2.0
        assert config.process.watch_regex == DEFAULT_CONFIG.process.watch_regex

    def test_handles_invalid_json(self, tmp_path):
        """Should use defaults when config file has invalid JSON."""
        config_file = tmp_path / "config.json"
        config_file.write_text("not valid json {{{")
        with pytest.raises(json.JSONDecodeError):
            load_config(config_file)


class TestProcessActive:
    """Tests for the "active work" heuristic."""

    def test_cpu_activity_marks_active(self):
        config = replace(
            DEFAULT_CONFIG.process,
            enable_nettop=False,
            consider_children_active=False,
            cpu_active_threshold_percent=1.0,
        )
        proc = ProcessInfo(
            pid="100",
            ppid="1",
            tty="ttys001",
            cpu_percent=5.0,
            cmd="codex",
        )

        active, last_active_at, debug = _process_active(
            config,
            now=123.0,
            matches=[proc],
            children_map={},
            prev_net_totals={},
            last_active_at=0.0,
        )

        assert active is True
        assert last_active_at == 123.0
        assert "cpu" in debug["evidence"]

    def test_child_cpu_marks_active(self):
        config = replace(
            DEFAULT_CONFIG.process,
            enable_nettop=False,
            consider_children_active=True,
            cpu_active_threshold_percent=1.0,
        )
        proc = ProcessInfo(
            pid="100",
            ppid="1",
            tty="ttys001",
            cpu_percent=0.0,
            cmd="codex",
        )
        child = ProcessInfo(
            pid="101",
            ppid="100",
            tty="ttys001",
            cpu_percent=5.0,
            cmd="pytest -q",
        )

        active, last_active_at, debug = _process_active(
            config,
            now=10.0,
            matches=[proc],
            children_map={"100": [child]},
            prev_net_totals={},
            last_active_at=0.0,
        )

        assert active is True
        assert last_active_at == 10.0
        assert "child_cpu" in debug["evidence"]

    def test_grace_window_prevents_flapping(self):
        config = replace(
            DEFAULT_CONFIG.process,
            enable_nettop=False,
            consider_children_active=False,
            cpu_active_threshold_percent=999.0,
            active_grace_seconds=4.0,
        )
        proc = ProcessInfo(
            pid="100",
            ppid="1",
            tty="ttys001",
            cpu_percent=0.0,
            cmd="codex",
        )

        active, last_active_at, debug = _process_active(
            config,
            now=10.0,
            matches=[proc],
            children_map={},
            prev_net_totals={},
            last_active_at=8.0,
        )

        assert active is True
        assert last_active_at == 8.0
        assert "grace" in debug["evidence"]
