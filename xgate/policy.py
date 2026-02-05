from __future__ import annotations

import re
import time
from dataclasses import dataclass

from .config import GateConfig

WINDOW_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")
DURATION_TOKEN_RE = re.compile(r"(\d+)\s*([smhd])", flags=re.IGNORECASE)


@dataclass(frozen=True)
class BlockDecision:
    should_block: bool
    reasons: list[str]
    activity_block_active: bool
    time_block_active: bool
    timer_block_active: bool


def normalize_time_block(value: str) -> str:
    match = WINDOW_RE.match(value)
    if match is None:
        raise ValueError("time block must be HH:MM-HH:MM (24h)")
    start_h, start_m, end_h, end_m = (int(part) for part in match.groups())
    if start_h > 23 or end_h > 23 or start_m > 59 or end_m > 59:
        raise ValueError("invalid time block; hours 00-23 and minutes 00-59")
    if start_h == end_h and start_m == end_m:
        raise ValueError("time block start and end cannot be the same")
    return f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}"


def parse_duration_seconds(value: str) -> int:
    text = value.strip().lower()
    if not text:
        raise ValueError("duration must be non-empty (example: 3h)")

    position = 0
    total = 0
    for match in DURATION_TOKEN_RE.finditer(text):
        if match.start() != position and text[position:match.start()].strip():
            raise ValueError("invalid duration format (example: 3h, 45m, 1h 30m)")
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if amount <= 0:
            raise ValueError("duration units must be positive")
        multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        total += amount * multiplier
        position = match.end()
    if position == 0 or text[position:].strip():
        raise ValueError("invalid duration format (example: 3h, 45m, 1h 30m)")
    return total


def _minutes_of_day(hour: int, minute: int) -> int:
    return hour * 60 + minute


def is_time_block_active(value: str, *, now_local: time.struct_time | None = None) -> bool:
    normalized = normalize_time_block(value)
    start_s, end_s = normalized.split("-", 1)
    start_h, start_m = (int(part) for part in start_s.split(":", 1))
    end_h, end_m = (int(part) for part in end_s.split(":", 1))

    local = now_local or time.localtime()
    now_minutes = _minutes_of_day(local.tm_hour, local.tm_min)
    start_minutes = _minutes_of_day(start_h, start_m)
    end_minutes = _minutes_of_day(end_h, end_m)

    if start_minutes < end_minutes:
        return start_minutes <= now_minutes < end_minutes
    return now_minutes >= start_minutes or now_minutes < end_minutes


def _activity_blocks(config: GateConfig, process_active: bool) -> bool:
    if config.reward_mode:
        return not process_active
    return process_active


def block_decision(
    config: GateConfig,
    process_active: bool,
    *,
    now_unix: float | None = None,
) -> BlockDecision:
    if not config.enabled:
        return BlockDecision(
            should_block=False,
            reasons=[],
            activity_block_active=False,
            time_block_active=False,
            timer_block_active=False,
        )

    ts = time.time() if now_unix is None else now_unix

    activity_block_active = _activity_blocks(config, process_active)
    timer_block_active = float(config.block_until_unix) > ts
    time_block_active = any(is_time_block_active(block) for block in config.time_blocks)

    reasons: list[str] = []
    if timer_block_active:
        reasons.append("timer")
    if time_block_active:
        reasons.append("time_block")
    if activity_block_active:
        reasons.append("activity")

    return BlockDecision(
        should_block=bool(reasons),
        reasons=reasons,
        activity_block_active=activity_block_active,
        time_block_active=time_block_active,
        timer_block_active=timer_block_active,
    )


def should_block(config: GateConfig, process_active: bool) -> bool:
    return block_decision(config, process_active).should_block
