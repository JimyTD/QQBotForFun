"""红警2斗蛐蛐 —— 对阵面板与兵种简介（来自 OpenRA Description，非帝国类型体系）。"""

from __future__ import annotations

import re

from .constants import CELL_WDIST
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
        if not armament_allowed(arm):
            continue
        return resolve_weapon(arm.weapon)
    return None


def format_attack_summary(actor: ActorDef) -> str:
    """主武器伤害与射程（斗蛐蛐展示用）。"""
    parts: list[str] = []
    for arm in actor.armaments:
        if not armament_allowed(arm):
            continue
        w = resolve_weapon(arm.weapon)
        if not w or not w.warheads:
            continue
        dmg = max(wh.damage for wh in w.warheads)
        rng = _cells_from_wdist(w.range)
        parts.append(f"{arm.weapon} {dmg}伤/{rng}格")
    if len(parts) > 1:
        return "；".join(parts[:2])
    return parts[0] if parts else "无武器"


def format_description_blurb(actor: ActorDef, max_lines: int = 2) -> str:
    """游戏内 Buildable.Description，整理为群消息可读简介。"""
    raw = (actor.description or "").strip()
    if not raw:
        return ""
    text = raw.replace("\\n", "\n")
    lines: list[str] = []
    for part in text.split("\n"):
        part = part.strip()
        if not part:
            continue
        part = re.sub(r"\s+", " ", part)
        lines.append(part)
        if len(lines) >= max_lines:
            break
    return " / ".join(lines)


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
