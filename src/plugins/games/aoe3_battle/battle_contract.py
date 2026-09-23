"""Stable battle result/event contract shared by the 2D engine and consumers.

This module intentionally contains no movement or combat implementation.  It
is the only production-side bridge between the simulator and the broadcast,
settlement, logging and analysis layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.plugins.aoe3.models import Unit


class EventType(str, Enum):
    BATTLE_START = "BATTLE_START"
    MOVE = "MOVE"
    ATTACK = "ATTACK"
    DEATH = "DEATH"
    TARGET_LOCK = "TARGET_LOCK"
    AOE_SPLASH = "AOE_SPLASH"
    BATTLE_END = "BATTLE_END"


class Side(str, Enum):
    RED = "red"
    BLUE = "blue"


@dataclass
class BattleEvent:
    """One structured battle event consumed by reports and diagnostics."""

    tick: int
    time: float
    event_type: EventType
    data: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"[{self.time:.1f}s] {self.event_type.value} {self.data}"


@dataclass
class ArmySlot:
    """One unit type and its starting count."""

    unit: Unit
    count: int


@dataclass
class BattleResult:
    """Shared result shape for both battle consumers and test doubles."""

    winner: Side | None
    events: list[BattleEvent]
    ticks: int
    duration: float
    red_alive: list[Any]
    blue_alive: list[Any]
    red_dead: list[Any]
    blue_dead: list[Any]
    red_army: list[ArmySlot]
    blue_army: list[ArmySlot]
    red_count: int
    blue_count: int
    timeout: bool = False

    @property
    def red_unit(self) -> Unit:
        return self.red_army[0].unit

    @property
    def blue_unit(self) -> Unit:
        return self.blue_army[0].unit
