"""AoE3 科技效果运行时应用。

科技 parser 将游戏 ``techtreey.xml`` 的效果规整为 ``scope`` + ``ops`` 后，
由本模块把**已明确选定**的科技作用到 Unit 副本。它不读取科技池、不选择科技、
也不引入随机性；未来的文明科技树和主城国策共用这套效果语义。
"""
from __future__ import annotations

import dataclasses
from typing import Sequence

from .models import Multiplier, Unit


# ------------------------------------------------------------------
# 应用
# ------------------------------------------------------------------

def _slots_for_op(op: dict, unit: Unit) -> list[str]:
    """op 的 action 落 ranged/melee 哪些槽（与 upgrades_parser._slots_for_action 同源逻辑）。"""
    allact = op.get("allactions", False)
    action = op.get("action")
    if allact or not action:
        slots = []
        if unit.attack_ranged:
            slots.append("ranged")
        if unit.attack_melee:
            slots.append("melee")
        return slots
    if action == unit.protoaction_ranged:
        return ["ranged"] if unit.attack_ranged else []
    if action == unit.protoaction_melee:
        return ["melee"] if unit.attack_melee else []
    return []


def _op_dedup_key(op: dict, unit: Unit) -> tuple[str, ...]:
    """为 op 生成去重键：同键的多条 op 只保留最强的一条。

    键的构成取决于 stat 类型：
      - slot-routed (range/aoe/rof): (stat, kind, slot)
      - mult: (stat, kind, slot, vs)
      - 全局 (hp/damage/speed): (stat, kind)
      - armor: (stat, kind, armor_kind)
      - cost: (stat, kind, resource)

    返回 tuple 列表（一条 op 可能命中多个 slot，则生成多个键）。
    """
    stat = op["stat"]
    kind = op["kind"]

    if stat in ("range", "aoe", "rof"):
        slots = _slots_for_op(op, unit)
        return tuple(f"{stat}:{kind}:{s}" for s in slots) if slots else (f"{stat}:{kind}:",)
    if stat == "mult":
        vs = op.get("vs", "")
        slots = _slots_for_op(op, unit)
        return tuple(f"mult:{kind}:{s}:{vs}" for s in slots) if slots else (f"mult:{kind}::{vs}",)
    if stat == "armor":
        return (f"armor:{kind}:{op.get('armor_kind', '')}",)
    if stat == "cost":
        return (f"cost:{kind}:{op.get('resource', '')}",)
    # hp, damage, speed 等全局 stat
    return (f"{stat}:{kind}",)


def _deduplicate_ops(ops: list[dict], unit: Unit) -> list[dict]:
    """同一科技内按去重键分组，每组只保留 value 最大的 op。

    科技列出多条 action 变体是为覆盖不同兵种的代表动作名，对单个兵只应生效一次。
    数据中偶有 parser 合并产生的重复（如同 stat 不同 value），取最大值。
    """
    seen: dict[str, dict] = {}  # key → best op
    result_keys: list[str] = []  # 保持首次出现顺序

    for op in ops:
        keys = _op_dedup_key(op, unit)
        for k in keys:
            if k not in seen:
                seen[k] = op
                result_keys.append(k)
            elif op["value"] > seen[k]["value"]:
                seen[k] = op

    # 同一 op 可能产生多个 key（多 slot），去重保留唯一 op
    emitted: set[int] = set()
    result: list[dict] = []
    for k in result_keys:
        op = seen[k]
        op_id = id(op)
        if op_id not in emitted:
            emitted.add(op_id)
            result.append(op)
    return result


