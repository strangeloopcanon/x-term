from __future__ import annotations

import json
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ProcessConfig

LOG_FILE: Path | None = None

PS_BIN = "/bin/ps" if Path("/bin/ps").exists() else "ps"
NETTOP_BIN = "/usr/bin/nettop" if Path("/usr/bin/nettop").exists() else "nettop"


def set_log_file(path: Path | None) -> None:
    global LOG_FILE
    LOG_FILE = path


def _log(level: str, message: str, **fields: Any) -> None:
    """Write structured JSONL log entry to the configured log file."""
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
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


@dataclass(frozen=True)
class ProcessInfo:
    pid: str
    ppid: str
    tty: str
    cpu_percent: float
    cmd: str


def _has_tty(tty: str) -> bool:
    return tty not in {"?", "??"} and "?" not in tty


def _list_processes_macos_linux() -> list[ProcessInfo]:
    out = subprocess.check_output(
        [PS_BIN, "-axo", "pid=,ppid=,tty=,%cpu=,command="],
        text=True,
        stderr=subprocess.DEVNULL,
    )

    rows: list[ProcessInfo] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        pid, ppid, tty, cpu_s, cmd = parts
        try:
            cpu = float(cpu_s)
        except Exception:
            cpu = 0.0
        rows.append(ProcessInfo(pid=pid, ppid=ppid, tty=tty, cpu_percent=cpu, cmd=cmd))
    return rows


def _matching_processes(processes: list[ProcessInfo], config: ProcessConfig) -> list[ProcessInfo]:
    watch = re.compile(config.watch_regex)
    matches: list[ProcessInfo] = []
    for proc in processes:
        if config.require_tty and not _has_tty(proc.tty):
            continue
        if watch.search(proc.cmd):
            matches.append(proc)
    return matches


def _build_children_map(processes: list[ProcessInfo]) -> dict[str, list[ProcessInfo]]:
    children: dict[str, list[ProcessInfo]] = {}
    for proc in processes:
        children.setdefault(proc.ppid, []).append(proc)
    return children


def _descendants_of(pid: str, children_map: dict[str, list[ProcessInfo]]) -> list[ProcessInfo]:
    stack = list(children_map.get(pid, []))
    seen: set[str] = set()
    out: list[ProcessInfo] = []
    while stack:
        proc = stack.pop()
        if proc.pid in seen:
            continue
        seen.add(proc.pid)
        out.append(proc)
        stack.extend(children_map.get(proc.pid, []))
    return out


def _parse_nettop_bytes(output: str) -> dict[str, tuple[int, int]]:
    totals: dict[str, tuple[int, int]] = {}
    for line in output.splitlines():
        if not line or line.startswith("time,"):
            continue
        parts = line.split(",")
        if len(parts) < 6:
            continue
        proc_field = parts[1]
        if not proc_field:
            continue
        pid = proc_field.rsplit(".", 1)[-1]
        if not pid:
            continue
        try:
            bytes_in = int(parts[4] or 0)
            bytes_out = int(parts[5] or 0)
        except Exception:
            continue
        prev_in, prev_out = totals.get(pid, (0, 0))
        totals[pid] = (prev_in + bytes_in, prev_out + bytes_out)
    return totals


def _nettop_totals_for_pids(pids: list[str]) -> dict[str, tuple[int, int]]:
    if not pids:
        return {}

    cmd = [NETTOP_BIN, "-P", "-L", "1", "-n"]
    for pid in pids:
        cmd.extend(["-p", pid])
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return {}
    return _parse_nettop_bytes(out)


def _process_active(
    config: ProcessConfig,
    *,
    now: float,
    matches: list[ProcessInfo],
    children_map: dict[str, list[ProcessInfo]],
    prev_net_totals: dict[str, tuple[int, int]],
    last_active_at: float,
) -> tuple[bool, float, dict[str, Any]]:
    if not matches:
        return False, 0.0, {"evidence": []}

    evidence: list[str] = []
    active_now = False

    if config.cpu_active_threshold_percent > 0:
        for proc in matches:
            if proc.cpu_percent >= config.cpu_active_threshold_percent:
                active_now = True
                evidence.append("cpu")
                break

    if (
        not active_now
        and config.consider_children_active
        and config.cpu_active_threshold_percent > 0
        and children_map
    ):
        watch = re.compile(config.watch_regex)
        match_pids = {p.pid for p in matches}
        for proc in matches:
            for child in _descendants_of(proc.pid, children_map):
                if child.pid in match_pids:
                    continue
                if watch.search(child.cmd):
                    continue
                if proc.tty and child.tty and proc.tty != child.tty:
                    continue
                if child.cpu_percent >= config.cpu_active_threshold_percent:
                    active_now = True
                    evidence.append("child_cpu")
                    break
            if active_now:
                break

    if (
        not active_now
        and config.enable_nettop
        and platform.system() == "Darwin"
        and config.net_active_threshold_bytes > 0
    ):
        pids = [p.pid for p in matches]
        totals = _nettop_totals_for_pids(pids)

        for pid in pids:
            cur = totals.get(pid)
            if cur is None:
                continue
            prev = prev_net_totals.get(pid)
            prev_net_totals[pid] = cur
            if prev is None:
                continue
            delta = max(0, (cur[0] + cur[1]) - (prev[0] + prev[1]))
            if delta >= config.net_active_threshold_bytes:
                active_now = True
                evidence.append("net")
                break

    new_last_active_at = last_active_at
    active = False
    if active_now:
        new_last_active_at = now
        active = True
    else:
        if last_active_at and (now - last_active_at) <= config.active_grace_seconds:
            active = True
            evidence.append("grace")

    debug = {
        "evidence": evidence,
        "active_grace_seconds": config.active_grace_seconds,
        "cpu_active_threshold_percent": config.cpu_active_threshold_percent,
        "net_active_threshold_bytes": config.net_active_threshold_bytes,
        "consider_children_active": config.consider_children_active,
        "enable_nettop": config.enable_nettop,
    }
    return active, new_last_active_at, debug


class ProcessGate:
    def __init__(self, config: ProcessConfig) -> None:
        self.config = config
        self.last_active_at = 0.0
        self.prev_net_totals: dict[str, tuple[int, int]] = {}

    def poll(self) -> tuple[bool, bool, dict[str, Any]]:
        sysname = platform.system()
        if sysname not in {"Darwin", "Linux"}:
            running = self._process_running_fallback()
            return running, running, {"evidence": ["fallback"]}

        try:
            processes = _list_processes_macos_linux()
        except Exception as exc:
            _log("warning", "ps_error", error=str(exc))
            return False, False, {"evidence": ["ps_error"]}

        matches = _matching_processes(processes, self.config)
        if not matches:
            self.last_active_at = 0.0
            self.prev_net_totals = {}
            return False, False, {"evidence": []}

        match_pids = {p.pid for p in matches}
        self.prev_net_totals = {
            pid: totals for pid, totals in self.prev_net_totals.items() if pid in match_pids
        }
        children_map = _build_children_map(processes)
        now = time.time()
        active, self.last_active_at, debug = _process_active(
            self.config,
            now=now,
            matches=matches,
            children_map=children_map,
            prev_net_totals=self.prev_net_totals,
            last_active_at=self.last_active_at,
        )
        return True, active, debug

    def _process_running_fallback(self) -> bool:
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
        watch = re.compile(self.config.watch_regex)
        return any(watch.search(line or "") for line in out.splitlines())
