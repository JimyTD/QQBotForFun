"""AoE3 时代升级运行时。

``seeds/aoe3/unit_upgrades.json`` / ``civ_unit_upgrades.json`` 记录每个兵、每个时代
已生效的**科技 id**（逐兵线 + 类别科技），由 ``scripts/crawler`` 下的升级 parser 生成。
运行时把这些科技连同它们解锁的科技合并去重，效果按统一算符一次结算
（docs/games/aoe3-battle.md §3.10）：同一科技只生效一次，不同科技全部叠加，没有取大。
2 时代（及以下）没有时代升级。
"""
from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Iterable
from pathlib import Path

from .models import Unit

logger = logging.getLogger("aoe3.upgrades")

_DATA_PATH = Path(__file__).resolve().parents[3] / "seeds" / "aoe3" / "unit_upgrades.json"
_CIV_DATA_PATH = (
    Path(__file__).resolve().parents[3] / "seeds" / "aoe3" / "civ_unit_upgrades.json"
)
_POOL_PATH = Path(__file__).resolve().parents[3] / "seeds" / "aoe3" / "civ_war_tech_pool.json"

# 类别标签 → 中文展示名（押注简报「已激活类别科技」用）
CATEGORY_LABELS = {
    "AbstractOutlaw": "亡命徒强化",
    "AbstractNativeWarrior": "传奇土著战士",
    "Mercenary": "雇佣兵契约",
}

_cache: dict | None = None
_civ_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("加载 unit_upgrades.json 失败：%s（改良将全部跳过）", e)
            _cache = {"units": {}, "category": {}}
    return _cache


def _load_civ() -> dict:
    global _civ_cache
    if _civ_cache is None:
        try:
            _civ_cache = json.loads(_CIV_DATA_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("加载 civ_unit_upgrades.json 失败: %s", e)
            _civ_cache = {"civs": {}}
    return _civ_cache


def _unit_upgrade_table(unit: Unit, civ_id: str | None) -> dict[str, dict]:
    base = _load().get("units", {}).get(unit.id, {})
    if civ_id:
        override = _load_civ().get("civs", {}).get(civ_id, {}).get(unit.id)
        if override:
            return {**base, **override}
    return base


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


def _category_tags(unit: Unit) -> list[str]:
    cats = _load().get("category", {})
    return [tag for tag in unit.type if tag in cats]


def age_tech_ids(unit: Unit, age: int, civ_id: str | None = None) -> list[str]:
    """这个兵在本时代已生效的时代升级科技 id（逐兵线 + 类别），去重、保持顺序。"""
    if age is None or age < 2:
        return []
    ids: list[str] = []
    entry = _pick(_unit_upgrade_table(unit, civ_id), age) or {}
    for tech in entry.get("techs") or ():
        if tech not in ids:
            ids.append(tech)
    cats = _load().get("category", {})
    for tag in _category_tags(unit):
        for tech in _pick_list(cats[tag], age):
            if tech not in ids:
                ids.append(tech)
    return ids


def _pick_list(table: dict[str, list], age: int) -> list[str]:
    best = None
    for key in table:
        try:
            value = int(key)
        except ValueError:
            continue
        if value <= age and (best is None or value > best):
            best = value
    return list(table.get(str(best), ())) if best is not None else []


def age_upgrade_line(unit: Unit, civ_id: str | None = None) -> tuple[set[str], set[str]]:
    """The unit's age-upgrade line at every tier: tech ids and display names.

    None of these is a composition choice.
    """
    tech_ids: set[str] = set()
    names: set[str] = set()
    for key, entry in _unit_upgrade_table(unit, civ_id).items():
        try:
            int(key)
        except ValueError:
            continue
        tech_ids.update(str(tech) for tech in entry.get("techs") or ())
        if entry.get("name"):
            names.add(str(entry["name"]))
    return tech_ids, names


def _unit_age_name(unit: Unit, age: int, civ_id: str | None = None) -> str | None:
    entry = _pick(_unit_upgrade_table(unit, civ_id), age)
    return entry.get("name") if entry else None


def apply_upgrades(
    unit: Unit,
    age: int,
    *,
    civ_id: str | None = None,
    tech_ids: Iterable[str] = (),
) -> Unit:
    """结算时代升级（以及调用方给的额外科技），返回 Unit 副本；无变化返回原对象。

    时代升级科技、``tech_ids`` 与它们解锁的科技合并去重，同一科技只生效一次，
    全部效果按统一算符一次结算（``tech_effects.settle_unit``）。
    """
    from .tech_effects import runtime_op, settle_unit
    from .tech_links import expand

    ids = expand([*age_tech_ids(unit, age, civ_id), *tech_ids], age=age or 0)
    if not ids:
        return unit
    rows = tech_pool_rows()
    ops = []
    for tech in ids:
        row = rows.get(tech)
        if row is None:
            continue
        for op in (*row.get("combat_ops", ()), *row.get("cost_ops", ())):
            translated = runtime_op(op)
            if translated is not None:
                ops.append(translated)
    upgraded = settle_unit(unit, ops, unit)
    name = _unit_age_name(unit, age, civ_id)
    if name and name != upgraded.name:
        upgraded = dataclasses.replace(upgraded, name=name)
    return upgraded


_pool_rows: dict[str, dict] | None = None


def tech_pool_rows() -> dict[str, dict]:
    """科技池（seeds/aoe3/civ_war_tech_pool.json）按 id 索引。"""
    global _pool_rows
    if _pool_rows is None:
        try:
            payload = json.loads(_POOL_PATH.read_text(encoding="utf-8"))
            _pool_rows = {row["id"]: row for row in payload["techs"]}
        except (OSError, json.JSONDecodeError, KeyError) as e:
            logger.warning("加载 civ_war_tech_pool.json 失败：%s（时代升级不生效）", e)
            _pool_rows = {}
    return _pool_rows


def active_category_techs(units: list[Unit], age: int) -> list[tuple[str, float]]:
    """本局有该类别单位时，列出已生效的类别科技 [(中文名, 生命倍率)]（押注简报用）。"""
    if age is None or age <= 2:
        return []
    cats = _load().get("category", {})
    rows = tech_pool_rows()
    out: list[tuple[str, float]] = []
    seen: set[str] = set()
    for unit in units:
        for tag in _category_tags(unit):
            if tag in seen:
                continue
            ids = _pick_list(cats[tag], age)
            if not ids:
                continue
            seen.add(tag)
            inc = 0.0
            for tech in ids:
                for op in (rows.get(tech) or {}).get("combat_ops", ()):
                    if (
                        op.get("subtype") in {"Hitpoints", "HitPoints"}
                        and op.get("relativity") == "BasePercent"
                        and any(t.get("value") == tag for t in op.get("targets") or ())
                    ):
                        inc += float(op["amount"]) - 1.0
            out.append((CATEGORY_LABELS.get(tag, tag), round(1.0 + inc, 4)))
    return out