def _apply_one_tech(unit: Unit, tech: dict, base: Unit) -> Unit:
    """把一条已选科技叠到单位上，返回新副本（无效不动）。

    base: tier 升级前的原始 Unit，用于 BasePercent 加算（AoE3 所有 BasePercent
    效果加算于原始基础值，而非乘在 tier 之后的值上）。

    去重原则：同一条科技内，同一 (stat, kind, 目标键) 只生效一次。
    科技列出多条 action 变体是为覆盖不同兵种的代表动作名，实际对单个兵只取
    首次命中（值相同时无差别；值不同时取最大值的 op 先到先得，见 _best_ops）。
    """
    scope = set(tech["scope"])
    unit_tags = set(unit.type) | {unit.id}
    if not (scope & unit_tags):
        return unit

    # 预处理：按 (stat, kind, 目标键) 分组，每组只保留最强的一条 op
    best_ops = _deduplicate_ops(tech["ops"], unit)

    changes: dict = {}
    for op in best_ops:
        stat = op["stat"]
        kind = op["kind"]
        val = op["value"]

        if stat == "hp" and kind == "mult":
            changes["hp"] = round(changes.get("hp", unit.hp) + base.hp * (val - 1.0))
        elif stat == "hp" and kind == "add":
            changes["hp"] = round(changes.get("hp", unit.hp) + val)
        elif stat == "damage" and kind == "mult":
            inc = val - 1.0
            if unit.attack_ranged:
                changes["attack_ranged"] = round(
                    changes.get("attack_ranged", unit.attack_ranged)
                    + base.attack_ranged * inc, 2)
                if unit.damage_cap_ranged:
                    changes["damage_cap_ranged"] = round(
                        changes.get("damage_cap_ranged", unit.damage_cap_ranged)
                        + base.damage_cap_ranged * inc, 2)
            if unit.attack_melee:
                changes["attack_melee"] = round(
                    changes.get("attack_melee", unit.attack_melee)
                    + base.attack_melee * inc, 2)
                if unit.damage_cap_melee:
                    changes["damage_cap_melee"] = round(
                        changes.get("damage_cap_melee", unit.damage_cap_melee)
                        + base.damage_cap_melee * inc, 2)
        elif stat == "range" and kind == "add":
            for s in _slots_for_op(op, unit):
                if s == "ranged" and unit.range:
                    changes["range"] = round(
                        changes.get("range", unit.range) + val, 2)
                elif s == "melee" and unit.range_melee:
                    changes["range_melee"] = round(
                        changes.get("range_melee", unit.range_melee) + val, 2)
        elif stat == "aoe" and kind == "add":
            for s in _slots_for_op(op, unit):
                if s == "ranged":
                    changes["aoe_radius_ranged"] = round(
                        changes.get("aoe_radius_ranged", unit.aoe_radius_ranged) + val, 2)
                elif s == "melee":
                    changes["aoe_radius_melee"] = round(
                        changes.get("aoe_radius_melee", unit.aoe_radius_melee) + val, 2)
        elif stat == "rof" and kind == "set":
            for s in _slots_for_op(op, unit):
                if s == "ranged":
                    changes["rof_ranged"] = round(val, 3)
                elif s == "melee":
                    changes["rof_melee"] = round(val, 3)
        elif stat == "speed":
            cur = changes.get("speed", unit.speed)
            if kind == "mult":
                changes["speed"] = round(cur * val, 3)
            elif kind == "add":
                changes["speed"] = round(cur + val, 3)
            elif kind == "set":
                changes["speed"] = round(val, 3)
        elif stat == "armor" and kind == "add":
            ak = op.get("armor_kind", "")
            if ak == "melee":
                changes["armor_melee"] = round(
                    changes.get("armor_melee", unit.armor_melee) + val, 3)
            elif ak == "ranged":
                changes["armor_ranged"] = round(
                    changes.get("armor_ranged", unit.armor_ranged) + val, 3)
        elif stat == "cost" and kind == "mult":
            resource = op.get("resource", "")
            if resource and resource in base.cost:
                cur_cost = dict(changes.get("cost", unit.cost))
                cur_cost[resource] = max(0, round(
                    cur_cost.get(resource, unit.cost.get(resource, 0))
                    + base.cost[resource] * (val - 1.0)))
                changes["cost"] = cur_cost
        elif stat == "mult" and kind == "add":
            vs = op.get("vs", "")
            if not vs:
                continue
            for s in _slots_for_op(op, unit):
                field_name = f"multipliers_{s}"
                cur_list = changes.get(field_name) or list(getattr(unit, field_name))
                new_list = []
                found = False
                for m in cur_list:
                    if m.vs == vs:
                        new_list.append(dataclasses.replace(m, value=round(m.value + val, 3)))
                        found = True
                    else:
                        new_list.append(m)
                if not found:
                    new_list.append(Multiplier(vs=vs, value=round(1.0 + val, 3)))
                changes[field_name] = new_list

    if not changes:
        return unit
    return dataclasses.replace(unit, **changes)


