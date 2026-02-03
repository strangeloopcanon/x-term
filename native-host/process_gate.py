#!/usr/bin/env python3
"""Native messaging host for x-term: blocks X/Twitter while Codex/Claude runs."""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Any

HOST_NAME = "com.xterm.processgate"
LOG_FILE: Path | None = None


def _log(level: str, message: str, **fields: Any) -> None:
    """Write structured JSONL log entry to stderr (doesn't interfere with native messaging)."""
    if LOG_FILE is None:
        return
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "level": level,
        "logger": "process_gate",
        "message": message,
        **fields,
    }
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Best-effort logging; don't crash on log failures


@dataclass(frozen=True)
class Config:
    watch_regex: str
    require_tty: bool
    poll_interval_seconds: float
    heartbeat_seconds: float
    invert: bool  # If True: block when NOT running (allow X while working)


DEFAULT_CONFIG = Config(
    watch_regex=r"(?i)\b(codex|claude(?:-code)?|claude_code)\b",
    require_tty=True,
    poll_interval_seconds=1.0,
    heartbeat_seconds=15.0,
    invert=False,  # Default: block when running (original behavior)
)


def _load_config() -> Config:
    """Load configuration from JSON file or environment variable."""
    config_path = os.environ.get("XTERM_PROCESS_GATE_CONFIG")
    if config_path:
        path = Path(config_path)
    else:
        path = Path(__file__).with_name("process_gate.config.json")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _log("info", "config_loaded", path=str(path))
    except FileNotFoundError:
        _log("info", "config_not_found_using_defaults", path=str(path))
        return DEFAULT_CONFIG
    except Exception as e:
        _log("warning", "config_parse_error_using_defaults", path=str(path), error=str(e))
        return DEFAULT_CONFIG

    def _get(key: str, default: Any) -> Any:
        val = data.get(key, default)
        return default if val is None else val

    config = Config(
        watch_regex=str(_get("watch_regex", DEFAULT_CONFIG.watch_regex)),
        require_tty=bool(_get("require_tty", DEFAULT_CONFIG.require_tty)),
        poll_interval_seconds=float(
            _get("poll_interval_seconds", DEFAULT_CONFIG.poll_interval_seconds)
        ),
        heartbeat_seconds=float(_get("heartbeat_seconds", DEFAULT_CONFIG.heartbeat_seconds)),
        invert=bool(_get("invert", DEFAULT_CONFIG.invert)),
    )

    # Validate config values
    if config.poll_interval_seconds <= 0:
        _log("warning", "invalid_poll_interval", value=config.poll_interval_seconds)
    if config.heartbeat_seconds <= 0:
        _log("warning", "invalid_heartbeat_seconds", value=config.heartbeat_seconds)

    return config


def _native_read_message() -> dict[str, Any] | None:
    """Read a length-prefixed JSON message from stdin (Chrome native messaging protocol)."""
    raw_len = sys.stdin.buffer.read(4)
    if not raw_len:
        _log("debug", "stdin_eof")
        return None
    (msg_len,) = struct.unpack("<I", raw_len)
    data = sys.stdin.buffer.read(msg_len)
    if not data:
        _log("warning", "stdin_incomplete_message", expected_len=msg_len)
        return None
    try:
        msg = json.loads(data.decode("utf-8", errors="replace"))
        _log("debug", "message_received", msg_type=msg.get("type") if isinstance(msg, dict) else None)
        return msg
    except Exception as e:
        _log("warning", "message_parse_error", error=str(e), data_len=len(data))
        return None


def _native_send_message(obj: dict[str, Any]) -> None:
    data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _has_tty(tty: str) -> bool:
    """Check if TTY string indicates a real terminal (not '?' or '??')."""
    return tty not in {"?", "??"} and "?" not in tty


def _process_running(config: Config) -> bool:
    """Check if any Codex/Claude process is running (optionally with TTY)."""
    sysname = platform.system()
    watch = re.compile(config.watch_regex)

    if sysname in {"Darwin", "Linux"}:
        # pid, tty, command
        out = subprocess.check_output(
            ["ps", "-axo", "pid=,tty=,command="],
            text=True,
            stderr=subprocess.DEVNULL,
        )

        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue
            _pid, tty, cmd = parts
            if config.require_tty and not _has_tty(tty):
                continue
            if watch.search(cmd):
                return True
        return False

    if sysname == "Windows":
        # Best-effort: checking "terminal-attached" is non-trivial on Windows.
        # Here we only check if the process exists.
        ps_cmd = (
            "Get-CimInstance Win32_Process | "
            "Select-Object -ExpandProperty CommandLine"
        )
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                text=True,
                stderr=subprocess.DEVNULL,
                errors="ignore",
            )
        except Exception:
            return False
        return any(watch.search(line or "") for line in out.splitlines())

    return False


