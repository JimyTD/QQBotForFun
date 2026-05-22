"""航母子机（对齐 CarrierParent / CarrierChild / Rearmable / Aircraft）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .constants import REARM_TICKS

if TYPE_CHECKING:
    from .simulator import BattleSimulator, UnitInstance


def spawn_children_for_carrier(sim: BattleSimulator, carrier: UnitInstance) -> None:
    cp = carrier.actor.carrier_parent
    if cp is None:
        return
    alive_children = sum(
        1
        for u in sim._units
        if u.alive and u.parent_carrier_id == carrier.id
    )
    if alive_children > 0:
        return
    count = len(cp.actors) if cp.spawn_all_at_once else 1
    offsets = [(1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (0, -1)]
    for i, child_id in enumerate(cp.actors[:count]):
        if child_id not in sim.actors:
            continue
        ox, oy = offsets[i % len(offsets)]
        cx = max(0, min(sim.width - 1, carrier.x + ox))
        cy = max(0, min(sim.height - 1, carrier.y + oy))
        sim._spawn_child(
            child_id,
            carrier.side,
            cx,
            cy,
            parent_id=carrier.id,
        )
    carrier.carrier_respawn_cooldown = cp.respawn_ticks


def tick_carrier_respawn(sim: BattleSimulator) -> None:
    for u in sim._alive():
        if u.actor.carrier_parent is None:
            continue
        cp = u.actor.carrier_parent
        if u.carrier_respawn_cooldown > 0:
            u.carrier_respawn_cooldown -= 1
            continue
        spawn_children_for_carrier(sim, u)


def init_carrier_children(sim: BattleSimulator) -> None:
    for u in sim._alive():
        if u.actor.carrier_parent is not None:
            spawn_children_for_carrier(sim, u)


def needs_rearm(unit: UnitInstance) -> bool:
    return (
        unit.ammo_left is not None
        and unit.ammo_left <= 0
        and len(unit.actor.rearmable_actors) > 0
        and unit.parent_carrier_id is not None
    )


def tick_aircraft_takeoff(unit: UnitInstance) -> None:
    from .simulator import BattleSimulator

    if not BattleSimulator._is_air_unit(unit):
        unit.airborne = False
        return
    if unit.actor.takeoff_ticks <= 0:
        unit.airborne = True
        return
    if unit.takeoff_ticks_left > 0:
        unit.takeoff_ticks_left -= 1
        if unit.takeoff_ticks_left <= 0:
            unit.airborne = True


def on_carrier_destroyed(sim: BattleSimulator, carrier: UnitInstance) -> None:
    """航母阵亡时击落其舰载机（避免无弹黄蜂与敌方耗到平局）。"""
    if carrier.actor.carrier_parent is None:
        return
    from .simulator import EventType

    for child in list(sim._units):
        if not child.alive or child.parent_carrier_id != carrier.id:
            continue
        child.alive = False
        child.hp = 0.0
        sim._emit(
            EventType.DEATH,
            {
                "unit_id": child.id,
                "actor_id": child.actor_id,
                "killer_id": carrier.id,
            },
        )


def tick_rearm(sim: BattleSimulator, unit: UnitInstance) -> None:
    if not needs_rearm(unit):
        unit.rearm_ticks_left = 0
        return
    parent = sim._by_id.get(unit.parent_carrier_id or -1)
    if parent is None or not parent.alive:
        unit.rearm_ticks_left = 0
        return
    if unit.cell != parent.cell:
        unit.target_id = parent.id
        unit.rearm_ticks_left = 0
        return
    if unit.rearm_ticks_left <= 0:
        unit.rearm_ticks_left = REARM_TICKS
    unit.rearm_ticks_left -= 1
    if unit.rearm_ticks_left <= 0 and unit.actor.ammo_max is not None:
        unit.ammo_left = unit.actor.ammo_max
        from .simulator import EventType

        sim._emit(
            EventType.REARM,
            {
                "unit_id": unit.id,
                "actor_id": unit.actor_id,
                "parent_id": parent.id,
                "ammo": unit.ammo_left,
            },
        )
