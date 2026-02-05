from __future__ import annotations

import time
from dataclasses import replace

import pytest

from xgate.config import DEFAULT_CONFIG
from xgate.policy import (
    block_decision,
    is_time_block_active,
    normalize_time_block,
    parse_duration_seconds,
)


def _local_time(hour: int, minute: int) -> time.struct_time:
    return time.struct_time((2026, 2, 5, hour, minute, 0, 3, 36, -1))


def test_normalize_time_block():
    assert normalize_time_block("9:05-17:45") == "09:05-17:45"
    assert normalize_time_block("22:00 - 7:00") == "22:00-07:00"


@pytest.mark.parametrize("value", ["", "9-5", "25:00-12:00", "09:60-10:00", "10:00-10:00"])
def test_normalize_time_block_rejects_invalid(value: str):
    with pytest.raises(ValueError):
        normalize_time_block(value)


def test_is_time_block_active_same_day_window():
    assert is_time_block_active("09:00-17:00", now_local=_local_time(9, 0)) is True
    assert is_time_block_active("09:00-17:00", now_local=_local_time(16, 59)) is True
    assert is_time_block_active("09:00-17:00", now_local=_local_time(17, 0)) is False


def test_is_time_block_active_overnight_window():
    assert is_time_block_active("22:00-07:00", now_local=_local_time(23, 30)) is True
    assert is_time_block_active("22:00-07:00", now_local=_local_time(6, 59)) is True
    assert is_time_block_active("22:00-07:00", now_local=_local_time(12, 0)) is False


def test_parse_duration_seconds():
    assert parse_duration_seconds("3h") == 10800
    assert parse_duration_seconds("45m") == 2700
    assert parse_duration_seconds("1h 30m") == 5400
    assert parse_duration_seconds("2d4h") == 187200


@pytest.mark.parametrize("value", ["", "3", "0h", "-3h", "1x", "1h foo"])
def test_parse_duration_seconds_rejects_invalid(value: str):
    with pytest.raises(ValueError):
        parse_duration_seconds(value)


def test_block_decision_enabled_off_is_allow():
    config = replace(DEFAULT_CONFIG, enabled=False, time_blocks=["00:00-23:59"], block_until_unix=9e9)
    decision = block_decision(config, process_active=False, now_unix=10.0)
    assert decision.should_block is False
    assert decision.reasons == []


def test_block_decision_combines_activity_timer_and_timeblock():
    config = replace(
        DEFAULT_CONFIG,
        enabled=True,
        reward_mode=False,
        time_blocks=["00:00-23:59"],
        block_until_unix=200.0,
    )
    decision = block_decision(config, process_active=True, now_unix=100.0)
    assert decision.should_block is True
    assert decision.reasons == ["timer", "time_block", "activity"]


def test_block_decision_timer_only_when_activity_allows():
    config = replace(
        DEFAULT_CONFIG,
        enabled=True,
        reward_mode=False,
        time_blocks=[],
        block_until_unix=200.0,
    )
    decision = block_decision(config, process_active=False, now_unix=100.0)
    assert decision.should_block is True
    assert decision.reasons == ["timer"]
