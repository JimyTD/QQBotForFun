"""2D area-of-effect resolution for AoE3 combat.

The resolver is intentionally independent from target acquisition and damage
application.  It filters candidates in world space, applies the configured
distance falloff, and spends the action damage cap from the impact point
outward.  The caller is responsible for armour, multipliers, and HP mutation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import Soldier2D
from .spatial import SpatialHash


@dataclass(frozen=True)
class AoeHit:
    """One target selected by the area resolver."""

    target: Soldier2D
    damage: float
    distance: float
    distance_factor: float


def distance_factor(
    distance: float,
    radius: float,
    outer_distance: float,
    outer_factor: float,
) -> float:
    """Return the AOE damage factor at a distance from the impact point.

    Missing outer parameters preserve the historical, fully uniform circle.
    When present, ``outer_distance`` is treated as the absolute distance at
    which the damage reaches ``outer_factor``.  The value stays clamped to
    that floor through the remaining radius.
    """
    if radius <= 0 or distance <= 0:
        return 1.0
    if outer_distance <= 0 or outer_factor <= 0:
        return 1.0
    if distance >= outer_distance:
        return max(0.0, outer_factor)
    ratio = distance / outer_distance
    return 1.0 - (1.0 - outer_factor) * ratio


def _is_directional_hit(
    attacker: Soldier2D,
    impact: Soldier2D,
    target: Soldier2D,
) -> bool:
    """Return whether target lies in the forward half-plane of the attack."""
    attack_dx = impact.x - attacker.x
    attack_dy = impact.y - attacker.y
    target_dx = target.x - impact.x
    target_dy = target.y - impact.y
    attack_len_sq = attack_dx * attack_dx + attack_dy * attack_dy
    target_len_sq = target_dx * target_dx + target_dy * target_dy
    if attack_len_sq <= 1e-12 or target_len_sq <= 1e-12:
        return True
    dot = attack_dx * target_dx + attack_dy * target_dy
    return dot >= 0.0


def resolve_aoe(
    *,
    attacker: Soldier2D,
    main_target: Soldier2D,
    radius: float,
    base_damage: float,
    damage_cap: float,
    area_sort_mode: str = "",
    outer_distance: float = 0.0,
    outer_factor: float = 0.0,
    spatial_hash: SpatialHash,
) -> list[AoeHit]:
    """Resolve secondary targets for one AOE attack.

    Candidates are sorted by distance from the impact point, then each target
    consumes the remaining raw damage cap.  The returned damage is before
    per-target multipliers and armour; the caller applies those exactly once.
    """
    if radius <= 0 or damage_cap <= 0:
        return []

    candidates = spatial_hash.query_circle(
        main_target.pos,
        radius,
        predicate=lambda other: (
            other.alive
            and other.id != main_target.id
            and other.side != attacker.side
        ),
    )

    directional = area_sort_mode.strip().lower() == "directional"
    ranked: list[tuple[float, Soldier2D]] = []
    for target in candidates:
        distance = math.hypot(
            target.x - main_target.x,
            target.y - main_target.y,
        )
        if distance > radius:
            continue
        if directional and not _is_directional_hit(attacker, main_target, target):
            continue
        ranked.append((distance, target))

    ranked.sort(key=lambda item: (item[0], item[1].id))
    remaining = max(0.0, damage_cap)
    result: list[AoeHit] = []
    for distance, target in ranked:
        if remaining <= 0.0:
            break
        factor = distance_factor(
            distance,
            radius,
            outer_distance,
            outer_factor,
        )
        raw_damage = base_damage * factor
        if raw_damage <= 0.0:
            continue
        allocated = min(raw_damage, remaining)
        remaining -= allocated
        result.append(
            AoeHit(
                target=target,
                damage=allocated,
                distance=distance,
                distance_factor=factor,
            )
        )
    return result


def filter_directional(
    attacker: Soldier2D,
    impact: Soldier2D,
    target: Soldier2D,
) -> bool:
    """Public helper retained for tests and callers that need the predicate."""
    return _is_directional_hit(attacker, impact, target)
