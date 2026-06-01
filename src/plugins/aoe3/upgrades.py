"""AoE3 单位改良（科技加成）运行时应用。

读取 ``seeds/aoe3/unit_upgrades.json``（由 ``scripts/crawler/aoe3_upgrades_parser.py``
离线生成），对 ``Unit`` 按指定时代叠加血/攻加成，返回**副本**（不改全局 seed）。

设计依据：docs/games/aoe3-battle.md §3.10。要点：
  - 逐兵 id 链与**类别科技**（亡命徒/佣兵/土著，按标签）各取该时代条目，
    **取较大者整包**（不混不叠）：既避免土著「逐兵传奇 + 类别传奇」double，
    也避免共享单位的小额文明逐兵档顶掉更大的类别加成。
  - 指定时代 N → 取该兵 ≤N 的最高档 cumulative mult（BasePercent 已在生成期累加）。
  - 2 时代（及以下）默认无军改，原样返回。
"""
from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

from .models import Unit

logger = logging.getLogger("aoe3.upgrades")

_DATA_PATH = Path(__file__).resolve().parents[3] / "seeds" / "aoe3" / "unit_upgrades.json"

# 类别标签 → 中文展示名（押注简报「已激活类别科技」用）
CATEGORY_LABELS = {
    "AbstractOutlaw": "亡命徒强化",
    "AbstractNativeWarrior": "传奇土著战士",
    "Mercenary": "雇佣兵契约",
}

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("加载 unit_upgrades.json 失败：%s（改良将全部跳过）", e)
            _cache = {"units": {}, "category": {}}
    return _cache


def _pick(table: dict[str, dict], age: int) -> dict | None:
    """从 {"3":{...},"4":{...}} 里取 ≤age 的最高档条目。"""
    best_key = None
    for k in table:
        try:
            ki = int(k)
        except ValueError:
            continue
        if ki <= age and (best_key is None or ki > best_key):
            best_key = ki
    return table.get(str(best_key)) if best_key is not None else None


def _category_tag(unit: Unit) -> str | None:
    cats = _load().get("category", {})
    for tag in unit.type:
        if tag in cats:
            return tag
    return None


def get_multipliers(unit: Unit, age: int) -> tuple[float, float, str | None]:
    """返回 (hp_mult, damage_mult, source)。

    source: "unit"（逐兵链）/ 类别标签名 / None（无加成）。
    """
    if age is None or age < 2:
        return 1.0, 1.0, None
    data = _load()

    # 逐兵链与类别科技各取该时代条目，**取较大者整包**（不混不叠）：
    #   - 避免土著「逐兵传奇 +50」与「类别传奇 +50」叠成 +100（double）；
    #   - 避免共享单位的小额文明逐兵档（如瑞士长枪荷兰 Waardgelders +10）
    #     顶掉更大的类别加成（佣兵 +50）。
    candidates: list[tuple[float, float, str]] = []
    per_id = data.get("units", {}).get(unit.id)
    if per_id:
        e = _pick(per_id, age)
        if e:
            candidates.append((e.get("hp_mult", 1.0), e.get("damage_mult", 1.0), "unit"))
    tag = _category_tag(unit)
    if tag:
        e = _pick(data["category"][tag], age)
        if e:
            candidates.append((e.get("hp_mult", 1.0), e.get("damage_mult", 1.0), tag))
    if not candidates:
        return 1.0, 1.0, None
    # 取 hp_mult 较大的整包；source 用于展示
    return max(candidates, key=lambda c: c[0])


def _unit_extras(unit: Unit, age: int) -> dict:
    """取逐兵链在 ≤age 的 extras 整包（range/aoe/rof/速度/护甲/倍率）。

    extras 只挂在逐兵条目（"units"）上；类别科技不带这些字段。
    """
    if age is None or age < 2:
        return {}
    per_id = _load().get("units", {}).get(unit.id)
    if not per_id:
        return {}
    return _pick(per_id, age) or {}


def _apply_mult_add(mults: list, mult_add_vs: dict[str, float]) -> list | None:
    """按 vs 累加 delta；无条目视为隐含 1.0 倍并创建；返回新列表（无改动则 None）。"""
    if not mult_add_vs:
        return None
    from .models import Multiplier
    out = list(mults)
    remaining = dict(mult_add_vs)
    for i, m in enumerate(out):
        if m.vs in remaining:
            out[i] = dataclasses.replace(m, value=round(m.value + remaining.pop(m.vs), 3))
    for vs, delta in remaining.items():
        out.append(Multiplier(vs=vs, value=round(1.0 + delta, 3)))
    return out if out != list(mults) else None


