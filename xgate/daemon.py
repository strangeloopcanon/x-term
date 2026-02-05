from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import signal
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import COMPAT_VERSION, __version__
from .config import DEFAULT_CONFIG, GateConfig, load_config
from .hosts import apply_hosts, expand_domains, normalize_domain
from .paths import hosts_path, log_path, state_path
from .policy import should_block
from .process_gate import ProcessGate, set_log_file


def _log(level: str, message: str, **fields: Any) -> None:
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "level": level,
        "logger": "xgate_daemon",
        "message": message,
        **fields,
    }
    log_file = log_path(for_daemon=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _write_state(payload: dict[str, Any]) -> None:
    path = state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
        with contextlib.suppress(Exception):
            os.chmod(path, 0o644)
    except Exception as exc:
        _log("warning", "state_write_failed", path=str(path), error=str(exc))


def _load_config_safe(path: Path) -> tuple[GateConfig, bool]:
    try:
        return load_config(path), True
    except FileNotFoundError:
        return DEFAULT_CONFIG, False
    except Exception as exc:
        _log("warning", "config_load_failed", error=str(exc), path=str(path))
        return DEFAULT_CONFIG, False


def _expand_blocklist(blocklist: list[str], include_www: bool) -> list[str]:
    cleaned: list[str] = []
    for entry in blocklist:
        try:
            cleaned.append(normalize_domain(entry))
        except ValueError:
            _log("warning", "invalid_domain_ignored", value=str(entry))
    return expand_domains(cleaned, include_www=include_www)


def _flush_dns() -> None:
    if platform.system() != "Darwin":
        return
    for cmd in (["/usr/bin/dscacheutil", "-flushcache"], ["/usr/bin/killall", "-HUP", "mDNSResponder"]):
        with contextlib.suppress(Exception):
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_loop(config_file: Path, *, once: bool) -> int:
    set_log_file(log_path(for_daemon=True))

    gate_config, found = _load_config_safe(config_file)
    if not found:
        gate_config = replace(gate_config, enabled=False)
        _log("warning", "config_missing_fail_open", path=str(config_file))

    gate = ProcessGate(gate_config.process)
    last_block: bool | None = None
    last_domains: list[str] | None = None

    stop = False

    def _handle_stop(_: int, __: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    while not stop:
        gate_config, found = _load_config_safe(config_file)
        if not found:
            gate_config = replace(gate_config, enabled=False)

        if gate.config != gate_config.process:
            gate = ProcessGate(gate_config.process)

        process_running, process_active, active_debug = gate.poll()
        block_now = should_block(gate_config, process_active)
        domains = _expand_blocklist(gate_config.blocklist, gate_config.include_www)

        _write_state(
            {
                "timestamp_unix": time.time(),
                "block": block_now,
                "process_running": process_running,
                "process_active": process_active,
                "evidence": active_debug.get("evidence"),
                "enabled": gate_config.enabled,
                "reward_mode": gate_config.reward_mode,
                "poll_interval_seconds": gate_config.poll_interval_seconds,
                "daemon_version": __version__,
                "compat_version": COMPAT_VERSION,
            }
        )

        if block_now != last_block or domains != (last_domains or []):
            _log(
                "info",
                "state_update",
                block=block_now,
                process_running=process_running,
                process_active=process_active,
                evidence=active_debug.get("evidence"),
            )
            try:
                changed = apply_hosts(
                    hosts_path(),
                    domains=domains,
                    should_block=block_now,
                )
                if changed:
                    _flush_dns()
                    _log("info", "hosts_updated", block=block_now, domains=len(domains))
            except PermissionError:
                _log("error", "hosts_permission_error", path=str(hosts_path()))
            except Exception as exc:
                _log("error", "hosts_update_failed", error=str(exc))

            last_block = block_now
            last_domains = list(domains)

        if once:
            break
        time.sleep(max(0.2, gate_config.poll_interval_seconds))

    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="xgate daemon (hosts-based X/Twitter gate)")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config.json (defaults to XGATE_CONFIG or OS default).",
    )
    parser.add_argument("--once", action="store_true", help="Apply state once and exit.")
    args = parser.parse_args(argv)

    if args.config:
        config_file = Path(args.config).expanduser()
    elif os.environ.get("XGATE_CONFIG"):
        config_file = Path(os.environ.get("XGATE_CONFIG", "")).expanduser()
    else:
        from .paths import config_path

        config_file = config_path()

    if not config_file.exists():
        _log("warning", "config_missing", path=str(config_file))

    return run_loop(config_file, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
