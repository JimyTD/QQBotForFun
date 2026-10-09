"""AoE3 科技效果结算。

一份科技由若干效果（op）组成。结算规则（docs/wip/aoe3-tech-effects.md）：

- 每一条 op 只打 ``targets`` 写明的兵；写了攻击名只改同名攻击，``allactions``
  或没写攻击名改全部攻击。
- 同一科技只生效一次（由调用方保证科技列表去重）。
- 打到同一个量上的多条 op 按统一算符合并，没有“取大”：
  ``mult``（BasePercent）各项增量相加后乘基础值；``percent`` 累乘；
  ``add``（Absolute）相加；``set``（Assign）覆盖，后写的覆盖先写的。
  合并顺序：先 set，再 mult 增量，再 percent，最后 add。
"""
from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .attack_actions import AttackAction
from .models import Multiplier, Unit

# ------------------------------------------------------------------
# 作用对象
# ------------------------------------------------------------------

def unit_target_values(op: Mapping) -> tuple[str, ...]:
    """这条效果写明的兵种 id 或兵种标签。非兵种目标（科技、玩家）不算。"""
    return tuple(
        str(target.get("value") or "")
        for target in op.get("targets") or ()
        if isinstance(target, Mapping)
        and target.get("type") == "ProtoUnit"
        and target.get("value")
    )


def target_hits_unit(target: str, unit: Unit) -> bool:
    """兵种 id 不分大小写精确相等，或兵种标签精确相等。"""
    return target.lower() == unit.id.lower() or target in unit.type


def op_targets_unit(op: Mapping, unit: Unit) -> bool:
    """这一条效果打不打得到这个兵。没写兵种的效果谁都不打。"""
    return any(target_hits_unit(target, unit) for target in unit_target_values(op))


def ops_for_unit(ops: Iterable[Mapping], unit: Unit) -> list:
    return [op for op in ops if op_targets_unit(op, unit)]


# ------------------------------------------------------------------
# 统一算符
# ------------------------------------------------------------------

@dataclass
class Stack:
    """打到同一个量上的全部 op，按统一算符合并。"""

    set_value: float | None = None
    base_inc: float = 0.0
    percent: float = 1.0
    add: float = 0.0
    touched: bool = False
    ops: list = field(default_factory=list)

    def push(self, kind: str, value: float) -> None:
        self.touched = True
        if kind == "set":
            self.set_value = value
        elif kind == "mult":
            self.base_inc += value - 1.0
        elif kind == "percent":
            self.percent *= value
        elif kind == "add":
            self.add += value

    def resolve(self, base: float, current: float) -> float:
        """base：原始基础值（BasePercent 的基准）；current：本次结算前的值。"""
        if not self.touched:
            return current
        start = current if self.set_value is None else self.set_value
        origin = base if self.set_value is None else self.set_value
        return (start + origin * self.base_inc) * self.percent + self.add


# ------------------------------------------------------------------
# 游戏效果 → 运行时效果
# ------------------------------------------------------------------

# 游戏 relativity → 统一算符。所有数值效果共用这一张表。
RELATIVITY_KIND = {
    "BasePercent": "mult",
    "Percent": "percent",
    "Absolute": "add",
    "Assign": "set",
    "Override": "set",
}

# 游戏 subtype → (运行时 stat, 攻击范围)。攻击范围 None 表示按 op 自己的 action。
_NUMERIC_SUBTYPES: dict[str, tuple[str, str | None]] = {
    "Hitpoints": ("hp", None),
    "HitPoints": ("hp", None),
    "Damage": ("damage", None),
    "DamageForAllHandLogicActions": ("damage", "hand"),
    "DamageForAllRangedLogicActions": ("damage", "ranged"),
    "DamageCap": ("cap", None),
    "DamageBonus": ("mult", None),
    "DamageArea": ("aoe", None),
    "MaximumRange": ("range_max", None),
    "MinimumRange": ("range_min", None),
    "RangeForAllRangedLogicActions": ("range_max", "ranged"),
    "RateOfFire": ("rof", None),
    "MaximumVelocity": ("speed", None),
    "ArmorSpecific": ("armor", None),
    "Armor": ("armor", None),
    "Cost": ("cost", None),
    "RechargeTime": ("recharge", None),
}

# 护甲按伤害类型。``Armor`` 没写类型时三种都加。
_ARMOR_KINDS = {"Hand": "melee", "Melee": "melee", "Ranged": "ranged", "Siege": "siege"}