def _unit_age_name(unit: Unit, age: int) -> str | None:
    """取该单位在指定时代的升级名（SetName），无则 None。"""
    per_id = _load().get("units", {}).get(unit.id)
    if not per_id:
        return None
    e = _pick(per_id, age)
    return e.get("name") if e else None


def apply_upgrades(unit: Unit, age: int) -> Unit:
    """按时代叠加改良，返回 Unit 副本（无加成时返回原对象）。

    血/攻取逐兵与类别 max 整包；range/aoe/rof/速度/护甲/倍率 取逐兵链整包。
    """
    hp_mult, dmg_mult, _ = get_multipliers(unit, age)
    extras = _unit_extras(unit, age)
    upgraded_name = _unit_age_name(unit, age)
    if hp_mult == 1.0 and dmg_mult == 1.0 and not extras and not upgraded_name:
        return unit

    changes: dict = {}
    if upgraded_name:
        changes["name"] = upgraded_name
    if hp_mult != 1.0:
        changes["hp"] = round(unit.hp * hp_mult)
    if dmg_mult != 1.0:
        if unit.attack_ranged:
            changes["attack_ranged"] = round(unit.attack_ranged * dmg_mult, 2)
        if unit.attack_melee:
            changes["attack_melee"] = round(unit.attack_melee * dmg_mult, 2)
        # 溅射伤害池随主伤害同比例缩放，保持铁律一致
        if unit.damage_cap_ranged:
            changes["damage_cap_ranged"] = round(unit.damage_cap_ranged * dmg_mult, 2)
        if unit.damage_cap_melee:
            changes["damage_cap_melee"] = round(unit.damage_cap_melee * dmg_mult, 2)

    # --- extras（整包，relativity 已在生成期换算）---
    range_add = extras.get("range_add", {})
    if range_add.get("ranged") and unit.range:
        changes["range"] = round(unit.range + range_add["ranged"], 2)
    if range_add.get("melee") and unit.range_melee:
        changes["range_melee"] = round(unit.range_melee + range_add["melee"], 2)

    aoe_add = extras.get("aoe_add", {})
    if aoe_add.get("ranged"):
        changes["aoe_radius_ranged"] = round(unit.aoe_radius_ranged + aoe_add["ranged"], 2)
    if aoe_add.get("melee"):
        changes["aoe_radius_melee"] = round(unit.aoe_radius_melee + aoe_add["melee"], 2)

    rof_set = extras.get("rof_set", {})
    if rof_set.get("ranged"):
        changes["rof_ranged"] = round(float(rof_set["ranged"]), 3)
    if rof_set.get("melee"):
        changes["rof_melee"] = round(float(rof_set["melee"]), 3)

    armor_add = extras.get("armor_add", {})
    if armor_add.get("melee"):
        changes["armor_melee"] = round(unit.armor_melee + armor_add["melee"], 3)
    if armor_add.get("ranged"):
        changes["armor_ranged"] = round(unit.armor_ranged + armor_add["ranged"], 3)

    speed = unit.speed
    if extras.get("speed_set") is not None:
        speed = float(extras["speed_set"])
    speed = speed * extras.get("speed_mult", 1.0) + extras.get("speed_add", 0.0)
    if abs(speed - unit.speed) > 1e-9:
        changes["speed"] = round(speed, 3)

    mult_add = extras.get("mult_add", {})
    if mult_add.get("ranged"):
        new_m = _apply_mult_add(unit.multipliers_ranged, mult_add["ranged"])
        if new_m is not None:
            changes["multipliers_ranged"] = new_m
    if mult_add.get("melee"):
        new_m = _apply_mult_add(unit.multipliers_melee, mult_add["melee"])
        if new_m is not None:
            changes["multipliers_melee"] = new_m

    if not changes:
        return unit
    return dataclasses.replace(unit, **changes)


def active_category_techs(units: list[Unit], age: int) -> list[tuple[str, float]]:
    """返回本局已激活的类别科技 [(中文名, hp_mult)]，用于押注简报展示。

    仅当本局存在该类别且**该类别单位走类别科技**（即未被逐兵链覆盖）时列出。
    """
    if age is None or age <= 2:
        return []
    data = _load()
    cats = data.get("category", {})
    seen: set[str] = set()
    out: list[tuple[str, float]] = []
    for u in units:
        # 仅当该单位实际「吃到」类别科技（max 取胜方为类别标签）时才展示，
        # 避免逐兵档更高时仍误报类别加成。
        _, _, source = get_multipliers(u, age)
        if source is None or source == "unit" or source in seen:
            continue
        entry = _pick(cats[source], age)
        if not entry:
            continue
        seen.add(source)
        out.append((CATEGORY_LABELS.get(source, source), entry.get("hp_mult", 1.0)))
    return out
