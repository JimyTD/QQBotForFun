"""索敌逻辑（对齐 OpenRA AutoTargetPriority，斗蛐蛐默认 stance 非 attack-anything）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .repo import ActorDef, ArmamentDef, AutoTargetPriority, WeaponDef

if TYPE_CHECKING:
    from .simulator import UnitInstance

# OpenRA WeaponInfo 默认值（yaml 未写 ValidTargets 时）
_DEFAULT_WEAPON_VALID = frozenset({"Ground", "Water"})


def _eval_targetable_condition(cond: str | None, unit: UnitInstance) -> bool:
    if cond is None:
        return True
    c = str(cond).strip()
    if "&&" in c:
        return all(_eval_targetable_condition(p.strip(), unit) for p in c.split("&&"))
    if c == "airborne":
        return unit.airborne
    if c == "!airborne":
        return not unit.airborne
    if c == "damaged":
        return unit.hp < unit.max_hp
    if c == "underwater":
        return False
    if c == "!underwater":
        return True
    if c == "controlled":
        return unit.controlled_by_id is not None
    if c == "!controlled":
        return unit.controlled_by_id is None
    if c.startswith("!"):
        return True
    return False


def effective_target_types(unit: UnitInstance) -> set[str]:
    """按单位当前状态合并 Targetable 层（如 hornet 升空后为 Air）。"""
    layers = unit.actor.targetable_layers
    if not layers:
        return set(unit.actor.target_types)
    active: set[str] = set()
    for layer in layers:
        if _eval_targetable_condition(layer.requires_condition, unit):
            active.update(layer.types)
    if not active:
        return set(unit.actor.target_types)
    return active


def _priority_active(
    p: AutoTargetPriority,
    *,
    is_controlling: bool = False,
    veterancy_level: int = 0,
) -> bool:
    """斗蛐蛐默认 stance：启用 DEFAULT（!stance-attackanything），不用 ATTACKANYTHING。"""
    if p.requires_condition is None:
        return True
    if "ATTACKANYTHING" in p.id:
        return False
    if "DEFAULT" in p.id:
        return True
    cond = str(p.requires_condition).strip()
    if cond == "!controlling":
        return not is_controlling
    if cond == "controlling":
        return is_controlling
    if cond == "rank-elite":
        return veterancy_level >= 2
    if cond == "!rank-elite":
        return veterancy_level < 2
    if cond.startswith("!"):
        return True
    return False


def merged_valid_targets(actor: ActorDef, *, is_controlling: bool = False) -> set[str]:
    return set(merged_valid_targets_ordered(actor, is_controlling=is_controlling))


def merged_valid_targets_ordered(
    actor: ActorDef, *, is_controlling: bool = False
) -> tuple[str, ...]:
    """保持 yaml 中 ValidTargets 顺序（对齐 AutoTarget 扫描优先级）。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for p in actor.auto_target_priorities:
        if not _priority_active(p, is_controlling=is_controlling):
            continue
        for cat in p.valid_targets:
            if cat not in seen:
                seen.add(cat)
                ordered.append(cat)
    if not ordered:
        ordered = ["Infantry", "Vehicle", "Air"]
    return tuple(ordered)


def auto_target_type_rank(
    attacker: ActorDef,
    target: ActorDef,
    *,
    is_controlling: bool = False,
    target_unit: UnitInstance | None = None,
) -> int:
    """越小越优先锁定该目标类型。"""
    if target_unit is not None:
        tgt_cats = target_categories_from_types(effective_target_types(target_unit))
    else:
        tgt_cats = target_categories(target)
    for i, cat in enumerate(
        merged_valid_targets_ordered(attacker, is_controlling=is_controlling)
    ):
        if cat in tgt_cats:
            return i
    return 999


def merged_invalid_targets(actor: ActorDef, *, is_controlling: bool = False) -> set[str]:
    invalid: set[str] = set()
    for p in actor.auto_target_priorities:
        if _priority_active(p, is_controlling=is_controlling):
            invalid.update(p.invalid_targets)
    return invalid


def target_categories_from_types(types: set[str]) -> set[str]:
    """将 TargetTypes 映射到 AutoTarget 使用的类别。"""
    cats: set[str] = set()
    for t in types:
        if t in (
            "Infantry", "Vehicle", "Air", "Water", "Underwater",
            "Structure", "Defense", "NoAutoTarget", "MindControl",
        ):
            cats.add(t)
    if "Vehicle" in types or "Ground" in types:
        cats.add("Vehicle")
    if "Infantry" in types:
        cats.add("Infantry")
    if "Air" in types:
        cats.add("Air")
    return cats


def target_categories(actor: ActorDef) -> set[str]:
    return target_categories_from_types(set(actor.target_types))


def auto_target_sort_key(
    attacker: ActorDef,
    target: ActorDef,
    *,
    in_weapon_range: bool,
    distance: int,
    target_hp: int = 0,
    is_controlling: bool = False,
    target_unit: UnitInstance | None = None,
) -> tuple[int, int, int, int]:
    """(在射程, 类型优先级, 距离, 血量) — 用于锁敌。"""
    if target_unit is not None:
        tgt_cats = target_categories_from_types(effective_target_types(target_unit))
        rank = 999
        for i, cat in enumerate(
            merged_valid_targets_ordered(attacker, is_controlling=is_controlling)
        ):
            if cat in tgt_cats:
                rank = i
                break
    else:
        rank = auto_target_type_rank(attacker, target, is_controlling=is_controlling)
    return (
        0 if in_weapon_range else 1,
        rank,
        distance,
        target_hp,
    )


def can_auto_target(
    attacker: ActorDef,
    target: ActorDef,
    *,
    is_controlling: bool = False,
    target_unit: UnitInstance | None = None,
) -> bool:
    if "NoAutoTarget" in (
        effective_target_types(target_unit)
        if target_unit is not None
        else target.target_types
    ):
        return False
    valid = merged_valid_targets(attacker, is_controlling=is_controlling)
    invalid = merged_invalid_targets(attacker, is_controlling=is_controlling)
    if target_unit is not None:
        tgt_cats = target_categories_from_types(effective_target_types(target_unit))
    else:
        tgt_cats = target_categories(target)
    if not valid.intersection(tgt_cats):
        return False
    if invalid.intersection(tgt_cats):
        return False
    return True


def weapon_valid_against(weapon: WeaponDef, victim: ActorDef) -> bool:
    return weapon_valid_against_unit(weapon, victim, target_types=set(victim.target_types))


def weapon_valid_against_unit(
    weapon: WeaponDef,
    victim: ActorDef,
    *,
    target_types: set[str],
) -> bool:
    """对齐 OpenRA WeaponInfo.IsValidTarget。"""
    valid = (
        set(weapon.valid_targets)
        if weapon.valid_targets
        else set(_DEFAULT_WEAPON_VALID)
    )
    invalid = set(weapon.invalid_targets)
    if not valid.intersection(target_types):
        return False
    if invalid.intersection(target_types):
        return False
    return True


def armament_allowed(arm: ArmamentDef, *, veterancy_level: int = 0) -> bool:
    """对齐 Armament RequiresCondition 与 rank-veteran / rank-elite。"""
    cond = arm.requires_condition
    if cond is None:
        return True
    c = str(cond).strip()
    if c == "rank-elite":
        return veterancy_level >= 2
    if c == "!rank-elite":
        return veterancy_level < 2
    if c == "rank-veteran":
        return veterancy_level >= 1
    if c.startswith("!"):
        return True
    return True