def runtime_op(op: Mapping) -> dict | None:
    """把科技池里的一条游戏效果换成运行时效果；结算不了的返回 None。"""
    subtype = str(op.get("subtype") or "")
    amount = op.get("amount")
    if amount is None:
        return None
    result: dict = {
        "subtype": subtype,
        "value": float(amount),
        "targets": list(op.get("targets") or ()),
    }
    for key in ("action", "allactions", "tactic"):
        if op.get(key):
            result[key] = op[key]
    if subtype == "ActionEnable":
        if not op.get("action"):
            return None
        result.update(stat="action_enable", kind="set")
        return result
    if subtype == "InitialTactic":
        if not op.get("tactic"):
            return None
        result.update(stat="initial_tactic", kind="set")
        return result
    mapped = _NUMERIC_SUBTYPES.get(subtype)
    kind = RELATIVITY_KIND.get(str(op.get("relativity") or ""))
    if mapped is None or kind is None:
        return None
    stat, scope = mapped
    result.update(stat=stat, kind=kind)
    if scope:
        result["attack_scope"] = scope
    if stat == "armor":
        if subtype == "Armor" and not op.get("newtype"):
            result["armor_kind"] = "all"
        else:
            armor_kind = _ARMOR_KINDS.get(str(op.get("newtype") or ""))
            if armor_kind is None:
                return None
            result["armor_kind"] = armor_kind
    elif stat == "cost":
        resource = str(op.get("resource") or "").lower()
        if not resource:
            return None
        result["resource"] = resource
    elif stat == "mult":
        vs = str(op.get("unittype") or "")
        if not vs:
            return None
        result["vs"] = vs
    return result


def unapplied_effect_key(op: Mapping) -> tuple[str, str, str] | None:
    """结算不了时返回 ``(subtype, relativity, newtype)``，能结算返回 None。"""
    if runtime_op(op) is not None:
        return None
    subtype = str(op.get("subtype") or "")
    newtype = str(op.get("newtype") or "") if subtype in {"Armor", "ArmorSpecific"} else ""
    return (subtype, str(op.get("relativity") or ""), newtype)


# 结算不了的效果，逐项列明，防止静默丢弃。新出现未列明的效果测试失败。
# 每一项是做还是移出可选名单，由 Owner 决定（docs/wip/aoe3-tech-effects.md）。
UNAPPLIED_EFFECTS: frozenset[tuple[str, str, str]] = frozenset({
    ("ActionAdd", "Absolute", ""),
    ("ActionAddAttachingUnit", "Absolute", ""),
    ("AddContainedBonusType", "Assign", ""),
    ("AddContainedType", "Assign", ""),
    ("ArmorType", "Absolute", ""),
    ("AttackPriority", "Absolute", ""),
    ("AutoAttackType", "Absolute", ""),
    ("ContainedHitpointBonus", "Assign", ""),
    ("ConversionDelay", "Absolute", ""),
    ("ConversionResistance", "Percent", ""),
    ("DamageMultiplier", "Assign", ""),
    ("DodgeChance", "Assign", ""),
    ("EnableDodge", "Assign", ""),
    ("GarrisonBonusDamage", "Assign", ""),
    ("HitPercent", "Absolute", ""),
    ("HitPercent", "Assign", ""),
    ("HitPercent", "BasePercent", ""),
    ("HitPercent", "Percent", ""),
    ("HitPercentType", "Absolute", ""),
    ("ProtoActionAdd", "Assign", ""),
    ("SelfDamageMultiplier", "Assign", ""),
    ("SetActionFlag", "Absolute", ""),
    ("SetProjectile", "Absolute", ""),
    ("SetTacticDataOverride", "Assign", ""),
    ("SetUnitType", "Assign", ""),
    ("Snare", "Assign", ""),
    ("SpeedModifier", "Absolute", ""),
    ("SpeedModifier", "Assign", ""),
    ("SpeedModifier", "BasePercent", ""),
    ("TacticArmor", "Absolute", ""),
    ("TacticEnable", "Absolute", ""),
    ("TacticEnable", "Assign", ""),
    ("UnitRegenAbsolute", "Assign", ""),
    ("UnitRegenIgnoreOnStealth", "Absolute", ""),
    ("UnitRegenRate", "Absolute", ""),
    ("UnitRegenRate", "Assign", ""),
    ("UnitRegenRate", "Percent", ""),
    ("UnitRegenRateLimit", "Absolute", ""),
    ("VeterancyBonus", "Assign", ""),
    ("VeterancyEnable", "Absolute", ""),
})


# ------------------------------------------------------------------
# 结算到一个兵
# ------------------------------------------------------------------