def apply_techs(
    units: Sequence[Unit],
    techs: list[dict],
    base_units: Sequence[Unit] | None = None,
) -> list[Unit]:
    """对一方的所有单位叠加已选科技列表，返回新副本列表。

    base_units: tier 升级前的原始 Unit 列表（与 units 同序），用于 BasePercent
    加算。如果为 None 则用 units 自身作为 base（适用于无 tier 的场景）。
    """
    if not techs:
        return list(units)
    result = []
    for i, u in enumerate(units):
        base = base_units[i] if base_units else u
        cur = u
        for t in techs:
            cur = _apply_one_tech(cur, t, base)
        result.append(cur)
    return result


# ------------------------------------------------------------------
# 战报展示
# ------------------------------------------------------------------

def format_tech_lines(
    red_techs: list[dict], blue_techs: list[dict], *, title: str = "🔬 本局科技"
) -> list[str]:
    """生成已选科技展示行（嵌入到 VS banner）。"""
    if not red_techs and not blue_techs:
        return []
    lines = [title + "："]
    for t in red_techs:
        lines.append(f"   🔴 {t['name_zh']}（{_brief_desc(t)}）")
    for t in blue_techs:
        lines.append(f"   🔵 {t['name_zh']}（{_brief_desc(t)}）")
    return lines


def _brief_desc(tech: dict) -> str:
    """一行简述科技效果。"""
    parts = []
    for op in tech["ops"]:
        stat = op["stat"]
        kind = op["kind"]
        val = op["value"]
        if stat == "hp" and kind == "mult":
            pct = round((val - 1) * 100)
            parts.append(f"血{'+' if pct > 0 else ''}{pct}%")
        elif stat == "damage" and kind == "mult":
            pct = round((val - 1) * 100)
            parts.append(f"攻{'+' if pct > 0 else ''}{pct}%")
        elif stat == "speed" and kind == "mult":
            pct = round((val - 1) * 100)
            parts.append(f"速{'+' if pct > 0 else ''}{pct}%")
        elif stat == "speed" and kind == "add":
            parts.append(f"速{'+' if val > 0 else ''}{val}")
        elif stat == "range" and kind == "add":
            parts.append(f"射程+{val}")
        elif stat == "aoe" and kind == "add":
            parts.append(f"AOE+{val}")
        elif stat == "rof" and kind == "set":
            parts.append(f"攻速→{val}s")
        elif stat == "armor" and kind == "add":
            ak = op.get("armor_kind", "")
            parts.append(f"{'近' if ak == 'melee' else '远'}防+{val}")
        elif stat == "cost" and kind == "mult":
            pct = round((val - 1) * 100)
            res = op.get("resource", "")
            parts.append(f"造价{res}{'+' if pct > 0 else ''}{pct}%")
        elif stat == "mult" and kind == "add":
            vs_short = op.get("vs", "").replace("Abstract", "")
            parts.append(f"vs{vs_short}+{val}")
    scope = "/".join(s.replace("Abstract", "") for s in tech["scope"])
    return f"{scope}: {', '.join(parts)}" if parts else scope
