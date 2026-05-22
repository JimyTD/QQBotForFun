"""心控（对齐 MindController / MindControllable / MindControl 武器）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .repo import WeaponDef
from .targeting import effective_target_types

if TYPE_CHECKING:
    from .simulator import BattleSimulator, UnitInstance


def is_mind_control_weapon(weapon: WeaponDef) -> bool:
    return "MindControl" in weapon.valid_targets


def can_be_mind_controlled_unit(victim: UnitInstance) -> bool:
    if not victim.actor.mind_controllable:
        return False
    if victim.controlled_by_id is not None:
        return False
    return "MindControl" in effective_target_types(victim)


def controller_is_busy(controller: UnitInstance) -> bool:
    return controller.controls_unit_id is not None


def apply_mind_control(
    sim: BattleSimulator,
    controller: UnitInstance,
    victim: UnitInstance,
) -> bool:
    if not can_be_mind_controlled_unit(victim):
        return False
    if controller_is_busy(controller):
        return False
    if controller.side == victim.side:
        return False

    victim.original_side = victim.side
    victim.side = controller.side
    victim.controlled_by_id = controller.id
    victim.target_id = None
    controller.controls_unit_id = victim.id

    from .simulator import EventType

    sim._emit(
        EventType.MIND_CONTROL,
        {
            "controller_id": controller.id,
            "controller": controller.actor_id,
            "victim_id": victim.id,
            "victim": victim.actor_id,
            "new_side": victim.side.value,
        },
    )
    return True


def release_mind_control(sim: BattleSimulator, victim: UnitInstance) -> None:
    if victim.controlled_by_id is None:
        return
    controller = sim._by_id.get(victim.controlled_by_id)
    if controller is not None and controller.controls_unit_id == victim.id:
        controller.controls_unit_id = None
    if victim.original_side is not None:
        victim.side = victim.original_side
    victim.original_side = None
    victim.controlled_by_id = None
    victim.target_id = None

    from .simulator import EventType

    sim._emit(
        EventType.MIND_RELEASE,
        {"unit_id": victim.id, "actor_id": victim.actor_id},
    )


def on_unit_death(sim: BattleSimulator, unit: UnitInstance) -> None:
    from .carrier import on_carrier_destroyed

    on_carrier_destroyed(sim, unit)
    if unit.controls_unit_id is not None:
        slave = sim._by_id.get(unit.controls_unit_id)
        if slave is not None and slave.alive:
            release_mind_control(sim, slave)
    if unit.controlled_by_id is not None:
        release_mind_control(sim, unit)