_ROF_FLOOR = 0.1
_ARMOR_FIELDS = {"melee": "armor_melee", "ranged": "armor_ranged", "siege": "armor_siege"}
_ACTION_STATS = {"damage", "cap", "mult", "aoe", "range_max", "range_min", "rof", "recharge"}


def _op_action_names(op: Mapping, actions: Sequence[AttackAction]) -> list[str]:
    """这条 op 落到的攻击名。"""
    scope = op.get("attack_scope")
    if scope == "hand":
        return [a.name for a in actions if a.handlogic]
    if scope == "ranged":
        return [a.name for a in actions if a.rangedlogic]
    if op.get("allactions") or not op.get("action"):
        return [a.name for a in actions]
    name = str(op["action"])
    return [a.name for a in actions if a.name == name]


def _switch_actions(unit: Unit, base: Unit, ops: Sequence[Mapping]) -> tuple[list, list]:
    """先换阵型，再开关攻击。返回（当前攻击列表，对应的基础攻击列表）。"""
    current = list(unit.attack_actions)
    origin = list(base.attack_actions)
    for op in ops:
        if op["stat"] != "initial_tactic":
            continue
        tactic = str(op.get("tactic") or "")
        if tactic in unit.attack_actions_by_tactic:
            current = list(unit.attack_actions_by_tactic[tactic])
            origin = list(base.attack_actions_by_tactic.get(tactic, current))
    for op in ops:
        if op["stat"] != "action_enable":
            continue
        enabled = float(op["value"]) != 0.0
        for name in _op_action_names(op, current):
            current = [
                dataclasses.replace(a, enabled=enabled) if a.name == name else a
                for a in current
            ]
    return current, origin


def _settle_action(action: AttackAction, origin: AttackAction, stacks: dict) -> AttackAction:
    changes: dict = {}
    damage = stacks.get("damage")
    if damage:
        changes["damage"] = round(max(0.0, damage.resolve(origin.damage, action.damage)), 2)
        # 伤害倍率同时放大溅射池（basedamagecap）。
        if origin.damage_cap and damage.base_inc:
            changes["damage_cap"] = round(
                action.damage_cap + origin.damage_cap * damage.base_inc, 2,
            )
    cap = stacks.get("cap")
    if cap:
        current_cap = changes.get("damage_cap", action.damage_cap)
        changes["damage_cap"] = round(max(0.0, cap.resolve(origin.damage_cap, current_cap)), 2)
    for stat, attr in (("aoe", "aoe_radius"), ("range_min", "range_min")):
        stack = stacks.get(stat)
        if stack:
            changes[attr] = round(max(0.0, stack.resolve(getattr(origin, attr), getattr(action, attr))), 2)
    range_max = stacks.get("range_max")
    if range_max and action.range_max > 0:
        changes["range_max"] = round(max(0.0, range_max.resolve(origin.range_max, action.range_max)), 2)
    rof = stacks.get("rof")
    if rof and (action.rof > 0 or rof.set_value is not None):
        changes["rof"] = round(max(_ROF_FLOOR, rof.resolve(origin.rof, action.rof)), 3)
    recharge = stacks.get("recharge")
    if recharge and action.charge:
        changes["recharge"] = round(max(0.0, recharge.resolve(origin.recharge, action.recharge)), 4)
    mult_stacks = {key[1]: stack for key, stack in stacks.items() if isinstance(key, tuple)}
    if mult_stacks:
        base_values = {m.vs: m.value for m in origin.multipliers}
        values = {m.vs: m.value for m in action.multipliers}
        order = [m.vs for m in action.multipliers]
        for vs, stack in mult_stacks.items():
            current = values.get(vs, 1.0)
            values[vs] = round(stack.resolve(base_values.get(vs, 1.0), current), 4)
            if vs not in order:
                order.append(vs)
        changes["multipliers"] = tuple(Multiplier(vs=vs, value=values[vs]) for vs in order)
    return dataclasses.replace(action, **changes) if changes else action


