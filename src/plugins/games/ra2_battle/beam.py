"""AreaBeam / LaserZap 持续伤害（对齐 OpenRA Projectiles 的 Duration + DamageInterval）。"""

from __future__ import annotations

from .repo import WarheadDef, WeaponDef

_BEAM_KINDS = frozenset({"AreaBeam", "LaserZap"})


def is_beam_weapon(weapon: WeaponDef) -> bool:
    return (
        weapon.projectile_kind in _BEAM_KINDS
        and weapon.beam_duration > 0
        and weapon.beam_damage_interval > 0
    )


def beam_damage_pulse_offsets(weapon: WeaponDef) -> tuple[int, ...]:
    """相对光束开始的伤害 tick 偏移（对齐 headTicks % DamageInterval == 0）。"""
    if not is_beam_weapon(weapon):
        return (0,)
    dur = weapon.beam_duration
    interval = weapon.beam_damage_interval
    return tuple(t for t in range(1, dur + 1) if t % interval == 0)


def warhead_hits_enemy(wh: WarheadDef) -> bool:
    """ValidStances 含 Ally 且不含 Enemy/Neutral 时跳过（如 SonicZap 友军弹头）。"""
    if not wh.valid_stances:
        return True
    st = set(wh.valid_stances)
    if st <= {"Ally"}:
        return False
    return bool(st & {"Enemy", "Neutral"})


def warhead_valid_against_types(wh: WarheadDef, target_types: set[str]) -> bool:
    if not wh.valid_targets:
        return True
    return bool(set(wh.valid_targets).intersection(target_types))
