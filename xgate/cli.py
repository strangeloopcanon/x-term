from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import COMPAT_VERSION, __version__
from .chrome import reset_chrome_network_service, restart_chrome
from .config import DEFAULT_CONFIG, GateConfig, ensure_config, save_config, update_config
from .hosts import expand_domains, hosts_has_block, normalize_domain
from .install import (
    daemon_status,
    install_daemon,
    install_menubar,
    uninstall_daemon,
    uninstall_menubar,
)
from .paths import config_path, hosts_path, state_path
from .policy import should_block
from .process_gate import ProcessGate

DEPLOYED_APP_DIR = Path("/Library/Application Support/x-gate/app/xgate")


def _resolve_config_path(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser()
    return config_path()


def _prompt_domain() -> str:
    if sys.platform != "darwin":
        raise RuntimeError("--prompt is only supported on macOS")
    script = 'text returned of (display dialog "Add domain to block" default answer "")'
    try:
        output = subprocess.check_output(["/usr/bin/osascript", "-e", script], text=True)
    except subprocess.CalledProcessError:
        return ""
    return output.strip()


def _print_status(data: dict[str, Any]) -> None:
    print("X Gate")
    print(f"  enabled: {data['enabled']}")
    print(f"  reward_mode: {data['reward_mode']}")
    print(f"  process_running: {data['process_running']}")
    print(f"  process_active: {data['process_active']}")
    print(f"  should_block: {data['should_block']}")
    print(f"  hosts_blocked: {data['hosts_blocked']}")
    print(f"  config_path: {data['config_path']}")
    print(f"  blocklist: {', '.join(data['blocklist']) if data['blocklist'] else '(empty)'}")
    warnings = data.get("status_warnings") or []
    if warnings:
        print("  warnings:")
        for warning in warnings:
            print(f"    - {warning}")


def _read_daemon_state(*, max_age_seconds: float) -> dict[str, Any] | None:
    path = state_path()
    if not path.exists():
        return None
    try:
        age = time.time() - path.stat().st_mtime
        if age > max(0.0, max_age_seconds):
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data["_age_seconds"] = age
    return data


def _read_deployed_compat() -> tuple[int | None, str | None]:
    init_path = DEPLOYED_APP_DIR / "__init__.py"
    if not init_path.exists():
        return None, "deployed daemon package not found; run `sudo ./bin/xgate daemon install`"
    try:
        content = init_path.read_text(encoding="utf-8")
    except Exception as exc:
        return None, f"unable to read deployed daemon metadata: {exc}"

    compat_match = re.search(r"^COMPAT_VERSION\s*=\s*(\d+)\s*$", content, flags=re.MULTILINE)
    if compat_match is None:
        return None, "deployed daemon missing COMPAT_VERSION marker; reinstall daemon"
    return int(compat_match.group(1)), None


def _status_payload(config: GateConfig, *, debug: bool, config_file: Path) -> dict[str, Any]:
    gate = ProcessGate(config.process)
    running, active, active_debug = gate.poll()
    daemon_state = _read_daemon_state(
        max_age_seconds=max(3.0, float(config.poll_interval_seconds) * 3.0)
    )
    if daemon_state is not None:
        running = bool(daemon_state.get("process_running", running))
        active = bool(daemon_state.get("process_active", active))
        active_debug = {"evidence": daemon_state.get("evidence", [])}

    try:
        expanded = expand_domains(config.blocklist, include_www=config.include_www)
    except ValueError:
        expanded = [domain for domain in config.blocklist if str(domain).strip()]

    computed_should_block = should_block(config, active)
    daemon_block = daemon_state.get("block") if daemon_state else None
    daemon_compat = daemon_state.get("compat_version") if daemon_state else None
    deployed_compat, deployed_error = _read_deployed_compat()

    status_warnings: list[str] = []
    if isinstance(deployed_compat, int) and deployed_compat != COMPAT_VERSION:
        status_warnings.append(
            f"CLI/daemon mismatch (cli={COMPAT_VERSION}, deployed={deployed_compat}); run `sudo ./bin/xgate daemon install`"
        )
    elif deployed_error:
        status_warnings.append(deployed_error)
    if daemon_state is not None and isinstance(daemon_compat, int) and daemon_compat != COMPAT_VERSION:
        status_warnings.append(
            f"running daemon compat mismatch (cli={COMPAT_VERSION}, daemon={daemon_compat}); reinstall daemon"
        )
    if daemon_state is None:
        status_warnings.append("daemon state unavailable; status may be stale")

    payload = {
        "cli_version": __version__,
        "compat_version": COMPAT_VERSION,
        "enabled": config.enabled,
        "reward_mode": config.reward_mode,
        "process_running": running,
        "process_active": active,
        "should_block": bool(daemon_block) if isinstance(daemon_block, bool) else computed_should_block,
        "hosts_blocked": hosts_has_block(hosts_path()),
        "config_path": str(config_file),
        "blocklist": list(expanded),
        "include_www": config.include_www,
        "poll_interval_seconds": config.poll_interval_seconds,
        "daemon_state": daemon_state is not None,
        "daemon_compat_version": daemon_compat if isinstance(daemon_compat, int) else None,
        "deployed_compat_version": deployed_compat if isinstance(deployed_compat, int) else None,
        "status_warnings": status_warnings,
    }
    if debug:
        payload["active_debug"] = active_debug
    return payload


def cmd_status(args: argparse.Namespace) -> int:
    config_file = _resolve_config_path(args.config)
    config = ensure_config(config_file)
    payload = _status_payload(config, debug=args.debug, config_file=config_file)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        _print_status(payload)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    if path.exists():
        print(f"Config already exists: {path}")
        return 0
    save_config(path, DEFAULT_CONFIG)
    print(f"Created config: {path}")
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    update_config(_resolve_config_path(args.config), enabled=True)
    print("Enabled")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    update_config(_resolve_config_path(args.config), enabled=False)
    print("Disabled")
    return 0


def cmd_toggle(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    current = ensure_config(path)
    update_config(path, enabled=not current.enabled)
    print(f"Enabled: {not current.enabled}")
    return 0


def cmd_reward(args: argparse.Namespace) -> int:
    value = args.value.lower()
    if value not in {"on", "off"}:
        raise SystemExit("reward must be 'on' or 'off'")
    update_config(_resolve_config_path(args.config), reward_mode=value == "on")
    print(f"Reward mode: {value}")
    return 0


def cmd_blocklist_list(args: argparse.Namespace) -> int:
    config = ensure_config(_resolve_config_path(args.config))
    domains = expand_domains(config.blocklist, include_www=config.include_www)
    for domain in domains:
        print(domain)
    return 0


def cmd_blocklist_add(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    config = ensure_config(path)
    domains = list(args.domains or [])
    if args.prompt:
        prompt_value = _prompt_domain()
        if prompt_value:
            domains.append(prompt_value)
    if not domains:
        raise SystemExit("provide at least one domain or use --prompt")
    normalized: list[str] = []
    for domain in domains:
        try:
            normalized.append(normalize_domain(domain))
        except ValueError as exc:
            raise SystemExit(f"invalid domain: {domain}") from exc
    new_blocklist = list(config.blocklist)
    for domain in normalized:
        if domain not in new_blocklist:
            new_blocklist.append(domain)
    save_config(path, replace(config, blocklist=new_blocklist))
    print("Added")
    return 0


def cmd_blocklist_remove(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    config = ensure_config(path)
    if not args.domains:
        raise SystemExit("provide at least one domain")
    try:
        remove = {normalize_domain(domain) for domain in args.domains}
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    new_blocklist = [domain for domain in config.blocklist if domain not in remove]
    save_config(path, replace(config, blocklist=new_blocklist))
    print("Removed")
    return 0


def cmd_menubar_install(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    xgate_bin = repo_root / "bin" / "xgate"
    if not xgate_bin.exists():
        raise SystemExit("missing xgate wrapper script at repo root")
    plugin_path = install_menubar(xgate_bin=xgate_bin, config_path=_resolve_config_path(args.config))
    print(f"Installed menu bar plugin: {plugin_path}")
    return 0


def cmd_menubar_uninstall(args: argparse.Namespace) -> int:
    uninstall_menubar()
    print("Removed menu bar plugin")
    return 0


def cmd_daemon_install(args: argparse.Namespace) -> int:
    try:
        install_daemon(_resolve_config_path(args.config))
    except PermissionError as exc:
        raise SystemExit("daemon install requires sudo") from exc
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print("Daemon installed")
    return 0


def cmd_daemon_uninstall(args: argparse.Namespace) -> int:
    try:
        uninstall_daemon()
    except PermissionError as exc:
        raise SystemExit("daemon uninstall requires sudo") from exc
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print("Daemon removed")
    return 0


def cmd_daemon_status(args: argparse.Namespace) -> int:
    status = daemon_status()
    if args.json:
        print(json.dumps(status, indent=2))
    else:
        print(status["stdout"] or status["stderr"])
    return 0


def cmd_chrome_restart(args: argparse.Namespace) -> int:
    try:
        restart_chrome(app_name=args.app)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print("Chrome restart requested")
    return 0


def cmd_chrome_reset_network(args: argparse.Namespace) -> int:
    try:
        count = reset_chrome_network_service()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if count:
        print(f"Chrome Network Service reset ({count} process{'es' if count != 1 else ''})")
    else:
        print("Chrome Network Service not found (is Chrome running?)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xgate", description="Hosts-based X/Twitter gate")
    parser.add_argument("--config", default=None, help="Override config.json path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show current status")
    status_parser.add_argument("--json", action="store_true", help="Emit JSON")
    status_parser.add_argument("--debug", action="store_true", help="Include activity debug")
    status_parser.set_defaults(func=cmd_status)

    init_parser = subparsers.add_parser("init", help="Create default config")
    init_parser.set_defaults(func=cmd_init)

    enable_parser = subparsers.add_parser("enable", help="Enable gating")
    enable_parser.set_defaults(func=cmd_enable)

    disable_parser = subparsers.add_parser("disable", help="Disable gating")
    disable_parser.set_defaults(func=cmd_disable)

    toggle_parser = subparsers.add_parser("toggle", help="Toggle enabled on/off")
    toggle_parser.set_defaults(func=cmd_toggle)

    reward_parser = subparsers.add_parser("reward", help="Set reward mode")
    reward_parser.add_argument("value", choices=["on", "off"])
    reward_parser.set_defaults(func=cmd_reward)

    blocklist_parser = subparsers.add_parser("blocklist", help="Manage blocked domains")
    blocklist_sub = blocklist_parser.add_subparsers(dest="block_cmd", required=True)

    blocklist_list = blocklist_sub.add_parser("list", help="List blocked domains")
    blocklist_list.set_defaults(func=cmd_blocklist_list)

    blocklist_add = blocklist_sub.add_parser("add", help="Add blocked domains")
    blocklist_add.add_argument("domains", nargs="*", help="Domains to add")
    blocklist_add.add_argument("--prompt", action="store_true", help="Prompt for a domain")
    blocklist_add.set_defaults(func=cmd_blocklist_add)

    blocklist_remove = blocklist_sub.add_parser("remove", help="Remove blocked domains")
    blocklist_remove.add_argument("domains", nargs="+", help="Domains to remove")
    blocklist_remove.set_defaults(func=cmd_blocklist_remove)

    menubar_parser = subparsers.add_parser("menubar", help="Manage menubar integration")
    menubar_sub = menubar_parser.add_subparsers(dest="menubar_cmd", required=True)
    menubar_install = menubar_sub.add_parser("install", help="Install SwiftBar plugin")
    menubar_install.set_defaults(func=cmd_menubar_install)
    menubar_uninstall = menubar_sub.add_parser("uninstall", help="Remove SwiftBar plugin")
    menubar_uninstall.set_defaults(func=cmd_menubar_uninstall)

    chrome_parser = subparsers.add_parser("chrome", help="Chrome helpers (macOS)")
    chrome_sub = chrome_parser.add_subparsers(dest="chrome_cmd", required=True)
    chrome_restart = chrome_sub.add_parser(
        "restart", help="Restart Chrome via chrome://restart (flushes DNS/socket pools)"
    )
    chrome_restart.add_argument("--app", default="Google Chrome", help="App name (e.g. Google Chrome)")
    chrome_restart.set_defaults(func=cmd_chrome_restart)
    chrome_reset = chrome_sub.add_parser(
        "reset-network", help="Restart Chrome Network Service (flushes DNS/socket pools)"
    )
    chrome_reset.set_defaults(func=cmd_chrome_reset_network)

    daemon_parser = subparsers.add_parser("daemon", help="Manage daemon")
    daemon_sub = daemon_parser.add_subparsers(dest="daemon_cmd", required=True)
    daemon_install = daemon_sub.add_parser("install", help="Install launchd daemon (sudo)")
    daemon_install.set_defaults(func=cmd_daemon_install)
    daemon_uninstall = daemon_sub.add_parser("uninstall", help="Remove launchd daemon (sudo)")
    daemon_uninstall.set_defaults(func=cmd_daemon_uninstall)
    daemon_status_cmd = daemon_sub.add_parser("status", help="Show launchd status")
    daemon_status_cmd.add_argument("--json", action="store_true", help="Emit JSON")
    daemon_status_cmd.set_defaults(func=cmd_daemon_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
