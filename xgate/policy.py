from __future__ import annotations

from .config import GateConfig


def should_block(config: GateConfig, process_active: bool) -> bool:
    if not config.enabled:
        return False
    if config.reward_mode:
        return not process_active
    return process_active
