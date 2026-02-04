from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PS_BIN = "/bin/ps" if Path("/bin/ps").exists() else "ps"
OPEN_BIN = "/usr/bin/open" if Path("/usr/bin/open").exists() else "open"

_CHROME_RE = re.compile(r"google chrome", re.IGNORECASE)
_NETWORK_RE = re.compile(r"network\.mojom\.networkservice", re.IGNORECASE)


@dataclass(frozen=True)
class ProcessRow:
    pid: int
    command: str


def restart_chrome(*, app_name: str = "Google Chrome") -> None:
    if sys.platform != "darwin":
        raise RuntimeError("Chrome restart is only supported on macOS")
    subprocess.run([OPEN_BIN, "-a", app_name, "chrome://restart"], check=False)


def _list_process_rows() -> list[ProcessRow]:
    out = subprocess.check_output(
        [PS_BIN, "-axo", "pid=,command="],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    rows: list[ProcessRow] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid_s, cmd = parts
        try:
            pid = int(pid_s)
        except Exception:
            continue
        rows.append(ProcessRow(pid=pid, command=cmd))
    return rows


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except Exception:
        return False
    return True


def _kill(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except Exception:
        return


def _is_chrome_network_service(cmd: str) -> bool:
    if not _CHROME_RE.search(cmd):
        return False
    if "--type=utility" not in cmd and "--type=network" not in cmd:
        return False
    return _NETWORK_RE.search(cmd) is not None


def reset_chrome_network_service(*, timeout_seconds: float = 1.5) -> int:
    """Terminate Chrome's Network Service utility processes so it rebuilds DNS/socket pools."""
    if sys.platform != "darwin":
        raise RuntimeError("Chrome network reset is only supported on macOS")

    rows = _list_process_rows()
    pids = [row.pid for row in rows if _is_chrome_network_service(row.command)]
    if not pids:
        return 0

    for pid in pids:
        _kill(pid, signal.SIGTERM)

    deadline = time.time() + max(0.2, timeout_seconds)
    alive: set[int] = set(pids)
    while time.time() < deadline:
        alive = {pid for pid in alive if _pid_alive(pid)}
        if not alive:
            return len(pids)
        time.sleep(0.1)

    for pid in alive:
        _kill(pid, signal.SIGKILL)
    return len(pids)