def settle_unit(unit: Unit, ops: Sequence[Mapping], base: Unit | None = None) -> Unit:
    """把一组运行时 op 结算到一个兵上，返回副本；没有任何变化时返回原对象。

    ``ops`` 是本局对这个兵生效的全部科技的 op（每个科技只出现一次）。
    ``base`` 是 BasePercent 的基准（未升级前的单位），缺省用 ``unit``。
    """
    base = base or unit
    own = [_normalized(op) for op in ops if op_targets_unit(op, unit)]
    if not own:
        return unit
    changes: dict = {}

    unit_stacks: dict = {}
    action_stacks: dict[str, dict] = {}
    actions, origin_actions = _switch_actions(unit, base, own)
    for op in own:
        stat = op["stat"]
        if stat in {"action_enable", "initial_tactic"}:
            continue
        if stat in _ACTION_STATS:
            key = ("mult", op["vs"]) if stat == "mult" else stat
            for name in _op_action_names(op, actions):
                action_stacks.setdefault(name, {}).setdefault(key, Stack()).push(op["kind"], op["value"])
            continue
        if stat == "armor":
            kinds = _ARMOR_FIELDS if op["armor_kind"] == "all" else {op["armor_kind"]: None}
            for kind in kinds:
                unit_stacks.setdefault(("armor", kind), Stack()).push(op["kind"], op["value"])
            continue
        if stat == "cost":
            unit_stacks.setdefault(("cost", op["resource"]), Stack()).push(op["kind"], op["value"])
            continue
        unit_stacks.setdefault(stat, Stack()).push(op["kind"], op["value"])

    if "hp" in unit_stacks:
        changes["hp"] = round(max(1.0, unit_stacks["hp"].resolve(base.hp, unit.hp)), 1)
    if "speed" in unit_stacks:
        changes["speed"] = round(max(0.0, unit_stacks["speed"].resolve(base.speed, unit.speed)), 3)
    for kind, attr in _ARMOR_FIELDS.items():
        stack = unit_stacks.get(("armor", kind))
        if stack:
            changes[attr] = round(stack.resolve(getattr(base, attr), getattr(unit, attr)), 3)
    cost = dict(unit.cost)
    for key, stack in unit_stacks.items():
        if isinstance(key, tuple) and key[0] == "cost":
            resource = key[1]
            value = max(0, round(stack.resolve(base.cost.get(resource, 0), cost.get(resource, 0))))
            if value:
                cost[resource] = value
            else:
                cost.pop(resource, None)
    if cost != unit.cost:
        changes["cost"] = cost

    origin_by = {a.name: a for a in origin_actions}
    settled = [
        _settle_action(a, origin_by.get(a.name, a), action_stacks[a.name])
        if a.name in action_stacks else a
        for a in actions
    ]
    if settled != list(unit.attack_actions):
        changes["attack_actions"] = settled
    # 其余阵型的攻击列表同样吃到数值效果（开关与换阵型只作用于当前列表）。
    if unit.attack_actions_by_tactic and action_stacks:
        by_tactic = {}
        for tactic, tactic_actions in unit.attack_actions_by_tactic.items():
            base_by = {a.name: a for a in base.attack_actions_by_tactic.get(tactic, tactic_actions)}
            by_tactic[tactic] = [
                _settle_action(a, base_by.get(a.name, a), action_stacks[a.name])
                if a.name in action_stacks else a
                for a in tactic_actions
            ]
        if by_tactic != unit.attack_actions_by_tactic:
            changes["attack_actions_by_tactic"] = by_tactic
    return dataclasses.replace(unit, **changes) if changes else unit


def _normalized(op: Mapping) -> Mapping:
    """``stat: range`` + ``subtype`` 是射程的旧写法，换成 range_max / range_min。"""
    if op.get("stat") != "range":
        return op
    stat = "range_min" if op.get("subtype") == "MinimumRange" else "range_max"
    return {**op, "stat": stat}


def apply_techs(
    units: Sequence[Unit],
    techs: list[dict],
    base_units: Sequence[Unit] | None = None,
) -> list[Unit]:
    """对一方的所有单位结算已选科技列表（每个科技一次），返回副本列表。

    同一兵吃到的全部科技 op 先合并再结算，不按科技逐个取大。
    """
    if not techs:
        return list(units)
    seen: set[str] = set()
    ops: list = []
    for tech in techs:
        key = str(tech.get("id") or id(tech))
        if key in seen:
            continue
        seen.add(key)
        ops.extend(tech.get("ops") or ())
    result = []
    for index, unit in enumerate(units):
        base = base_units[index] if base_units else unit
        result.append(settle_unit(unit, ops, base))
    return result


# ------------------------------------------------------------------
# 战报展示
# ------------------------------------------------------------------

def format_tech_lines(
    red_techs: list[dict], blue_techs: list[dict], *, title: str = "🔬 本局科技"
) -> list[str]:
    """生成已选科技展示行（嵌入到 VS banner）。"""
    from src.plugins.games.aoe3_battle.tech_summary import format_runtime_tech_summary

    if not red_techs and not blue_techs:
        return []
    lines = [title + "："]
    for t in red_techs:
        lines.append(f"   🔴 {format_runtime_tech_summary(t)}")
    for t in blue_techs:
        lines.append(f"   🔵 {format_runtime_tech_summary(t)}")
    return lines
