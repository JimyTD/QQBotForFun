"""斗蛐蛐模式 Armament / 武器过滤（YR 单位降级规则）。"""

from __future__ import annotations

from .repo import ActorDef, ArmamentDef, WeaponDef

_WEAPON_DENY: dict[str, frozenset[str]] = {
    "disk": frozenset({"DiskDrain"}),
}

_WEAPON_ALLOW_ONLY: dict[str, frozenset[str]] = {
    "tele": frozenset({"MagneShake"}),
}

# yaml 仅对 Structure 有效；斗蛐蛐无建筑，扩展为可对地面单位
_WEAPON_VALID_OVERRIDE: dict[str, dict[str, tuple[str, ...]]] = {
    "tele": {
        "MagneShake": ("Ground", "Water", "Vehicle", "Structure"),
    },
}


def _battle_atom_active(
    atom: str,
    *,
    veterancy_level: int,
) -> bool:
    c = atom.strip()
    if c == "rank-elite":
        return veterancy_level >= 2
    if c == "rank-veteran":
        return veterancy_level >= 1
    if c == "!rank-elite":
        return veterancy_level < 2
    if c == "!rank-veteran":
        return veterancy_level < 1
    if c in ("deployed", "stage-2", "stage-3", "elite-stage-2", "elite-stage-3"):
        return False
    if c in ("!deployed", "stage-1", "elite-stage-1"):
        return True
    if c == "freed":
        return True
    if c.startswith("ifv-"):
        return False
    if c.startswith("stance-"):
        return False
    if c.startswith("!"):
        return True
    return False


def _eval_battle_condition(
    cond: str | None,
    *,
    veterancy_level: int,
) -> bool:
    if cond is None:
        return True
    c = str(cond).strip()
    if "&&" in c:
        return all(
            _eval_battle_condition(part.strip(), veterancy_level=veterancy_level)
            for part in c.split("&&")
        )
    return _battle_atom_active(c, veterancy_level=veterancy_level)


def armament_battle_allowed(
    arm: ArmamentDef,
    actor: ActorDef,
    *,
    veterancy_level: int = 0,
) -> bool:
    deny = _WEAPON_DENY.get(actor.id)
    if deny and arm.weapon in deny:
        return False
    allow = _WEAPON_ALLOW_ONLY.get(actor.id)
    if allow is not None and arm.weapon not in allow:
        return False
    return _eval_battle_condition(arm.requires_condition, veterancy_level=veterancy_level)


def weapon_battle_denied(actor_id: str, weapon_id: str) -> bool:
    deny = _WEAPON_DENY.get(actor_id)
    if deny and weapon_id in deny:
        return True
    allow = _WEAPON_ALLOW_ONLY.get(actor_id)
    return allow is not None and weapon_id not in allow


def battle_weapon_valid_targets(
    weapon: WeaponDef,
    actor_id: str,
) -> tuple[str, ...]:
    ov = _WEAPON_VALID_OVERRIDE.get(actor_id, {}).get(weapon.id)
    if ov:
        return ov
    return weapon.valid_targets
