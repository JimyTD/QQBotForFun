"""AoE3 通用科技（roguelike 随机研发科技）—— 运行时选择与应用。

读取 ``seeds/aoe3/generic_techs.json``（由 ``scripts/crawler/aoe3_generic_techs_parser.py``
离线生成），每局为双方各随机 K/2 条**与己方阵容相关**的横向增益，叠在 tier 之上。

设计依据：docs/games/aoe3-battle.md §3.10（通用科技 roguelike）。

要点：
  - 每方 K/2 条科技（单挑/自选 K=2 → 各 1；押注 K=4 → 各 2）。
  - **相关性**：科技 scope ∩ 己方单位 type 非空才入候选。
  - **age 门槛**：tech.age ≤ 本局 age。
  - 双方独立抽取，可能抽到同一条（共用 → 白赚）。
  - 应用顺序：先 tier（apply_upgrades），再通用科技（apply_generic_techs）。
  - 效果规整逻辑与 upgrades.py 同源（op 里保留 action，按单位代表动作分 ranged/melee 槽）。
"""
from __future__ import annotations

import dataclasses
import json
import logging
import random
from pathlib import Path
from typing import Sequence

from .models import Multiplier, Unit

logger = logging.getLogger("aoe3.generic_techs")

_DATA_PATH = Path(__file__).resolve().parents[3] / "seeds" / "aoe3" / "generic_techs.json"

_cache: list[dict] | None = None


def _load() -> list[dict]:
    global _cache
    if _cache is None:
        try:
            data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
            _cache = data.get("techs", [])
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("加载 generic_techs.json 失败：%s（通用科技将跳过）", e)
            _cache = []
    return _cache


# ------------------------------------------------------------------
# 选择
# ------------------------------------------------------------------

def _unit_tags(units: Sequence[Unit]) -> set[str]:
    """收集一方所有单位的 type 标签（含具体 id，用于具体兵科技如细红线→musketeer）。"""
    tags: set[str] = set()
    for u in units:
        tags.update(u.type)
        tags.add(u.id)
    return tags


def _is_relevant(tech: dict, tags: set[str]) -> bool:
    """科技 scope 与己方单位标签有交集 → 相关。"""
    for s in tech["scope"]:
        if s in tags:
            return True
    return False


def select_techs(
    red_units: Sequence[Unit],
    blue_units: Sequence[Unit],
    age: int,
    *,
    k: int = 4,
    rng: random.Random | None = None,
) -> tuple[list[dict], list[dict]]:
    """为双方各抽 k//2 条相关通用科技。

    Returns (red_techs, blue_techs)，每条是 generic_techs.json 里的原始 dict。
    池中不够时尽量抽满但不报错。
    """
    if rng is None:
        rng = random.Random()
    pool = [t for t in _load() if t["age"] <= age]
    per_side = k // 2 or 1

    red_tags = _unit_tags(red_units)
    blue_tags = _unit_tags(blue_units)
    red_pool = [t for t in pool if _is_relevant(t, red_tags)]
    blue_pool = [t for t in pool if _is_relevant(t, blue_tags)]

    red_techs = rng.sample(red_pool, min(per_side, len(red_pool)))
    blue_techs = rng.sample(blue_pool, min(per_side, len(blue_pool)))
    return red_techs, blue_techs


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
    # protoaction_ranged/melee 存在 Unit 的上游 JSON 但 dataclass 没直接暴露
    # → 用 internal_name / type 不够；需要看 unit_json。
    # 但 Unit 无 protoaction 字段（历史原因），直接在此用规则近似：
    #   远程代表动作含 "Ranged/Bow/Volley" → ranged 槽
    #   近战代表动作含 "Hand/Melee/Defend" → melee 槽
    # 更稳妥的做法是给 Unit 加 protoaction_ranged/melee 字段，但改动面大，暂用这套。
    # 注意：scope 已保证科技只对有该标签的兵起作用，action 不匹配顶多不生效。
    al = action.lower()
    if "ranged" in al or "bow" in al or "volley" in al or "stagger" in al:
        return ["ranged"] if unit.attack_ranged else []
    if "hand" in al or "melee" in al or "defend" in al or "trample" in al:
        return ["melee"] if unit.attack_melee else []
    # fallback: 两个槽都给
    slots = []
    if unit.attack_ranged:
        slots.append("ranged")
    if unit.attack_melee:
        slots.append("melee")
    return slots


def _apply_one_tech(unit: Unit, tech: dict, base: Unit) -> Unit:
    """把一条通用科技叠到单位上，返回新副本（无效不动）。

    base: tier 升级前的原始 Unit，用于 BasePercent 加算（AoE3 所有 BasePercent
    效果加算于原始基础值，而非乘在 tier 之后的值上）。
    """
    scope = set(tech["scope"])
    unit_tags = set(unit.type) | {unit.id}
    if not (scope & unit_tags):
        return unit

    changes: dict = {}
    for op in tech["ops"]:
        stat = op["stat"]
        kind = op["kind"]
        val = op["value"]

        if stat == "hp" and kind == "mult":
            # BasePercent 加算：增量 = base_hp × (val - 1)
            changes["hp"] = round(changes.get("hp", unit.hp) + base.hp * (val - 1.0))
        elif stat == "hp" and kind == "add":
            changes["hp"] = round(changes.get("hp", unit.hp) + val)
        elif stat == "damage" and kind == "mult":
            # BasePercent 加算：增量 = base_attack × (val - 1)
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
                    # 隐含 1.0 倍率 + 增量
                    new_list.append(Multiplier(vs=vs, value=round(1.0 + val, 3)))
                changes[field_name] = new_list

    if not changes:
        return unit
    return dataclasses.replace(unit, **changes)


def apply_generic_techs(
    units: Sequence[Unit],
    techs: list[dict],
    base_units: Sequence[Unit] | None = None,
) -> list[Unit]:
    """对一方的所有单位叠加通用科技列表，返回新副本列表。

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

def format_tech_lines(red_techs: list[dict], blue_techs: list[dict]) -> list[str]:
    """生成通用科技展示行（嵌入到 VS banner）。"""
    if not red_techs and not blue_techs:
        return []
    lines = ["🔬 本局通用科技（roguelike）："]
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
