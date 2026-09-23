"""Compatibility re-exports for the shared 2D battle contract."""

from __future__ import annotations

from ..battle_contract import (
    ArmySlot,
    BattleEvent,
    BattleResult,
    EventType,
    Side,
)

__all__ = [
    "ArmySlot",
    "BattleEvent",
    "BattleResult",
    "EventType",
    "Side",
]