def _block_x_now(config: Config) -> bool:
    """Determine if X should be blocked based on process state and invert setting.

    - invert=False (default): block when Codex/Claude IS running
    - invert=True: block when Codex/Claude is NOT running (allow X while working)
    """
    running = _process_running(config)
    if config.invert:
        return not running  # Block when NOT running
    return running  # Block when running


def _stdin_reader(queue: Queue[dict[str, Any] | None], stop: threading.Event) -> None:
    while not stop.is_set():
        msg = _native_read_message()
        if msg is None:
            queue.put(None)
            stop.set()
            return
        queue.put(msg)


def run_watch_stdio(config: Config) -> None:
    """Main loop: poll processes and send status updates over native messaging."""
    _log("info", "watch_stdio_started", config=config.__dict__)

    stop = threading.Event()
    inbox: Queue[dict[str, Any] | None] = Queue()

    t = threading.Thread(target=_stdin_reader, args=(inbox, stop), daemon=True)
    t.start()

    last_block: bool | None = None
    last_sent_at = 0.0

    while not stop.is_set():
        now = time.time()
        running = _process_running(config)
        block_x = _block_x_now(config)

        should_send = (
            last_block is None
            or block_x != last_block
            or (now - last_sent_at) >= config.heartbeat_seconds
        )
        if should_send:
            if last_block is not None and block_x != last_block:
                _log("info", "block_state_changed", block_x=block_x, previous=last_block)
            payload = {
                "type": "status",
                "block_x": bool(block_x),
                "process_running": bool(running),  # Raw state for extension to use
                "timestamp_unix": now,
            }
            try:
                _native_send_message(payload)
            except BrokenPipeError:
                _log("info", "stdout_broken_pipe_exiting")
                return
            last_sent_at = now
            last_block = block_x

        # Drain inbox to react quickly to poll requests / detect EOF.
        try:
            while True:
                msg = inbox.get_nowait()
                if msg is None:
                    _log("info", "stdin_closed_exiting")
                    return
                if isinstance(msg, dict) and msg.get("type") == "poll":
                    reply_to = msg.get("id")
                    # Use fresh timestamp and state for poll replies
                    poll_now = time.time()
                    poll_running = _process_running(config)
                    poll_block = _block_x_now(config)
                    payload = {
                        "type": "status",
                        "block_x": bool(poll_block),
                        "process_running": bool(poll_running),
                        "timestamp_unix": poll_now,
                        "reply_to": reply_to,
                    }
                    try:
                        _native_send_message(payload)
                    except BrokenPipeError:
                        _log("info", "stdout_broken_pipe_exiting")
                        return
        except Empty:
            pass

        time.sleep(max(0.05, config.poll_interval_seconds))


def _init_logging() -> None:
    """Initialize logging to a file in a platform-appropriate cache directory."""
    global LOG_FILE
    log_path = os.environ.get("XTERM_PROCESS_GATE_LOG")
    if log_path:
        LOG_FILE = Path(log_path)
    else:
        # Default: log to cache directory
        sysname = platform.system()
        if sysname == "Darwin":
            cache_dir = Path.home() / "Library" / "Logs" / "x-term"
        elif sysname == "Linux":
            cache_dir = Path.home() / ".cache" / "x-term"
        else:
            cache_dir = Path.home() / ".x-term" / "logs"
        cache_dir.mkdir(parents=True, exist_ok=True)
        LOG_FILE = cache_dir / "process_gate.log"


def main(argv: list[str]) -> int:
    """Entry point for the native messaging host."""
    _init_logging()
    _log("info", "process_gate_started", pid=os.getpid(), argv=argv)

    config = _load_config()

    parser = argparse.ArgumentParser(
        prog="process_gate.py",
        description="Native messaging host for x-term (blocks X while Codex/Claude run).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Print current block status as JSON and exit.",
    )
    parser.add_argument(
        "--watch-stdio",
        action="store_true",
        help="Run as a Chrome native messaging host over stdin/stdout.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Override log file path (default: ~/Library/Logs/x-term/ on macOS).",
    )
    # Chrome passes the extension origin as a positional argument - accept and ignore it
    parser.add_argument(
        "chrome_origin",
        nargs="?",
        default=None,
        help=argparse.SUPPRESS,  # Hidden; Chrome passes chrome-extension://... here
    )
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        _log("info", "ignored_unknown_args", unknown=unknown)

    # Override log file if specified
    if args.log_file:
        global LOG_FILE
        LOG_FILE = Path(args.log_file)
        _log("info", "log_file_overridden", path=str(LOG_FILE))

    if args.check:
        print(
            json.dumps(
                {
                    "block_x": bool(_block_x_now(config)),
                    "host_name": HOST_NAME,
                    "config": config.__dict__,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    # Default mode is watch-stdio (Chrome will not pass args).
    run_watch_stdio(config)
    _log("info", "process_gate_exiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
