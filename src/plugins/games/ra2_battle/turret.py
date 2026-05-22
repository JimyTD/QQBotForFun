"""炮塔转向（对齐 Turreted + AttackTurreted.FacingTolerance）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .geometry import cell_wangle, rotate_toward, wangle_delta

if TYPE_CHECKING:
    from .simulator import UnitInstance


DEFAULT_FACING_TOLERANCE = 512


def tick_turret(unit: UnitInstance, target_cell: tuple[int, int]) -> None:
    ts = unit.actor.turret_turn_speed
    if not ts or ts <= 0:
        return
    desired = cell_wangle(unit.cell, target_cell)
    unit.turret_facing = rotate_toward(unit.turret_facing, desired, ts)


def turret_can_fire(
    unit: UnitInstance, target_cell: tuple[int, int]
) -> bool:
    ts = unit.actor.turret_turn_speed
    if not ts or ts <= 0:
        return True
    tol = unit.actor.facing_tolerance or DEFAULT_FACING_TOLERANCE
    desired = cell_wangle(unit.cell, target_cell)
    return abs(wangle_delta(unit.turret_facing, desired)) <= tol
