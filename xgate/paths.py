from __future__ import annotations

import os
import platform
import pwd
from pathlib import Path


def _home_dir() -> Path:
    if os.geteuid() == 0:
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user:
            try:
                return Path(pwd.getpwnam(sudo_user).pw_dir)
            except KeyError:
                pass
        try:
            console_uid = os.stat("/dev/console").st_uid
            console_user = pwd.getpwuid(console_uid).pw_name
            if console_user and console_user != "root":
                return Path(pwd.getpwnam(console_user).pw_dir)
        except Exception:
            pass
    return Path.home()


def config_path() -> Path:
    override = os.environ.get("XGATE_CONFIG")
    if override:
        return Path(override).expanduser()

    sysname = platform.system()
    if sysname == "Darwin":
        return _home_dir() / "Library" / "Application Support" / "x-gate" / "config.json"
    if sysname == "Linux":
        return _home_dir() / ".config" / "x-gate" / "config.json"
    return _home_dir() / ".x-gate" / "config.json"


def hosts_path() -> Path:
    override = os.environ.get("XGATE_HOSTS_PATH")
    if override:
        return Path(override).expanduser()
    return Path("/etc/hosts")


def log_path(*, for_daemon: bool) -> Path:
    override = os.environ.get("XGATE_LOG")
    if override:
        return Path(override).expanduser()

    sysname = platform.system()
    if sysname == "Darwin":
        if for_daemon:
            return Path("/Library/Logs/x-term/xgate-daemon.log")
        return _home_dir() / "Library" / "Logs" / "x-term" / "xgate.log"
    if sysname == "Linux":
        if for_daemon:
            return Path("/var/log/xgate/xgate-daemon.log")
        return _home_dir() / ".cache" / "x-term" / "xgate.log"
    if for_daemon:
        return _home_dir() / ".x-gate" / "logs" / "xgate-daemon.log"
    return _home_dir() / ".x-gate" / "logs" / "xgate.log"


def state_path() -> Path:
    override = os.environ.get("XGATE_STATE")
    if override:
        return Path(override).expanduser()

    sysname = platform.system()
    if sysname == "Darwin":
        return Path("/Library/Application Support/x-gate/state.json")
    if sysname == "Linux":
        return Path("/var/run/x-gate/state.json")
    return _home_dir() / ".x-gate" / "state.json"
