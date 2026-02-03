#!/usr/bin/env python3
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


@dataclass(frozen=True)
class Config:
    watch_regex: str
    require_tty: bool
    poll_interval_seconds: float
    heartbeat_seconds: float


DEFAULT_CONFIG = Config(
    watch_regex=r"(?i)\b(codex|claude(?:-code)?|claude_code)\b",
    require_tty=True,
    poll_interval_seconds=1.0,
    heartbeat_seconds=15.0,
)


def _load_config() -> Config:
    config_path = os.environ.get("XTERM_PROCESS_GATE_CONFIG")
    if config_path:
        path = Path(config_path)
    else:
        path = Path(__file__).with_name("process_gate.config.json")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULT_CONFIG
    except Exception:
        return DEFAULT_CONFIG

    def _get(key: str, default: Any) -> Any:
        val = data.get(key, default)
        return default if val is None else val

    return Config(
        watch_regex=str(_get("watch_regex", DEFAULT_CONFIG.watch_regex)),
        require_tty=bool(_get("require_tty", DEFAULT_CONFIG.require_tty)),
        poll_interval_seconds=float(
            _get("poll_interval_seconds", DEFAULT_CONFIG.poll_interval_seconds)
        ),
        heartbeat_seconds=float(_get("heartbeat_seconds", DEFAULT_CONFIG.heartbeat_seconds)),
    )


def _native_read_message() -> dict[str, Any] | None:
    raw_len = sys.stdin.buffer.read(4)
    if not raw_len:
        return None
    (msg_len,) = struct.unpack("<I", raw_len)
    data = sys.stdin.buffer.read(msg_len)
    if not data:
        return None
    try:
        return json.loads(data.decode("utf-8", errors="replace"))
    except Exception:
        return None


def _native_send_message(obj: dict[str, Any]) -> None:
    data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _has_tty(tty: str) -> bool:
    # macOS typically uses '??' and Linux uses '?' for "no tty"
    return tty not in {"?", "??"} and "?" not in tty


def _block_x_now(config: Config) -> bool:
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


def _stdin_reader(queue: Queue[dict[str, Any] | None], stop: threading.Event) -> None:
    while not stop.is_set():
        msg = _native_read_message()
        if msg is None:
            queue.put(None)
            stop.set()
            return
        queue.put(msg)


def run_watch_stdio(config: Config) -> None:
    stop = threading.Event()
    inbox: Queue[dict[str, Any] | None] = Queue()

    t = threading.Thread(target=_stdin_reader, args=(inbox, stop), daemon=True)
    t.start()

    last_block: bool | None = None
    last_sent_at = 0.0

    while not stop.is_set():
        now = time.time()
        block_x = _block_x_now(config)

        should_send = (
            last_block is None
            or block_x != last_block
            or (now - last_sent_at) >= config.heartbeat_seconds
        )
        if should_send:
            payload = {
                "type": "status",
                "block_x": bool(block_x),
                "timestamp_unix": now,
            }
            try:
                _native_send_message(payload)
            except BrokenPipeError:
                return
            last_sent_at = now
            last_block = block_x

        # Drain inbox to react quickly to poll requests / detect EOF.
        try:
            while True:
                msg = inbox.get_nowait()
                if msg is None:
                    return
                if isinstance(msg, dict) and msg.get("type") == "poll":
                    reply_to = msg.get("id")
                    payload = {
                        "type": "status",
                        "block_x": bool(block_x),
                        "timestamp_unix": now,
                        "reply_to": reply_to,
                    }
                    try:
                        _native_send_message(payload)
                    except BrokenPipeError:
                        return
        except Empty:
            pass

        time.sleep(max(0.05, config.poll_interval_seconds))


def main(argv: list[str]) -> int:
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
    args = parser.parse_args(argv)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

