"""C4 爆破（对齐 Demolition / Demolishable；斗蛐蛐扩展至相邻 Vehicle）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .constants import CELL_WDIST
from .targeting import effective_target_types

if TYPE_CHECKING:
    from .simulator import UnitInstance

# OpenRA 建筑带 C4；斗蛐蛐无建筑，允许对相邻载具贴 C4（原版 RA2 行为）
_BATTLE_C4_TARGETS = frozenset({"C4", "Vehicle", "Structure"})


def has_demolition(unit: UnitInstance) -> bool:
    return unit.actor.demolition


def demolish_target_types(unit: UnitInstance) -> bool:
    return bool(_BATTLE_C4_TARGETS.intersection(effective_target_types(unit)))


def cells_adjacent(a: tuple[int, int], b: tuple[int, int]) -> bool:
    if a == b:
        return True
    return abs(a[0] - b[0]) <= 1 and abs(a[1] - b[1]) <= 1


def demolition_in_range(attacker: UnitInstance, victim: UnitInstance) -> bool:
    if not cells_adjacent(attacker.cell, victim.cell):
        return False
    dx = abs(attacker.x - victim.x) * CELL_WDIST
    dy = abs(attacker.y - victim.y) * CELL_WDIST
    return int((dx * dx + dy * dy) ** 0.5) <= CELL_WDIST


def can_demolish_target(attacker: UnitInstance, victim: UnitInstance) -> bool:
    if not has_demolition(attacker) or not victim.alive:
        return False
    if attacker.side == victim.side:
        return False
    if not demolish_target_types(victim):
        return False
    return demolition_in_range(attacker, victim)


def could_demolish_target(attacker: UnitInstance, victim: UnitInstance) -> bool:
    """尚未贴脸，但目标类型可被 C4（用于索敌/移动）。"""
    if not has_demolition(attacker) or not victim.alive:
        return False
    if attacker.side == victim.side:
        return False
    return demolish_target_types(victim)
