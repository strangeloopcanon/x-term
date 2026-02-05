from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProcessConfig:
    watch_regex: str
    require_tty: bool
    app_watch_regex: str
    app_require_tty: bool
    active_grace_seconds: float
    cpu_active_threshold_percent: float
    net_active_threshold_bytes: int
    enable_nettop: bool
    consider_children_active: bool


@dataclass(frozen=True)
class GateConfig:
    enabled: bool
    reward_mode: bool
    poll_interval_seconds: float
    blocklist: list[str]
    include_www: bool
    process: ProcessConfig


DEFAULT_PROCESS_CONFIG = ProcessConfig(
    watch_regex=r"(?i)\b(codex|claude(?:-code)?|claude_code)\b",
    require_tty=True,
    app_watch_regex=r"(?i)\bcodex app-server\b",
    app_require_tty=False,
    active_grace_seconds=15.0,
    cpu_active_threshold_percent=1.0,
    net_active_threshold_bytes=1,
    enable_nettop=True,
    consider_children_active=True,
)


DEFAULT_CONFIG = GateConfig(
    enabled=True,
    reward_mode=True,
    poll_interval_seconds=1.0,
    blocklist=["x.com", "twitter.com"],
    include_www=True,
    process=DEFAULT_PROCESS_CONFIG,
)


def _get(data: dict[str, Any], key: str, default: Any) -> Any:
    value = data.get(key, default)
    return default if value is None else value


def _process_from_dict(data: dict[str, Any] | None) -> ProcessConfig:
    if not isinstance(data, dict):
        return DEFAULT_PROCESS_CONFIG
    return ProcessConfig(
        watch_regex=str(_get(data, "watch_regex", DEFAULT_PROCESS_CONFIG.watch_regex)),
        require_tty=bool(_get(data, "require_tty", DEFAULT_PROCESS_CONFIG.require_tty)),
        app_watch_regex=str(_get(data, "app_watch_regex", DEFAULT_PROCESS_CONFIG.app_watch_regex)),
        app_require_tty=bool(_get(data, "app_require_tty", DEFAULT_PROCESS_CONFIG.app_require_tty)),
        active_grace_seconds=float(
            _get(data, "active_grace_seconds", DEFAULT_PROCESS_CONFIG.active_grace_seconds)
        ),
        cpu_active_threshold_percent=float(
            _get(
                data,
                "cpu_active_threshold_percent",
                DEFAULT_PROCESS_CONFIG.cpu_active_threshold_percent,
            )
        ),
        net_active_threshold_bytes=int(
            _get(data, "net_active_threshold_bytes", DEFAULT_PROCESS_CONFIG.net_active_threshold_bytes)
        ),
        enable_nettop=bool(_get(data, "enable_nettop", DEFAULT_PROCESS_CONFIG.enable_nettop)),
        consider_children_active=bool(
            _get(data, "consider_children_active", DEFAULT_PROCESS_CONFIG.consider_children_active)
        ),
    )


def _process_to_dict(config: ProcessConfig) -> dict[str, Any]:
    return {
        "watch_regex": config.watch_regex,
        "require_tty": config.require_tty,
        "app_watch_regex": config.app_watch_regex,
        "app_require_tty": config.app_require_tty,
        "active_grace_seconds": config.active_grace_seconds,
        "cpu_active_threshold_percent": config.cpu_active_threshold_percent,
        "net_active_threshold_bytes": config.net_active_threshold_bytes,
        "enable_nettop": config.enable_nettop,
        "consider_children_active": config.consider_children_active,
    }


def config_from_dict(data: dict[str, Any]) -> GateConfig:
    blocklist = _get(data, "blocklist", DEFAULT_CONFIG.blocklist)
    if not isinstance(blocklist, list):
        blocklist = DEFAULT_CONFIG.blocklist
    blocklist = [str(item) for item in blocklist if str(item).strip()]

    return GateConfig(
        enabled=bool(_get(data, "enabled", DEFAULT_CONFIG.enabled)),
        reward_mode=bool(_get(data, "reward_mode", DEFAULT_CONFIG.reward_mode)),
        poll_interval_seconds=float(
            _get(data, "poll_interval_seconds", DEFAULT_CONFIG.poll_interval_seconds)
        ),
        blocklist=blocklist,
        include_www=bool(_get(data, "include_www", DEFAULT_CONFIG.include_www)),
        process=_process_from_dict(_get(data, "process", None)),
    )


def config_to_dict(config: GateConfig) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "reward_mode": config.reward_mode,
        "poll_interval_seconds": config.poll_interval_seconds,
        "blocklist": list(config.blocklist),
        "include_www": config.include_www,
        "process": _process_to_dict(config.process),
    }


def load_config(path: Path) -> GateConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    return config_from_dict(data)


def save_config(path: Path, config: GateConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config_to_dict(config), indent=2, sort_keys=True)
    path.write_text(payload + "\n", encoding="utf-8")


def ensure_config(path: Path) -> GateConfig:
    if path.exists():
        return load_config(path)
    save_config(path, DEFAULT_CONFIG)
    return DEFAULT_CONFIG


def update_config(path: Path, **changes: Any) -> GateConfig:
    current = ensure_config(path)
    updated = replace(current, **changes)
    save_config(path, updated)
    return updated
