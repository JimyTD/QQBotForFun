"""红警2斗蛐蛐 —— 对阵面板与兵种简介（来自 OpenRA Description，非帝国类型体系）。"""

from __future__ import annotations

import re

from .constants import CELL_WDIST
from .locale import (
    localized_actor_description,
    localized_actor_name,
    localized_weapon_label,
)
from .repo import ActorDef, resolve_weapon
from .targeting import armament_allowed

_ARMOR_ZH = {
    "None": "无甲",
    "Flak": "防弹",
    "Plate": "板甲",
    "Light": "轻甲",
    "Medium": "中甲",
    "Heavy": "重甲",
    "Wood": "木甲",
    "Steel": "钢甲",
    "Concrete": "混凝土",
    "Drone": "无人机",
}

_LOCOMOTOR_ZH = {
    "foot": "步兵",
    "wheeled": "轮式",
    "tracked": "履带",
    "heavytracked": "重履带",
    "ships": "舰艇",
}


def _cells_from_wdist(wdist: int | None) -> str:
    if not wdist:
        return "?"
    cells = wdist / CELL_WDIST
    if abs(cells - round(cells)) < 0.05:
        return str(int(round(cells)))
    return f"{cells:.1f}"


def _primary_weapon(actor: ActorDef):
    for arm in actor.armaments:
        if not armament_allowed(arm, actor=actor):
            continue
        return resolve_weapon(arm.weapon)
    return None


def format_attack_summary(actor: ActorDef) -> str:
    """主武器伤害与射程（斗蛐蛐展示用，中文标签）。"""
    parts: list[str] = []
    labels = ("主武器", "副武器")
    idx = 0
    for arm in actor.armaments:
        if not armament_allowed(arm, actor=actor):
            continue
        w = resolve_weapon(arm.weapon)
        if not w or not w.warheads:
            continue
        dmg = max(wh.damage for wh in w.warheads)
        rng = _cells_from_wdist(w.range)
        wlabel = localized_weapon_label(arm.weapon)
        slot = labels[idx] if idx < len(labels) else f"武器{idx + 1}"
        parts.append(f"{slot}·{wlabel} {dmg}伤/{rng}格")
        idx += 1
    if len(parts) > 2:
        return "；".join(parts[:2])
    return parts[0] if parts else "无武器"


def format_description_blurb(actor: ActorDef, max_lines: int = 2) -> str:
    """兵种说明（优先 locale_zh，否则英译兜底）。"""
    text = localized_actor_description(actor.id, actor.description or "")
    if not text.strip():
        return ""
    lines: list[str] = []
    for part in text.replace("\\n", "\n").split("\n"):
        part = re.sub(r"\s+", " ", part.strip())
        if not part:
            continue
        lines.append(part)
        if len(lines) >= max_lines:
            break
    return " / ".join(lines)


def display_name(actor: ActorDef) -> str:
    return localized_actor_name(actor.id, actor.name)


def format_unit_role(actor: ActorDef) -> str:
    """兵种角色标签（红警语境，不用帝国 AbstractXxx）。"""
    tags: list[str] = []
    cat = actor.categories or ""
    if "Infantry" in cat:
        tags.append("步兵")
    if "Vehicle" in cat:
        tags.append("车辆")
    if "Aircraft" in cat or "Air" in actor.target_types:
        tags.append("飞行器")
    if "Naval" in cat or "Water" in actor.target_types:
        tags.append("海军")
    if actor.crushes and "infantry" in actor.crushes:
        tags.append("可碾压步兵")
    if actor.crushable:
        tags.append("可被碾压")
    loc = _LOCOMOTOR_ZH.get(actor.locomotor, actor.locomotor)
    if loc and loc not in tags:
        tags.append(loc)
    armor = _ARMOR_ZH.get(actor.armor, actor.armor)
    tags.append(f"{armor}")
    return " · ".join(tags)
