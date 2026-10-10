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
_CIVS_PATH = Path(__file__).resolve().parents[3] / "seeds" / "aoe3" / "civs.json"

# 类别标签 → 中文展示名（押注简报「已激活类别科技」用）
CATEGORY_LABELS = {
    "AbstractOutlaw": "亡命徒强化",
    "AbstractNativeWarrior": "传奇土著战士",
    "Mercenary": "雇佣兵契约",
}

_cache: dict | None = None
_civ_cache: dict | None = None
_civ_age_techs: dict[str, list[str]] | None = None


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


def civ_age_roots(civ_id: str | None, age: int) -> list[tuple[int, str]]:
    """文明开局与升时代自动激活的科技根（civs.xml ``agetech``）：[(时代, 科技 id)]。

    ``agetech`` 依次是 Age0..Age4，对应游戏时代 1..5；只取不超过本局时代的。
    """
    global _civ_age_techs
    if not civ_id:
        return []
    if _civ_age_techs is None:
        try:
            civs = json.loads(_CIVS_PATH.read_text(encoding="utf-8"))["civs"]
            _civ_age_techs = {
                key: list(row.get("age_techs") or ()) for key, row in civs.items()
            }
        except (OSError, json.JSONDecodeError, KeyError) as e:
            logger.warning("加载 civs.json 失败：%s（文明开局科技不生效）", e)
            _civ_age_techs = {}
    roots = _civ_age_techs.get(civ_id, ())
    return [(index + 1, tech) for index, tech in enumerate(roots) if index + 1 <= age]


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


def _age_tech_tiers(unit: Unit, age: int, civ_id: str | None) -> list[tuple[int, str]]:
    """本时代已生效的时代升级科技，带它最早进入的那一档时代：[(时代, 科技 id)]。"""
    if age is None or age < 2:
        return []
    first: dict[str, int] = {}

    def collect(table: dict, getter) -> None:
        for key in sorted((k for k in table if k.isdigit()), key=int):
            tier = int(key)
            if tier > age:
                continue
            for tech in getter(table[key]):
                first.setdefault(tech, tier)

    collect(_unit_upgrade_table(unit, civ_id), lambda entry: entry.get("techs") or ())
    cats = _load().get("category", {})
    for tag in _category_tags(unit):
        collect(cats[tag], lambda entry: entry)
    return [(tier, tech) for tech, tier in first.items()]


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

    有文明（``civ_id``）时，文明开局与升时代自动激活的科技也生效；普通斗蛐蛐没有文明。
    这些科技、时代升级科技、``tech_ids`` 与它们解锁的科技合并去重，同一科技只生效一次，
    按研究先后逐条结算（``tech_effects.settle_unit``）：时代从低到高；同一时代内
    文明自动激活 → 时代升级 → ``tech_ids``（按给定顺序）。
    """
    from .tech_effects import runtime_op, settle_unit
    from .tech_links import expand

    rows = tech_pool_rows()
    ordered: list[tuple[int, int, int, str]] = []
    for index, (tier, tech) in enumerate(civ_age_roots(civ_id, age or 0)):
        ordered.append((tier, 0, index, tech))
    for index, (tier, tech) in enumerate(_age_tech_tiers(unit, age, civ_id)):
        ordered.append((tier, 1, index, tech))
    for index, tech in enumerate(tech_ids):
        tier = (rows.get(tech) or {}).get("min_age") or 1
        ordered.append((int(tier), 2, index, tech))
    ordered.sort()
    ids = expand([tech for *_, tech in ordered], age=age or 0)
    if not ids:
        return unit
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
