"""弹道与 BlocksProjectiles 拦截（对齐 OpenRA Bullet/Missile + BlocksProjectiles）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .geometry import iter_line_cells
from .repo import WeaponDef

if TYPE_CHECKING:
    from .simulator import BattleSimulator, PendingHit, Side, UnitInstance

_DEFAULT_BLOCK_RELATIONSHIPS = frozenset({"Enemy", "Neutral", "Ally"})


def _relationship_allows_block(
    attacker_side: Side,
    blocker_side: Side,
    relationships: frozenset[str] | set[str],
) -> bool:
    if attacker_side == blocker_side:
        return "Ally" in relationships
    return "Enemy" in relationships


def _blocker_on_cell(
    sim: BattleSimulator,
    attacker: UnitInstance,
    cell: tuple[int, int],
) -> UnitInstance | None:
    for u in sim._cell_occupants(cell):
        if u.id == attacker.id or not u.alive:
            continue
        if u.actor.carrier_child:
            continue
        if not u.actor.blocks_projectiles:
            continue
        rels = u.actor.blocks_projectiles_relationships or _DEFAULT_BLOCK_RELATIONSHIPS
        if not _relationship_allows_block(attacker.side, u.side, rels):
            continue
        if u.actor.blocks_projectiles_height <= 0:
            continue
        return u
    return None


def find_projectile_blocker_between(
    sim: BattleSimulator,
    attacker: UnitInstance,
    from_cell: tuple[int, int],
    to_cell: tuple[int, int],
    weapon: WeaponDef,
) -> UnitInstance | None:
    """线段中点格上是否存在启用 BlocksProjectiles 的单位。"""
    if not weapon.projectile_blockable:
        return None
    if from_cell == to_cell:
        return None
    line = iter_line_cells(from_cell, to_cell)
    for cell in line[1:-1]:
        blocker = _blocker_on_cell(sim, attacker, cell)
        if blocker is not None:
            return blocker
    return None


def projectile_blocked(
    sim: BattleSimulator,
    attacker: UnitInstance,
    victim: UnitInstance,
    weapon: WeaponDef,
) -> bool:
    return (
        find_projectile_blocker_between(
            sim, attacker, attacker.cell, victim.cell, weapon
        )
        is not None
    )


def check_inflight_intercept(
    sim: BattleSimulator,
    hit: PendingHit,
) -> UnitInstance | None:
    """飞行中每 tick 检查：源格 → 目标当前格 是否被 BlocksProjectiles 截断。"""
    attacker = sim._by_id.get(hit.attacker_id)
    victim = sim._by_id.get(hit.victim_id)
    if attacker is None or victim is None or not attacker.alive or not victim.alive:
        return None
    from .repo import resolve_weapon

    weapon = resolve_weapon(hit.weapon_id)
    if weapon is None or not weapon.projectile_blockable:
        return None
    from_cell = (hit.src_x, hit.src_y)
    return find_projectile_blocker_between(
        sim, attacker, from_cell, victim.cell, weapon
    )
