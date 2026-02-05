from __future__ import annotations

import os
import pwd
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

LABEL = "com.xterm.xgate"
PLIST_PATH = Path("/Library/LaunchDaemons") / f"{LABEL}.plist"
APP_ROOT = Path("/Library/Application Support/x-gate")
APP_CODE_DIR = APP_ROOT / "app"
MENUBAR_PLUGIN_NAME = "xgate.10s.sh"
MENUBAR_PLUGIN_LEGACY = "xgate.1m.sh"


def _require_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError("root required")


def _launchctl(args: list[str]) -> None:
    subprocess.run(["/bin/launchctl", *args], check=False)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _python_executable() -> str:
    return os.environ.get("PYTHON", "/usr/bin/python3")


def _install_code() -> Path:
    """Copy the xgate package to a system location that launchd can access.

    We avoid running code directly from ~/Documents because system daemons can
    be blocked by macOS privacy controls (TCC).
    """
    repo_root = _repo_root()
    src_pkg = repo_root / "xgate"
    if not src_pkg.exists():
        raise FileNotFoundError(f"missing package directory: {src_pkg}")

    APP_CODE_DIR.mkdir(parents=True, exist_ok=True)
    dst_pkg = APP_CODE_DIR / "xgate"
    if dst_pkg.exists():
        shutil.rmtree(dst_pkg)
    shutil.copytree(src_pkg, dst_pkg, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return APP_CODE_DIR


def _write_plist(config_path: Path, *, working_dir: Path) -> None:
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{_python_executable()}</string>
    <string>-m</string>
    <string>xgate.daemon</string>
    <string>--config</string>
    <string>{config_path}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>{working_dir}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
    <key>PYTHONPATH</key>
    <string>{working_dir}</string>
  </dict>
  <key>StandardOutPath</key>
  <string>/Library/Logs/x-term/xgate-daemon.log</string>
  <key>StandardErrorPath</key>
  <string>/Library/Logs/x-term/xgate-daemon.log</string>
</dict>
</plist>
"""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist, encoding="utf-8")


def _ensure_log_dir() -> None:
    Path("/Library/Logs/x-term").mkdir(parents=True, exist_ok=True)


def _user_from_sudo() -> pwd.struct_passwd:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        return pwd.getpwnam(sudo_user)

    try:
        console_uid = os.stat("/dev/console").st_uid
        console_user = pwd.getpwuid(console_uid).pw_name
        if console_user and console_user != "root":
            return pwd.getpwnam(console_user)
    except Exception:
        pass

    raise RuntimeError("Could not determine target user (SUDO_USER missing and /dev/console unknown)")


def _ensure_user_config(config_path: Path, user: pwd.struct_passwd) -> None:
    if config_path.exists():
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    default = Path(__file__).resolve().parents[1] / "xgate" / "default_config.json"
    if default.exists():
        config_path.write_text(default.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        config_path.write_text("{}", encoding="utf-8")
    _chown(config_path.parent, user)


def _chown(path: Path, user: pwd.struct_passwd) -> None:
    os.chown(path, user.pw_uid, user.pw_gid)


def install_daemon(config_path: Path) -> None:
    _require_root()
    user = _user_from_sudo()
    _ensure_log_dir()
    working_dir = _install_code()
    _ensure_user_config(config_path, user)
    _chown(config_path, user)
    _write_plist(config_path, working_dir=working_dir)
    _launchctl(["bootout", f"system/{LABEL}"])
    _launchctl(["bootstrap", "system", str(PLIST_PATH)])
    _launchctl(["enable", f"system/{LABEL}"])
    _launchctl(["kickstart", "-k", f"system/{LABEL}"])


def uninstall_daemon() -> None:
    _require_root()
    _launchctl(["bootout", f"system/{LABEL}"])
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    if APP_CODE_DIR.exists():
        shutil.rmtree(APP_CODE_DIR, ignore_errors=True)


def daemon_status() -> dict[str, Any]:
    result = subprocess.run(
        ["/bin/launchctl", "print", f"system/{LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {"code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def _swiftbar_plugins_dir() -> Path:
    override = os.environ.get("XGATE_SWIFTBAR_PLUGINS_DIR")
    if override:
        return Path(override).expanduser()

    try:
        result = subprocess.run(
            ["/usr/bin/defaults", "read", "com.ameba.SwiftBar", "PluginDirectory"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            directory = result.stdout.strip().strip('"')
            if directory:
                return Path(directory).expanduser()
    except Exception:
        pass

    return Path.home() / "Library" / "Application Support" / "SwiftBar" / "Plugins"


def install_menubar(xgate_bin: Path, config_path: Path) -> Path:
    plugin_dir = _swiftbar_plugins_dir()
    plugin_dir.mkdir(parents=True, exist_ok=True)
    plugin_path = plugin_dir / MENUBAR_PLUGIN_NAME
    legacy_path = plugin_dir / MENUBAR_PLUGIN_LEGACY
    if legacy_path.exists() and legacy_path != plugin_path:
        legacy_path.unlink()

    script = """#!/usr/bin/env bash
export XGATE_BIN="__XGATE_BIN__"
export XGATE_CONFIG="__XGATE_CONFIG__"
exec /usr/bin/python3 - <<'PY'
import json
import os
import subprocess
import sys

xgate = os.environ["XGATE_BIN"]

try:
    status_json = subprocess.check_output([xgate, "status", "--json"], text=True, stderr=subprocess.DEVNULL)
except Exception:
    print("X Gate (error) | color=red")
    print("---")
    print("Status unavailable")
    sys.exit(0)

data = json.loads(status_json)
blocked = bool(data.get("hosts_blocked", False))
state = "BLOCK" if blocked else "ALLOW"
color = "red" if blocked else "green"
print(f"X Gate: {state} | color={color}")
desired_block = bool(data.get("should_block", blocked))
if desired_block != blocked:
    desired = "BLOCK" if desired_block else "ALLOW"
    print(f"Desired: {desired} (syncing…) | color=orange")
print("---")
enabled = data.get("enabled", False)
reward = data.get("reward_mode", False)
print(
    f"Enabled: {'On' if enabled else 'Off'} | bash={xgate} param1={'disable' if enabled else 'enable'} terminal=false refresh=true"
)
print(
    f"Reward Mode: {'On' if reward else 'Off'} | bash={xgate} param1=reward param2={'off' if reward else 'on'} terminal=false refresh=true"
)
process_line = "Active" if data.get("process_active") else "Idle"
print(f"Process: {process_line}")
warnings = data.get("status_warnings") or []
if warnings:
    print(f"Warning: {warnings[0]} | color=orange")
print("---")
print(f"Reset Chrome network (apply now) | bash={xgate} param1=chrome param2=reset-network terminal=false refresh=false")
print(f"Restart Chrome (apply now) | bash={xgate} param1=chrome param2=restart terminal=false refresh=false")
print("---")
print(f"Add domain… | bash={xgate} param1=blocklist param2=add param3=--prompt terminal=false refresh=true")
print("Blocklist")
for domain in data.get("blocklist", []):
    print(f"-- {domain}")
PY
"""
    script = (
        script.replace("__XGATE_BIN__", str(xgate_bin))
        .replace("__XGATE_CONFIG__", str(config_path))
    )
    plugin_path.write_text(script, encoding="utf-8")
    plugin_path.chmod(plugin_path.stat().st_mode | stat.S_IXUSR)
    return plugin_path


def uninstall_menubar() -> None:
    plugin_dir = _swiftbar_plugins_dir()
    for name in (MENUBAR_PLUGIN_NAME, MENUBAR_PLUGIN_LEGACY):
        plugin_path = plugin_dir / name
        if plugin_path.exists():
            plugin_path.unlink()
