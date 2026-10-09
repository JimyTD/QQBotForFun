"""Player-facing summaries for selected civ-war technologies."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from src.plugins.aoe3.i18n import t

_RESOURCE_NAMES = {
    "food": "食物",
    "wood": "木材",
    "gold": "金币",
    "influence": "影响力",
}

_ACTION_NAMES = {
    "VolleyRangedAttack": "远程攻击",
    "RangedAttack": "远程攻击",
    "DefendRangedAttack": "远程攻击",
    "StaggerRangedAttack": "远程攻击",
    "RepeatingRangedAttack": "远程攻击",
    "GuardianRangedAttack": "远程攻击",
    "BowAttack": "远程攻击",
    "CannonAttack": "火炮攻击",
    "FlameAttack": "火焰攻击",
    "BuildingAttack": "建筑攻击",
    "CoverBuildingAttack": "建筑攻击",
    "MortarAttack": "建筑攻击",
    "MortarBuildingAttack": "建筑攻击",
    "BombardAttack": "轰击",
    "CaseShotAttack": "葡萄弹攻击",
    "MeleeHandAttack": "近战攻击",
    "HandAttack": "近战攻击",
    "VolleyHandAttack": "近战攻击",
    "DefendHandAttack": "近战攻击",
    "StaggerHandAttack": "近战攻击",
    "CoverHandAttack": "近战攻击",
    "GuardianAttack": "近战攻击",
    "LanceChargeAttack": "冲锋攻击",
    "ChargeAttack": "冲锋攻击",
    "TrampleHandAttack": "践踏攻击",
    "BullseyeChargeAttack": "精准冲锋",
    "ChargeCarbineAttack": "冲锋射击",
    "ChargePistolAttack": "冲锋手枪",
    "LockRangedAttack": "锁弓远程",
    "RangedBuildingAttack": "远程建筑攻击",
    "DefendBuildingAttack": "防御建筑攻击",
    "RangedDefendBuildingAttack": "远程防御建筑攻击",
    "AntiShipAttack": "对舰攻击",
    "BarrageAttack": "弹幕攻击",
    "BuckshotChargeAttack": "霰弹冲锋",
    "ChargeBroadsideAttack": "冲锋舷射",
    "ChargeHeavyStrikeAttack": "重型冲锋",
    "ChargeMusketAttack": "冲锋射击",
    "ChargeQuickDrawAttack": "快速拔枪",
    "ChargeShootoutAttack": "枪战冲锋",
    "CoverMortarBuildingAttack": "掩护臼炮建筑攻击",
    "DynamiteAttackCharge": "炸药冲锋",
    "EagleEyeChargeAttack": "鹰眼冲锋",
    "FlameThrowerAttack": "喷火攻击",
    "GrenadeAttack": "手雷攻击",
    "GrenadeAttackLong": "远程手雷",
    "GrenadeAttackShort": "近程手雷",
    "LassoAttackCharge": "套索冲锋",
    "LongRangeAttack": "远距攻击",
    "LongRangedAttack": "远距攻击",
    "MusketAttack": "火枪攻击",
    "ObsidianChargeAttack": "黑曜石冲锋",
    "RangedAttack2": "远程攻击二式",
    "RepeatingAttack": "连发攻击",
    "RangedShipAttack": "对舰远程攻击",
    "DefendRangedShipAttack": "防御对舰远程攻击",
    "RifleAttack": "步枪攻击",
    "RocketAttack": "火箭攻击",
    "RocketBuildingAttack": "火箭建筑攻击",
    "RomanTactics1": "罗马战术一式",
    "SpearAttack": "长矛攻击",
    "StampedeAttack": "奔踏攻击",
    "VolleyAttack": "齐射攻击",
    "VolleyLongRangedAttack": "远距齐射",
}

_ATTACK_ACTIONS = frozenset(_ACTION_NAMES)

_ABILITY_NAMES = {
    "Stealth": "潜行",
    "Discover": "侦查",
    "Build": "建造",
    "Gather": "采集",
    "AutoGatherFood": "自动采集食物",
    "AutoGatherFoodSmall": "自动采集食物",
    "AutoGatherFoodSmaller": "自动采集食物",
    "AutoGatherWood": "自动采集木材",
    "AutoGatherWoodSmall": "自动采集木材",
    "AutoGatherWoodSmaller": "自动采集木材",
    "AutoGatherCoin": "自动采集金币",
    "AutoGatherCoinSmall": "自动采集金币",
    "AutoGatherCoinSmaller": "自动采集金币",
    "CrateGather": "收集资源箱",
    "Spawn": "召唤",
    "SpawnCannon": "产生火炮",
    "SpawnRocket": "产生火箭",
    "SpawnBombard": "产生臼炮",
}

_IGNORED_ABILITY_ACTIONS = frozenset(
    {
        "IncreaseHPWithFortifications",
        "IncreaseHPWithFortificationsIncludesEnemies",
        "IncreaseDamageWithFortifications",
        "IncreaseDamageWithFortificationsIncludesEnemies",
        "IncreaseHPWithBuildings",
        "IncreaseHPWithBuildingsIncludesEnemies",
        "IncreaseDamageWithBuildings",
        "IncreaseDamageWithBuildingsIncludesEnemies",
        "IncreaseSpeedWithBuildings",
        "IncreaseSpeedWithBuildingsIncludesEnemies",
        "IncreaseHPWithResources",
        "IncreaseHPWithResources2",
        "IncreaseDamageWithWalls",
        "IncreaseRangeWithWalls",
        "IncreaseHPWithUnits",
    }
)

_ATTACK_SCOPED_SUBTYPES = {
    "Damage",
    "DamageForAllHandLogicActions",
    "DamageBonus",
    "DamageArea",
    "MaximumRange",
    "MinimumRange",
    "RateOfFire",
    "RechargeTime",
}

_ALL_ATTACKS = "__all_attacks__"
_ALL_CHARGES = "__all_charges__"
_HAND_ATTACKS = "__hand_attacks__"
_MAX_EFFECTS = 6
_MAX_RECIPIENTS = 3


def _percent(value: float) -> str:
    pct = round((value - 1.0) * 100)
    return f"{pct:+d}%"


def _signed(value: float) -> str:
    return f"{value:+g}"


def _velocity_text(value: float, relation: str) -> str:
    if relation == "BasePercent":
        return f"移速{_percent(value)}"
    if relation == "Absolute":
        return f"移速{_signed(value)}"
    if relation == "Assign":
        return f"移速改为 {value:g}"
    return ""


def _rof_text(value: float, relation: str) -> str:
    if relation == "BasePercent":
        return f"攻击间隔{_percent(value)}"
    if relation == "Absolute":
        return f"攻击间隔{_signed(value)}秒"
    if relation == "Assign":
        return f"攻击间隔改为 {value:g} 秒"
    return ""


def _stat_text(label: str, value: float, relation: str, *, unit: str = "") -> str:
    if relation == "BasePercent":
        return f"{label}{_percent(value)}{unit}"
    if relation == "Percent":
        return f"{label}{_percent(value)}{unit}"
    if relation == "Assign":
        return f"{label}改为 {value:g}{unit}"
    if relation == "Override":
        return f"{label}改为 {value:g}{unit}"
    if relation == "Absolute":
        return f"{label}{_signed(value)}{unit}"
    return f"{label}{_signed(value)}{unit}"


def _action_label(action: object) -> str:
    name = str(action or "")
    return (
        _ACTION_NAMES.get(name)
        or _ABILITY_NAMES.get(name)
        or name
        or "动作"
    )


def describe_action_enable(action: object, amount: float) -> str:
    """Render one ActionEnable effect for both bot text and the viewer."""
    name = str(action or "")
    if name in _IGNORED_ABILITY_ACTIONS:
        return ""
    verb = "开启" if amount != 0 else "关闭"
    if not name:
        return verb
    if name in _ATTACK_ACTIONS:
        return f"{verb}攻击：{_action_label(name)}"
    return f"{verb}能力：{_action_label(name)}"


def _attack_scope(op: Mapping[str, Any]) -> str | None:
    subtype = str(op.get("subtype") or "")
    if subtype not in _ATTACK_SCOPED_SUBTYPES:
        return None
    if subtype == "DamageForAllHandLogicActions":
        return _HAND_ATTACKS
    action = str(op.get("action") or "")
    if action:
        return action
    if subtype == "RechargeTime":
        return _ALL_CHARGES
    return _ALL_ATTACKS


def _scope_prefix(scope: str | None) -> str:
    if scope is None or scope == _ALL_CHARGES:
        return ""
    if scope == _ALL_ATTACKS:
        return "全部攻击："
    if scope == _HAND_ATTACKS:
        return "全部近战攻击："
    return f"{_action_label(scope)}："


def _resource_name(resource: object) -> str:
    key = str(resource or "").lower()
    return _RESOURCE_NAMES.get(key, str(resource or "资源"))


def _type_name(value: object) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    translated = t("tags", raw)
    if translated != raw:
        return translated
    return raw.replace("Abstract", "")


def _target_summary(op: Mapping[str, Any]) -> str:
    unittype = str(op.get("unittype") or "")
    if unittype:
        translated = _type_name(unittype)
        if translated:
            return translated
    targets = op.get("targets") or ()
    values = [
        str(target.get("value") or "")
        for target in targets
        if isinstance(target, Mapping)
        and target.get("type") == "ProtoUnit"
        and target.get("value")
    ]
    if len(values) == 1:
        return values[0]
    return ""


def _describe_op(op: Mapping[str, Any]) -> str:
    subtype = str(op.get("subtype") or "")
    amount = op.get("amount")
    if amount is None:
        return ""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return ""

    if subtype in {"Hitpoints", "HitPoints"}:
        return _stat_text("生命", value, str(op.get("relativity") or ""))
    if subtype == "Damage":
        return _stat_text("伤害", value, str(op.get("relativity") or ""))
    if subtype == "DamageForAllHandLogicActions":
        return _stat_text("伤害", value, str(op.get("relativity") or ""))
    if subtype == "DamageBonus":
        target = _target_summary(op)
        return (
            f"对{target}伤害倍率{_signed(value)}"
            if target
            else f"伤害倍率{_signed(value)}"
        )
    if subtype == "DamageArea":
        return f"溅射范围{_signed(value)}"
    if subtype == "MaximumRange":
        return f"射程{_signed(value)}"
    if subtype == "MinimumRange":
        return f"最小射程{_signed(value)}"
    if subtype == "RateOfFire":
        return _rof_text(value, str(op.get("relativity") or ""))
    if subtype == "MaximumVelocity":
        return _velocity_text(value, str(op.get("relativity") or ""))
    if subtype in {"Armor", "ArmorSpecific"}:
        armor_type = str(op.get("newtype") or "")
        armor = {
            "Hand": "近战",
            "Melee": "近战",
            "Ranged": "远程",
            "Siege": "攻城",
        }.get(armor_type)
        if armor is None:
            return ""
        return f"{armor}护甲{_signed(value)}"
    if subtype == "Cost":
        return _stat_text(
            f"{_resource_name(op.get('resource'))}造价",
            value,
            str(op.get("relativity") or ""),
        )
    if subtype == "InitialTactic":
        return "切换攻击方式"
    if subtype == "ActionEnable":
        return describe_action_enable(op.get("action"), value)
    if subtype == "RechargeTime":
        relation = str(op.get("relativity") or "")
        if relation == "BasePercent":
            return f"蓄力冷却{_percent(value)}"
        if relation == "Absolute":
            return f"蓄力冷却{_signed(value)}秒"
        if relation == "Assign":
            return f"蓄力冷却改为 {value:g} 秒"
    return ""


def _unique(parts: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            result.append(part)
    return tuple(result)


def _format_effects(ops: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    rendered: list[tuple[str | None, str]] = []
    for op in ops:
        part = _describe_op(op)
        if not part:
            continue
        scope = _attack_scope(op)
        rendered.append((scope, part))

    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for scope, part in rendered:
        prefix = _scope_prefix(scope)
        if prefix not in grouped:
            grouped[prefix] = []
            order.append(prefix)
        grouped[prefix].append(part)

    total = sum(len(_unique(grouped[prefix])) for prefix in order)
    output: list[str] = []
    visible = 0
    for prefix in order:
        effects = _unique(grouped[prefix])
        remaining = _MAX_EFFECTS - visible
        if remaining <= 0:
            break
        shown = effects[:remaining]
        separator = "、" if prefix else "，"
        output.append(prefix + separator.join(shown))
        visible += len(shown)
    if total > _MAX_EFFECTS:
        output.append(f"等 {total} 项")
    return tuple(output)


def format_tech_summary(
    name: str,
    *,
    combat_ops: Iterable[Mapping[str, Any]] = (),
    cost_ops: Iterable[Mapping[str, Any]] = (),
    recipients: Iterable[str] = (),
) -> str:
    """Return ``【units】name: effects``, or only the name when no wording exists."""
    effects = _format_effects((*tuple(combat_ops), *tuple(cost_ops)))
    body = f"{name}：{'，'.join(effects)}" if effects else name
    return _with_recipients(body, recipients)


def format_runtime_tech_summary(tech: Mapping[str, Any]) -> str:
    """Render one already-translated runtime tech payload."""
    ops = [
        _runtime_mapping(op)
        for op in tech.get("ops") or ()
        if isinstance(op, Mapping)
    ]
    return format_tech_summary(
        str(tech.get("name_zh") or tech.get("id") or ""),
        combat_ops=ops,
    )


def format_grouped_tech_summary(
    name: str,
    per_unit: Iterable[
        tuple[str, Iterable[Mapping[str, Any]], Iterable[Mapping[str, Any]]]
    ],
) -> str:
    """Summarize a tech by the effects each unit actually receives.

    ``per_unit`` is ``(unit name, combat ops, cost ops)`` with only the ops
    that target that unit. Units that receive the same effects share one
    group. One group renders as ``【units】name：effects``; several render as
    ``name：【units】effects；【units】effects``.
    """
    groups: list[tuple[frozenset[str], list[str], tuple[str, ...]]] = []
    for unit_name, combat_ops, cost_ops in per_unit:
        effects = _format_effects((*tuple(combat_ops), *tuple(cost_ops)))
        key = frozenset(effects)
        for group_key, names, _effects in groups:
            if group_key == key:
                names.append(str(unit_name))
                break
        else:
            groups.append((key, [str(unit_name)], effects))
    if len(groups) <= 1:
        names = groups[0][1] if groups else []
        effects = groups[0][2] if groups else ()
        body = f"{name}：{'，'.join(effects)}" if effects else name
        return _with_recipients(body, names)
    parts = [
        _with_recipients("，".join(effects), names)
        for _key, names, effects in groups
        if effects
    ]
    if not parts:
        return name
    return f"{name}：{'；'.join(parts)}"


def _with_recipients(body: str, recipients: Iterable[str]) -> str:
    names = _unique(str(unit) for unit in recipients)
    if not names:
        return body
    if len(names) > _MAX_RECIPIENTS:
        head = "、".join(names[:_MAX_RECIPIENTS])
        return f"【{head} 等 {len(names)} 个兵种】{body}"
    return f"【{'、'.join(names)}】{body}"


def _runtime_mapping(op: Mapping[str, Any]) -> Mapping[str, Any]:
    """Translate runtime field names back to the player-facing op schema."""
    stat = str(op.get("stat") or "")
    subtype = {
        "hp": "Hitpoints",
        "damage": "Damage",
        "hand_damage": "DamageForAllHandLogicActions",
        "aoe": "DamageArea",
        "rof": "RateOfFire",
        "speed": "MaximumVelocity",
        "armor": "ArmorSpecific",
        "cost": "Cost",
        "mult": "DamageBonus",
        "initial_tactic": "InitialTactic",
        "action_enable": "ActionEnable",
        "recharge": "RechargeTime",
    }.get(stat, str(op.get("subtype") or ""))
    if stat == "range":
        subtype = str(op.get("subtype") or "MaximumRange")
    relation = {
        "mult": "BasePercent",
        "add": "Absolute",
        "set": "Assign",
        "percent": "Percent",
    }.get(str(op.get("kind") or ""), str(op.get("relativity") or ""))
    result: dict[str, Any] = {
        "subtype": subtype,
        "amount": op.get("value"),
        "relativity": relation,
    }
    for key in ("action", "allactions", "resource", "vs", "tactic"):
        if op.get(key):
            result[key] = op[key]
    if op.get("armor_kind"):
        result["newtype"] = {
            "melee": "Hand",
            "ranged": "Ranged",
            "siege": "Siege",
        }.get(str(op["armor_kind"]), "")
    if op.get("vs"):
        result["unittype"] = op["vs"]
    return result
