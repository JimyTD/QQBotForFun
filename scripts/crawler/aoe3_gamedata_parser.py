"""AoE3 DE Game Data Parser — 从游戏原始文件生成 seeds/aoe3/units.json。

数据源（由 aoe3_bar_extractor.py 从 Data.bar 提取）：
  - protoy.xml          (单位原型定义)
  - stringtabley_en.xml (英文名)
  - stringtabley_zh.xml (中文名)

设计原则：
  - 数据第一：type/multiplier.vs 直接存游戏原始标签，不翻译
  - 倍率天然匹配：damagebonus type 和 unit.type 使用同一命名空间
  - 翻译只在展示层：i18n_zh.json 负责 AbstractXxx → 中文

用法:
  1. 先运行 aoe3_bar_extractor.py 提取 XML
  2. 再运行本脚本生成 seeds/aoe3/units.json + seeds/aoe3/i18n_zh.json
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# ============================================================
# 路径
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXTRACTED_DIR = Path(__file__).resolve().parent / "_extracted"
SEEDS_DIR = PROJECT_ROOT / "seeds" / "aoe3"

PROTOY_PATH = EXTRACTED_DIR / "protoy.xml"
STRING_EN_PATH = EXTRACTED_DIR / "stringtabley_en.xml"
STRING_ZH_PATH = EXTRACTED_DIR / "stringtabley_zh.xml"

OUTPUT_UNITS_PATH = SEEDS_DIR / "units.json"
OUTPUT_I18N_PATH = SEEDS_DIR / "i18n_zh.json"


# ============================================================
# 应保留的 unittype 标签前缀/名称（分类标签）
# 其他的 LogicalType*/CountsToward*/ConvertsHerds/HasBountyValue 等行为标签过滤掉
# ============================================================
KEEP_TYPE_PREFIXES = ("Abstract",)
KEEP_TYPE_EXACT = {
    "Hero", "Ship", "Mercenary", "Military", "Unit", "UnitClass",
    "Ranged", "Guardian", "Building", "MercType2",
    "Huntable", "Herdable",
    # 以下被 damagebonus 引用，需保留以支持倍率匹配
    "LogicalTypeLandMilitary", "LogicalTypeLandEconomy",
}


# ============================================================
# 攻击动作名优先级（选择"标准"姿态）
# ============================================================
ATTACK_PRIORITY = {
    "DefendRangedAttack": 1,
    "StaggerRangedAttack": 2,
    "VolleyRangedAttack": 3,
    "RangedAttack": 4,
    "CannonAttack": 1,
    "BombardAttack": 2,
    "CaseShotAttack": 3,
    "DefendHandAttack": 1,
    "StaggerHandAttack": 2,
    "VolleyHandAttack": 3,
    "MeleeHandAttack": 4,
    "HandAttack": 5,
    "BuildingAttack": 10,
}


# ============================================================
# String table loader
# ============================================================
def load_string_table(path: Path) -> dict[str, str]:
    tree = ET.parse(path)
    lang = tree.getroot().find("language")
    return {s.get("_locid"): s.text
            for s in lang.findall("string")
            if s.get("_locid") and s.text}


# ============================================================
# Type tag filter
# ============================================================
def should_keep_type(tag: str) -> bool:
    """判断一个 unittype 标签是否应保留在 units.json 的 type 列表中。"""
    if tag in KEEP_TYPE_EXACT:
        return True
    for prefix in KEEP_TYPE_PREFIXES:
        if tag.startswith(prefix):
            return True
    return False


# ============================================================
# Main parser
# ============================================================
def parse_protoy(path: Path, strings_en: dict, strings_zh: dict) -> list[dict]:
    print(f"Parsing {path.name}...")
    tree = ET.parse(path)
    root = tree.getroot()
    units_raw = root.findall("unit")
    print(f"  Total <unit> elements: {len(units_raw)}")

    results = []
    for el in units_raw:
        parsed = parse_unit(el, strings_en, strings_zh)
        if parsed:
            results.append(parsed)

    print(f"  Combat units parsed: {len(results)}")
    return results


def parse_unit(el: ET.Element, strings_en: dict, strings_zh: dict) -> dict | None:
    """Parse a single <unit>. Returns None if not a combat unit."""
    internal_name = el.get("name", "")

    # Collect all unittype tags
    all_types = {ut.text.strip() for ut in el.findall("unittype") if ut.text}

    # Filter: must be a trainable combat unit
    if not _is_combat_unit(el, all_types):
        return None

    # --- ID ---
    uid = internal_name.lower()

    # --- Names ---
    display_name_id = el.findtext("displaynameid", "").strip()
    name_en = strings_en.get(display_name_id, internal_name)
    name_zh = strings_zh.get(display_name_id, name_en)

    # --- Type tags (filtered) ---
    type_tags = sorted(t for t in all_types if should_keep_type(t))

    # --- Age ---
    allowed_age = el.findtext("allowedage", "0").strip()
    age = _age_num_to_name(allowed_age)

    # --- Cost ---
    cost = {}
    for cost_el in el.findall("cost"):
        res_type = cost_el.get("resourcetype", "").lower()
        try:
            amount = round(float(cost_el.text or "0"))
        except ValueError:
            continue
        if amount > 0 and res_type:
            res_map = {"food": "food", "wood": "wood", "gold": "gold",
                       "trade": "export", "fame": "influence"}
            mapped = res_map.get(res_type)
            if mapped:
                cost[mapped] = amount

    # --- Population ---
    pop = round(float(el.findtext("populationcount", "0") or "0"))

    # --- Train time ---
    train_time = round(float(el.findtext("trainpoints", "0") or "0"))

    # --- HP ---
    hp = round(float(el.findtext("maxhitpoints", "0") or "0"))
    if hp <= 0:
        hp = round(float(el.findtext("initialhitpoints", "0") or "0"))

    # --- Speed ---
    speed = round(float(el.findtext("maxvelocity", "0") or "0"), 2)

    # --- LOS ---
    los = round(float(el.findtext("los", "0") or "0"), 1)

    # --- Armor ---
    armor_melee = 0.0
    armor_ranged = 0.0
    armor_siege = 0.0
    for armor_el in el.findall("armor"):
        atype = armor_el.get("type", "")
        aval = float(armor_el.get("value", "0"))
        if atype == "Hand":
            armor_melee = round(aval, 4)
        elif atype == "Ranged":
            armor_ranged = round(aval, 4)
        elif atype == "Siege":
            armor_siege = round(aval, 4)

    # --- Attacks ---
    attacks = _parse_attacks(el)
    ranged = attacks.get("ranged")
    melee = attacks.get("melee")
    siege = attacks.get("siege")

    # --- Build result ---
    result: dict[str, Any] = {
        "id": uid,
        "name_en": name_en,
        "name": name_zh,
        "type": type_tags,
        "civs": [],  # TODO: populate from techtreey.xml
        "age": age,
        "cost": cost,
        "pop": pop,
        "train_time": train_time,
        "hp": hp,
        "speed": speed,
        "los": los,
        "armor_melee": armor_melee,
        "armor_ranged": armor_ranged,
    }
    if armor_siege > 0:
        result["armor_siege"] = armor_siege

    if ranged:
        result["attack_ranged"] = ranged["damage"]
        result["range"] = ranged["maxrange"]
        result["range_min"] = ranged["minrange"]
        result["rof_ranged"] = ranged["rof"]
        result["damage_type_ranged"] = ranged["damagetype"]
        if ranged["aoe_radius"] > 0:
            result["aoe_radius_ranged"] = ranged["aoe_radius"]
        if ranged["multipliers"]:
            result.setdefault("multipliers", {})["ranged"] = ranged["multipliers"]

    if melee:
        result["attack_melee"] = melee["damage"]
        result["range_melee"] = melee["maxrange"]
        result["rof_melee"] = melee["rof"]
        result["damage_type_melee"] = melee["damagetype"]
        if melee["aoe_radius"] > 0:
            result["aoe_radius_melee"] = melee["aoe_radius"]
        if melee["multipliers"]:
            result.setdefault("multipliers", {})["melee"] = melee["multipliers"]

    if siege:
        result["attack_siege"] = siege["damage"]
        result["range_siege"] = siege["maxrange"]
        result["rof_siege"] = siege["rof"]
        if siege["multipliers"]:
            result.setdefault("multipliers", {})["siege"] = siege["multipliers"]

    # AOE radius (max across attacks)
    aoe_vals = [result.get("aoe_radius_ranged", 0), result.get("aoe_radius_melee", 0)]
    max_aoe = max(aoe_vals)
    if max_aoe > 0:
        result["aoe_radius"] = max_aoe

    return result


# ============================================================
# Helpers
# ============================================================

def _is_combat_unit(el: ET.Element, unit_types: set[str]) -> bool:
    """Must have HP, attack, cost, and be a military unit."""
    hp = float(el.findtext("maxhitpoints", "0") or "0")
    if hp <= 0:
        return False

    has_attack = any(
        float(a.findtext("damage") or "0") > 0
        for a in el.findall("protoaction")
    )
    if not has_attack:
        return False

    if not el.findall("cost"):
        return False

    # Exclude projectiles, buildings
    if "EmbellishmentClass" in unit_types or "Projectile" in unit_types:
        return False
    if unit_types & {"AbstractBuilding", "AbstractWall", "AbstractTownCenter",
                     "AbstractDock", "AbstractFort"}:
        return False

    if "Military" not in unit_types and "Unit" not in unit_types:
        return False

    return True


def _age_num_to_name(age_num: str) -> str:
    try:
        n = int(age_num)
    except ValueError:
        return ""
    return {
        0: "Exploration Age",
        1: "Commerce Age",
        2: "Fortress Age",
        3: "Industrial Age",
        4: "Imperial Age",
    }.get(n, "")


def _parse_attacks(el: ET.Element) -> dict[str, dict]:
    """Parse protoaction elements, categorize and select best per slot."""
    ranged_candidates = []
    melee_candidates = []
    siege_candidates = []

    for action in el.findall("protoaction"):
        name = action.findtext("name", "").strip()
        damage = round(float(action.findtext("damage", "0") or "0"), 2)
        if damage <= 0:
            continue

        damagetype = action.findtext("damagetype", "").strip()
        rof = round(float(action.findtext("rof", "3.0") or "3.0"), 4)
        maxrange = round(float(action.findtext("maxrange", "0") or "0"), 2)
        minrange = round(float(action.findtext("minrange", "0") or "0"), 2)
        damagearea = round(float(action.findtext("damagearea", "0") or "0"), 2)
        aoe_radius = round(damagearea) if damagearea > 0 else 0

        # Damage bonuses — store raw type directly
        multipliers = []
        for bonus in action.findall("damagebonus"):
            vs_type = bonus.get("type", "")
            try:
                mult_val = round(float(bonus.text or "1"), 4)
            except ValueError:
                continue
            if mult_val != 1.0 and vs_type:
                multipliers.append({"vs": vs_type, "value": mult_val})

        # Skip non-combat actions
        if any(kw in name for kw in ("Charge", "Trample", "Ability", "AutoGather", "Heal")):
            continue
        if "Build" in name and "Attack" not in name:
            continue

        info = {
            "name": name,
            "damage": damage,
            "damagetype": damagetype,
            "rof": rof,
            "maxrange": maxrange,
            "minrange": minrange,
            "aoe_radius": aoe_radius,
            "multipliers": multipliers,
            "priority": ATTACK_PRIORITY.get(name, 99),
        }

        # Categorize
        is_building_attack = "BuildingAttack" in name
        if is_building_attack:
            siege_candidates.append(info)
        elif damagetype == "Siege" and maxrange > 6:
            ranged_candidates.append(info)
        elif damagetype == "Siege":
            siege_candidates.append(info)
        elif damagetype == "Hand" or maxrange <= 2:
            melee_candidates.append(info)
        elif maxrange > 2:
            ranged_candidates.append(info)
        else:
            melee_candidates.append(info)

    result = {}
    if ranged_candidates:
        ranged_candidates.sort(key=lambda x: x["priority"])
        result["ranged"] = ranged_candidates[0]
    if melee_candidates:
        melee_candidates.sort(key=lambda x: x["priority"])
        result["melee"] = melee_candidates[0]
    if siege_candidates:
        siege_candidates.sort(key=lambda x: x["priority"])
        result["siege"] = siege_candidates[0]
    return result


# ============================================================
# i18n_zh.json generation
# ============================================================
def generate_i18n() -> dict:
    """Generate i18n_zh.json with Abstract tag translations."""
    return {
        "_comment": "AoE3 中英文对照表。key 为游戏原始标签，value 为中文显示名。",

        "type": {
            "AbstractInfantry": "步兵",
            "AbstractHeavyInfantry": "重装步兵",
            "AbstractLightInfantry": "轻型步兵",
            "AbstractRangedInfantry": "远程步兵",
            "AbstractHandInfantry": "近战步兵",
            "AbstractCavalry": "骑兵",
            "AbstractHeavyCavalry": "重装骑兵",
            "AbstractLightCavalry": "轻型骑兵",
            "AbstractRangedCavalry": "远程骑兵",
            "AbstractHandCavalry": "近战骑兵",
            "AbstractRangedHeavyCavalry": "远程重骑兵",
            "AbstractLancer": "枪骑兵",
            "AbstractCoyoteMan": "突击步兵",
            "AbstractRangedShockInfantry": "远程突击步兵",
            "AbstractMusketeer": "火枪兵",
            "AbstractSkirmisher": "散兵",
            "AbstractRifleman": "步枪兵",
            "AbstractPikeman": "长矛兵",
            "AbstractGunpowderTrooper": "火器步兵",
            "AbstractGrenadier": "掷弹兵",
            "AbstractArcher": "弓箭手",
            "AbstractArtillery": "炮兵",
            "AbstractSiegeTrooper": "攻城单位",
            "AbstractWarShip": "战舰",
            "AbstractNativeWarrior": "原住民战士",
            "AbstractOutlaw": "亡命徒",
            "AbstractVillager": "村民",
            "AbstractPet": "宠物",
            "AbstractCavalryInfantry": "反骑步兵",
            "Hero": "英雄",
            "Ship": "船",
            "Mercenary": "雇佣兵",
            "Guardian": "守卫者",
            "Building": "建筑",
            "MercType2": "雇佣兵",
        },

        "multiplier_vs": {
            "AbstractCavalry": "骑兵",
            "AbstractHeavyCavalry": "重装骑兵",
            "AbstractLightCavalry": "轻型骑兵",
            "AbstractInfantry": "步兵",
            "AbstractHeavyInfantry": "重装步兵",
            "AbstractLightInfantry": "轻型步兵",
            "AbstractCoyoteMan": "突击步兵",
            "AbstractRangedShockInfantry": "远程突击步兵",
            "AbstractSkirmisher": "散兵",
            "AbstractCounterSkirmisher": "反散兵",
            "AbstractArtillery": "炮兵",
            "AbstractSiegeTrooper": "攻城单位",
            "AbstractVillager": "村民",
            "AbstractNativeWarrior": "原住民战士",
            "AbstractPet": "宠物",
            "AbstractPikeman": "长矛兵",
            "AbstractWarShip": "战舰",
            "AbstractHandInfantry": "近战步兵",
            "Mercenary": "雇佣兵",
            "MercType2": "雇佣兵",
            "Hero": "英雄",
            "Ship": "船",
            "Building": "建筑",
            "Guardian": "守卫者",
            "AbstractWall": "城墙",
            "AbstractResourceEnclosure": "资源围栏",
            "AbstractDock": "码头",
            "AbstractIndianMonk": "印度僧侣",
            "Huntable": "猎物",
            "Herdable": "牧畜",
        },

        "age": {
            "Exploration Age": "探索时代",
            "Commerce Age": "商业时代",
            "Fortress Age": "要塞时代",
            "Industrial Age": "工业时代",
            "Imperial Age": "帝王时代",
        },

        "cost": {
            "food": "食物",
            "wood": "木材",
            "gold": "金币",
            "export": "出口",
            "influence": "影响力",
        },
    }


# ============================================================
# Main
# ============================================================
def main():
    print("=== AoE3 DE Game Data Parser ===\n")

    strings_en = load_string_table(STRING_EN_PATH)
    strings_zh = load_string_table(STRING_ZH_PATH)
    print(f"String tables: {len(strings_en)} en, {len(strings_zh)} zh")

    units = parse_protoy(PROTOY_PATH, strings_en, strings_zh)
    units.sort(key=lambda u: u["id"])

    # Write units.json
    print(f"\nWriting {OUTPUT_UNITS_PATH}...")
    with open(OUTPUT_UNITS_PATH, "w", encoding="utf-8") as f:
        json.dump(units, f, ensure_ascii=False, indent=2)
    print(f"  {len(units)} units, {OUTPUT_UNITS_PATH.stat().st_size / 1024:.0f} KB")

    # Write i18n_zh.json
    i18n = generate_i18n()
    print(f"Writing {OUTPUT_I18N_PATH}...")
    with open(OUTPUT_I18N_PATH, "w", encoding="utf-8") as f:
        json.dump(i18n, f, ensure_ascii=False, indent=2)
    print("  Done!")

    # Stats
    print(f"\n=== Stats ===")
    print(f"  Total: {len(units)}")
    print(f"  Ranged: {sum(1 for u in units if u.get('attack_ranged'))}")
    print(f"  Melee: {sum(1 for u in units if u.get('attack_melee'))}")
    print(f"  AOE: {sum(1 for u in units if u.get('aoe_radius'))}")

    # Verify multiplier matching
    all_types = set()
    all_vs = set()
    for u in units:
        all_types.update(u.get("type", []))
        for mtype in ("ranged", "melee", "siege"):
            for m in u.get("multipliers", {}).get(mtype, []):
                all_vs.add(m["vs"])

    matchable_vs = {v for v in all_vs if v in all_types}
    orphan_vs = all_vs - all_types
    print(f"\n  Multiplier vs values: {len(all_vs)}")
    print(f"  Matchable (vs in some unit.type): {len(matchable_vs)}")
    print(f"  Orphan (vs not in any unit.type): {len(orphan_vs)}")
    if orphan_vs:
        print(f"    {sorted(orphan_vs)[:15]}...")


if __name__ == "__main__":
    main()
