"""Shared test helper: build attack-action lists for hand-made units.

The production simulator reads only ``Unit.attack_actions``. Tests historically
built units with the retired ranged/melee slot kwargs; this helper keeps those
call sites readable while producing a single attack-action list.
"""

from __future__ import annotations

from plugins.aoe3.attack_actions import AttackAction
from plugins.aoe3.models import Multiplier


def ranged_action(
    *,
    name: str = "TestRangedAttack",
    damage: float,
    range_min: float = 0.0,
    range_max: float,
    rof: float = 1.0,
    priority: int = 50,
    aoe_radius: float = 0.0,
    damage_cap: float = 0.0,
    windup: float = 0.0,
    num_projectiles: int = 1,
    damage_type: str = "Ranged",
    multipliers: tuple[Multiplier, ...] = (),
) -> AttackAction:
    return AttackAction(
        name=name,
        priority=priority,
        damage=damage,
        damage_type=damage_type,
        range_min=range_min,
        range_max=range_max,
        rof=rof,
        aoe_radius=aoe_radius,
        damage_cap=damage_cap,
        windup=windup,
        num_projectiles=num_projectiles,
        multipliers=multipliers,
        rangedlogic=True,
    )


def melee_action(
    *,
    name: str = "TestHandAttack",
    damage: float,
    range_max: float = 1.5,
    range_min: float = 0.0,
    rof: float = 1.0,
    priority: int = 100,
    windup: float = 0.0,
    multipliers: tuple[Multiplier, ...] = (),
) -> AttackAction:
    return AttackAction(
        name=name,
        priority=priority,
        damage=damage,
        damage_type="Hand",
        range_min=range_min,
        range_max=range_max,
        rof=rof,
        windup=windup,
        multipliers=multipliers,
        handlogic=True,
    )


def build_attack_actions(
    *,
    attack_melee: float = 0.0,
    attack_ranged: float = 0.0,
    range_: float = 0.0,
    range_min: float = 0.0,
    melee_range: float = 1.5,
    rof_melee: float = 1.0,
    rof_ranged: float = 1.0,
    windup_melee: float = 0.0,
    windup_ranged: float = 0.0,
    aoe_radius_ranged: float = 0.0,
    damage_cap_ranged: float = 0.0,
    multipliers_ranged: tuple[Multiplier, ...] = (),
) -> list[AttackAction]:
    actions: list[AttackAction] = []
    if attack_ranged > 0 and range_ > 0:
        actions.append(
            ranged_action(
                damage=attack_ranged,
                range_min=range_min,
                range_max=range_,
                rof=rof_ranged or 1.0,
                windup=windup_ranged,
                aoe_radius=aoe_radius_ranged,
                damage_cap=damage_cap_ranged,
                multipliers=multipliers_ranged,
            )
        )
    if attack_melee > 0:
        actions.append(
            melee_action(
                damage=attack_melee,
                range_max=melee_range,
                rof=rof_melee or 1.0,
                windup=windup_melee,
            )
        )
    return actions
