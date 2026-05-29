"""AoE3 DE Game Data Parser — 从 data/aoe3/raw/ 生成 seeds/aoe3/units.json。

权威源（入库 git，由 extractor 从游戏 BAR 灌库）：
  - data/aoe3/raw/protoy.xml
  - data/aoe3/raw/tactics/*.tactics
  - data/aoe3/raw/anims/**/*.xml
  - data/aoe3/raw/stringtabley_*.xml

用法:
  uv run python scripts/crawler/aoe3_gamedata_parser.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ============================================================
# 路径
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "aoe3" / "raw"
EXTRACTED_DIR = Path(os.environ.get("AOE3_EXTRACTED_DIR", str(DEFAULT_RAW_DIR)))
SEEDS_DIR = PROJECT_ROOT / "seeds" / "aoe3"
DATA_AOE3_DIR = PROJECT_ROOT / "data" / "aoe3"

PROTOY_PATH = EXTRACTED_DIR / "protoy.xml"
STRING_EN_PATH = EXTRACTED_DIR / "stringtabley_en.xml"
STRING_ZH_PATH = EXTRACTED_DIR / "stringtabley_zh.xml"
TACTICS_DIR = EXTRACTED_DIR / "tactics"
ANIMS_DIR = EXTRACTED_DIR / "anims"

OUTPUT_UNITS_PATH = SEEDS_DIR / "units.json"
OUTPUT_I18N_PATH = SEEDS_DIR / "i18n_zh.json"
OUTPUT_MANIFEST_PATH = DATA_AOE3_DIR / "manifest.json"

ART_UNITS_BAR = Path(os.environ.get(
    "AOE3_ART_UNITS_BAR",
    r"E:\SteamLibrary\steamapps\common\AoE3DE\Game\Art\ArtUnits.bar",
))


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
# 攻击动作名优先级（选择"标准"姿态 / 主攻击）
# 数字越小越优先；不在列表中的 = 99
#
# 远程/近战统一层级：
#   齐射 Volley > 交错 Stagger > 具名主攻击（无 Volley/Stagger 后缀的主循环）
#   > 防御 Defend（手动阵型，置底）
# 全员统一 Volley > Stagger；多数纯骑兵 protoy 仅有 StaggerRangedAttack，
# 无齐射动作时自然落回交错，与「骑兵常用交错」一致。
# 炮兵等另表（打兵模式优先于打建筑）
# ============================================================

TIER_VOLLEY = 20
TIER_STAGGER = 21
TIER_NAMED_RANGED = 22   # + 在 NAMED_RANGED_ATTACK_ORDER 中的下标
TIER_DEFEND_RANGED = 32
# 具名远程：无 Volley/Stagger 后缀的常态主武器（弓骑 Bow、火枪 Rifle、船 Ranged 等）
NAMED_RANGED_ATTACK_ORDER = [
    "BowAttack",
    "RifleAttack",
    "BlunderbussAttack",
    "LongRangeAttack",
    "RangedAttack",
]
# 英雄技 / 一次性射击 / 召唤类 — 不进斗蛐蛐 DPS 循环
NON_DPS_RANGED_ATTACKS = frozenset({
    "SharpshooterAttack",
    "CrackshotAttack",
    "SwashbucklerAttack",
    "HeavenlyFireBomb",
    "Stun",
    "Chaos",
})

ARTILLERY_RANGED_PRIORITY = {
    "BarrageAttack": 40,
    "RepeatingAttack": 41,
    "CannonAttack": 42,
    "BombardAttack": 43,
    "CaseShotAttack": 44,
    "MortarAttack": 45,
}

TIER_VOLLEY_HAND = 1
TIER_STAGGER_HAND = 2
TIER_NAMED_MELEE = 3     # + 在 NAMED_MELEE_ATTACK_ORDER 中的下标
TIER_DEFEND_HAND = 13
# 具名近战：同上，在齐射/交错之后、防御之前
NAMED_MELEE_ATTACK_ORDER = [
    "MeleeHandAttack",
    "BayonetAttack",
    "HandAttack",
]


def _primary_ranged_stances(unit_types: set[str]) -> tuple[str, str]:
    """返回 (第一优先姿态, 第二优先姿态)。全员齐射 > 交错。"""
    return ("VolleyRangedAttack", "StaggerRangedAttack")


def _ranged_attack_priority(name: str, unit_types: set[str]) -> int:
    if name in ARTILLERY_RANGED_PRIORITY:
        return ARTILLERY_RANGED_PRIORITY[name]
    volley, stagger = _primary_ranged_stances(unit_types)
    if name == volley:
        return TIER_VOLLEY
    if name == stagger:
        return TIER_STAGGER
    if name in NAMED_RANGED_ATTACK_ORDER:
        return TIER_NAMED_RANGED + NAMED_RANGED_ATTACK_ORDER.index(name)
    if name == "DefendRangedAttack":
        return TIER_DEFEND_RANGED
    return 99


def _melee_hand_priority(name: str) -> int:
    if name == "VolleyHandAttack":
        return TIER_VOLLEY_HAND
    if name == "StaggerHandAttack":
        return TIER_STAGGER_HAND
    if name in NAMED_MELEE_ATTACK_ORDER:
        return TIER_NAMED_MELEE + NAMED_MELEE_ATTACK_ORDER.index(name)
    if name == "DefendHandAttack":
        return TIER_DEFEND_HAND
    return 99


# 兼容旧引用（siege 等）
ATTACK_PRIORITY = {
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

    rollover_id = el.findtext("rollovertextid", "").strip()
    short_rollover_id = el.findtext("shortrollovertextid", "").strip()
    description_en = strings_en.get(rollover_id, "").strip() if rollover_id else ""
    description_zh = strings_zh.get(rollover_id, "").strip() if rollover_id else ""
    if not description_en and short_rollover_id:
        description_en = strings_en.get(short_rollover_id, "").strip()
    if not description_zh and short_rollover_id:
        description_zh = strings_zh.get(short_rollover_id, "").strip()

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
    tactics_filename = el.findtext("tactics", "").strip()
    attacks = _parse_attacks(el, tactics_filename, all_types)
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

    if description_en:
        result["description_en"] = description_en
    if description_zh:
        result["description"] = description_zh

    if ranged:
        result["protoaction_ranged"] = ranged["name"]
        result["attack_ranged"] = ranged["damage"]
        result["range"] = ranged["maxrange"]
        result["range_min"] = ranged["minrange"]
        result["rof_ranged"] = ranged["rof"]
        result["damage_type_ranged"] = ranged["damagetype"]
        if ranged.get("num_projectiles", 1) > 1:
            result["num_projectiles_ranged"] = ranged["num_projectiles"]
        if ranged["aoe_radius"] > 0:
            result["aoe_radius_ranged"] = ranged["aoe_radius"]
        if ranged.get("damage_cap", 0) > 0:
            result["damage_cap_ranged"] = ranged["damage_cap"]
        if ranged["multipliers"]:
            result.setdefault("multipliers", {})["ranged"] = ranged["multipliers"]

    if melee:
        result["protoaction_melee"] = melee["name"]
        result["attack_melee"] = melee["damage"]
        result["range_melee"] = melee["maxrange"]
        result["rof_melee"] = melee["rof"]
        result["damage_type_melee"] = melee["damagetype"]
        if melee.get("num_projectiles", 1) > 1:
            result["num_projectiles_melee"] = melee["num_projectiles"]
        if melee["aoe_radius"] > 0:
            result["aoe_radius_melee"] = melee["aoe_radius"]
        if melee.get("damage_cap", 0) > 0:
            result["damage_cap_melee"] = melee["damage_cap"]
        if melee["multipliers"]:
            result.setdefault("multipliers", {})["melee"] = melee["multipliers"]

    if siege:
        result["attack_siege"] = siege["damage"]
        result["range_siege"] = siege["maxrange"]
        result["rof_siege"] = siege["rof"]
        if siege["multipliers"]:
            result.setdefault("multipliers", {})["siege"] = siege["multipliers"]

    # --- Windup（逐动作名；不展示，供模拟器/数据用）---
    windups = _parse_windups(el, tactics_filename)
    if windups:
        result["windups"] = windups
        if ranged and ranged["name"] in windups:
            result["windup_ranged"] = windups[ranged["name"]]
        if melee and melee["name"] in windups:
            result["windup_melee"] = windups[melee["name"]]

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


# ============================================================
# Tactics loader — displayednumberprojectiles + anim 名
# ============================================================
# 缓存：tactics filename → {action_name → {"anim": str, "projectiles": int}}
_tactics_cache: dict[str, dict[str, dict[str, Any]]] = {}


def _load_tactics_actions(tactics_filename: str) -> dict[str, dict[str, Any]]:
    """Load tactics file → {action_name: {anim, projectiles?, maxrange?, minrange?}}."""
    if tactics_filename in _tactics_cache:
        return _tactics_cache[tactics_filename]

    result: dict[str, dict[str, Any]] = {}
    tactics_path = TACTICS_DIR / tactics_filename
    if not tactics_path.exists():
        _tactics_cache[tactics_filename] = result
        return result

    try:
        tree = ET.parse(tactics_path)
        root = tree.getroot()
        for action in root.findall("action"):
            aname = action.findtext("name", "").strip()
            if not aname:
                continue
            entry: dict[str, Any] = {}
            anim = action.findtext("anim", "").strip()
            if anim:
                entry["anim"] = anim
            dnp = action.findtext("displayednumberprojectiles", "")
            if dnp:
                try:
                    val = int(dnp.strip())
                    if val > 1:
                        entry["projectiles"] = val
                except ValueError:
                    pass
            for range_key in ("maxrange", "minrange"):
                raw = action.findtext(range_key, "").strip()
                if not raw:
                    continue
                try:
                    val = round(float(raw), 2)
                    if val > 0:
                        entry[range_key] = val
                except ValueError:
                    pass
            if entry:
                result[aname] = entry
    except ET.ParseError:
        pass

    _tactics_cache[tactics_filename] = result
    return result


def _load_tactics(tactics_filename: str) -> dict[str, int]:
    """Load a tactics file and return {action_name: displayednumberprojectiles}."""
    actions = _load_tactics_actions(tactics_filename)
    return {
        name: meta["projectiles"]
        for name, meta in actions.items()
        if meta.get("projectiles")
    }


# ============================================================
# Anim windup — data/aoe3/raw/anims/ 优先，ArtUnits.bar 回退
# ============================================================
_anim_bar_entries: dict[str, dict] | None = None
_anim_xml_cache: dict[str, str] = {}


def _animfile_local_path(animfile: str) -> Path:
    return ANIMS_DIR / animfile.replace("\\", "/")


def _get_anim_units_entries() -> dict[str, dict]:
    global _anim_bar_entries
    if _anim_bar_entries is not None:
        return _anim_bar_entries
    if not ART_UNITS_BAR.exists():
        _anim_bar_entries = {}
        return _anim_bar_entries
    from aoe3_bar_extractor import read_bar_entries
    _anim_bar_entries = {e["name"]: e for e in read_bar_entries(str(ART_UNITS_BAR))}
    return _anim_bar_entries


def _animfile_to_bar_path(animfile: str) -> str:
    return animfile.replace("/", "\\") + ".XMB"


def _load_unit_anim_xml(animfile: str) -> str | None:
    if not animfile:
        return None
    if animfile in _anim_xml_cache:
        cached = _anim_xml_cache[animfile]
        return cached or None

    local_path = _animfile_local_path(animfile)
    if local_path.is_file():
        xml_text = local_path.read_text(encoding="utf-8")
        _anim_xml_cache[animfile] = xml_text
        return xml_text

    if not ART_UNITS_BAR.exists():
        _anim_xml_cache[animfile] = ""
        return None

    bar_path = _animfile_to_bar_path(animfile)
    entries = _get_anim_units_entries()
    entry = entries.get(bar_path)
    if not entry:
        _anim_xml_cache[animfile] = ""
        return None
    from aoe3_bar_extractor import decode_xmb_to_xml, extract_file_data
    xml_text = decode_xmb_to_xml(extract_file_data(str(ART_UNITS_BAR), entry))
    _anim_xml_cache[animfile] = xml_text
    return xml_text


def _extract_windup_sec(anim_xml: str, anim_name: str) -> float | None:
    """从 unit anim XML 读取指定 <anim> 块内 tag type=Attack 的秒数。"""
    pattern = re.compile(
        rf"<anim>\s*{re.escape(anim_name)}\s*(.*?)</anim>",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(anim_xml)
    if not m:
        return None
    tag_m = re.search(r'<tag\s+type="Attack">([^<]+)</tag>', m.group(1))
    if not tag_m:
        return None
    try:
        return round(float(tag_m.group(1).strip()), 4)
    except ValueError:
        return None


def _parse_windups(el: ET.Element, tactics_filename: str) -> dict[str, float]:
    """对每个 protoaction 动作名，从 tactics→anim 解 windup；解不出则省略该动作。"""
    if not tactics_filename:
        return {}
    animfile = (el.findtext("animfile") or "").strip()
    if not animfile:
        return {}
    anim_xml = _load_unit_anim_xml(animfile)
    if not anim_xml:
        return {}

    tactics_actions = _load_tactics_actions(tactics_filename)
    windups: dict[str, float] = {}
    for action in el.findall("protoaction"):
        name = action.findtext("name", "").strip()
        if not name:
            continue
        meta = tactics_actions.get(name)
        if not meta or not meta.get("anim"):
            continue
        sec = _extract_windup_sec(anim_xml, meta["anim"])
        if sec is not None:
            windups[name] = sec
    return windups


def _parse_attacks(
    el: ET.Element, tactics_filename: str = "", unit_types: set[str] | None = None,
) -> dict[str, dict]:
    """Parse protoaction elements, categorize and select best per slot.

    tactics_filename: 该单位引用的 tactics 文件名（如 "chukonu.tactics"），
    用于读取 displayednumberprojectiles（每次攻击的弹丸数）。
    unit_types: unittype 标签集合，用于远程姿态默认（步兵 Volley / 骑兵 Stagger）。
    """
    if unit_types is None:
        unit_types = set()
    tactics_actions = _load_tactics_actions(tactics_filename) if tactics_filename else {}
    tactics_proj = {
        name: meta["projectiles"]
        for name, meta in tactics_actions.items()
        if meta.get("projectiles")
    }

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
        tact = tactics_actions.get(name, {})
        if maxrange <= 0 and tact.get("maxrange", 0) > 0:
            maxrange = round(float(tact["maxrange"]), 2)
        if minrange <= 0 and tact.get("minrange", 0) > 0:
            minrange = round(float(tact["minrange"]), 2)
        damagearea = round(float(action.findtext("damagearea", "0") or "0"), 2)
        aoe_radius = round(damagearea) if damagearea > 0 else 0
        damagecap = round(float(action.findtext("damagecap", "0") or "0"), 2)

        # Projectile count from tactics (displayednumberprojectiles)
        num_projectiles = tactics_proj.get(name, 1)

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

        # Skip non-combat actions and hero skills (斗蛐蛐只用常态 DPS 循环)
        if any(kw in name for kw in ("Charge", "Trample", "Ability", "AutoGather", "Heal")):
            continue
        if name in NON_DPS_RANGED_ATTACKS:
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
            "damage_cap": damagecap,
            "num_projectiles": num_projectiles,
            "multipliers": multipliers,
        }

        # Categorize — 只看动作名 + maxrange，不看 damagetype
        # （攻击类型与伤害类型正交：近战骑兵可以打 Siege 伤害，远程炮可以打 Hand 伤害）
        # 判定优先级：动作名 > 射程阈值
        #   - 含 BuildingAttack → siege
        #   - 含 HandAttack → melee（长矛/流星锤 range 可达 4~5 仍为近战）
        #   - 含 RangedAttack → ranged（火绳枪骑兵 range=6 为远程射击）
        #   - 其余按 maxrange < 6 → melee，>= 6 → ranged
        if "BuildingAttack" in name:
            siege_candidates.append(info)
        elif "HandAttack" in name:
            melee_candidates.append(info)
        elif "RangedAttack" in name:
            ranged_candidates.append(info)
        elif maxrange < 6:
            melee_candidates.append(info)
        else:
            ranged_candidates.append(info)

    result = {}
    if ranged_candidates:
        # maxrange<=0 的 *RangedAttack 在 protoy 里是占位/继承，不能作远程槽代表。
        valid_ranged = [c for c in ranged_candidates if c["maxrange"] > 0]
        if valid_ranged:
            for c in valid_ranged:
                c["priority"] = _ranged_attack_priority(c["name"], unit_types)
            valid_ranged.sort(key=lambda x: x["priority"])
            result["ranged"] = valid_ranged[0]
    if melee_candidates:
        for c in melee_candidates:
            c["priority"] = _melee_hand_priority(c["name"])
        melee_candidates.sort(key=lambda x: x["priority"])
        result["melee"] = melee_candidates[0]
    if siege_candidates:
        for c in siege_candidates:
            c["priority"] = ATTACK_PRIORITY.get(c["name"], 99)
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

        "tags": {
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
            "AbstractCounterSkirmisher": "反散兵",
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
            "AbstractIndianMonk": "印度僧侣",
            "AbstractWall": "城墙",
            "AbstractResourceEnclosure": "资源围栏",
            "AbstractDock": "码头",
            "AbstractCamel": "骆驼骑兵",
            "AbstractElephant": "象兵",
            "AbstractHandElephant": "近战象兵",
            "AbstractSiegeElephant": "攻城象",
            "AbstractFootArcher": "步弓手",
            "AbstractGunpowderCavalry": "火枪骑兵",
            "AbstractHandCavalryMerc": "近战骑兵佣兵",
            "AbstractHandInfantryMerc": "近战步兵佣兵",
            "AbstractHandSiege": "近战攻城单位",
            "AbstractHealer": "治疗者",
            "AbstractMonk": "僧侣",
            "AbstractChineseMonk": "中国僧侣",
            "AbstractJapaneseMonk": "日本僧侣",
            "AbstractAfricanHero": "非洲英雄",
            "AbstractMeleeSkirmisher": "近战散兵",
            "AbstractTrainingShip": "训练船",
            "Hero": "英雄",
            "Ship": "船",
            "Mercenary": "雇佣兵",
            "MercType2": "雇佣兵",
            "Guardian": "守卫者",
            "Building": "建筑",
            "Huntable": "猎物",
            "Herdable": "牧畜",
            "Llama": "羊驼",
            "TradingPost": "贸易站",
            "UnitClass": "单位",
            "LogicalTypeLandMilitary": "陆军",
            "LogicalTypeLandEconomy": "经济单位",
            "xpArrowKnight": "弓箭骑士",
            "xpLakotaWarchief": "拉科塔战酋",
            "xpRifleRider": "步枪骑士",
            "deIncaWarChief": "印加战酋",
            "deMalteseGun": "马耳他炮",
            "deMercGatlingCamel": "加特林骆驼",
            "deREVGranadero": "掷弹骑兵",
            "ypShrineJapanese": "日本神社",
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
# Manifest
# ============================================================
def _git_head() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def write_manifest(units_count: int) -> None:
    anim_files = list(ANIMS_DIR.rglob("*.xml")) if ANIMS_DIR.is_dir() else []
    tactics_files = list(TACTICS_DIR.glob("*.tactics")) if TACTICS_DIR.is_dir() else []
    manifest = {
        "raw_dir": str(EXTRACTED_DIR.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "combat_units": units_count,
        "protoy_bytes": PROTOY_PATH.stat().st_size if PROTOY_PATH.is_file() else 0,
        "tactics_files": len(tactics_files),
        "anim_files": len(anim_files),
    }
    DATA_AOE3_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ============================================================
# Main
# ============================================================
def main():
    print("=== AoE3 DE Game Data Parser ===")
    print(f"Raw dir: {EXTRACTED_DIR}\n")

    if not PROTOY_PATH.is_file():
        raise SystemExit(f"protoy.xml not found: {PROTOY_PATH}")

    strings_en = load_string_table(STRING_EN_PATH)
    strings_zh = load_string_table(STRING_ZH_PATH)
    print(f"String tables: {len(strings_en)} en, {len(strings_zh)} zh")

    units = parse_protoy(PROTOY_PATH, strings_en, strings_zh)
    units.sort(key=lambda u: u["id"])

    # Write units.json
    print(f"\nWriting {OUTPUT_UNITS_PATH}...")
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_UNITS_PATH, "w", encoding="utf-8") as f:
        json.dump(units, f, ensure_ascii=False, indent=2)
    print(f"  {len(units)} units, {OUTPUT_UNITS_PATH.stat().st_size / 1024:.0f} KB")

    # Write i18n_zh.json
    i18n = generate_i18n()
    print(f"Writing {OUTPUT_I18N_PATH}...")
    with open(OUTPUT_I18N_PATH, "w", encoding="utf-8") as f:
        json.dump(i18n, f, ensure_ascii=False, indent=2)
    print("  Done!")

    write_manifest(len(units))
    print(f"Writing {OUTPUT_MANIFEST_PATH}...")

    # Stats
    print(f"\n=== Stats ===")
    print(f"  Total: {len(units)}")
    print(f"  Ranged: {sum(1 for u in units if u.get('attack_ranged'))}")
    print(f"  Melee: {sum(1 for u in units if u.get('attack_melee'))}")
    print(f"  AOE: {sum(1 for u in units if u.get('aoe_radius'))}")
    print(f"  damage_cap: {sum(1 for u in units if u.get('damage_cap_ranged') or u.get('damage_cap_melee'))}")
    print(f"  description: {sum(1 for u in units if u.get('description'))}")
    print(f"  windups: {sum(1 for u in units if u.get('windups'))}")
    windup_actions = sum(len(u.get('windups', {})) for u in units)
    print(f"  windup action entries: {windup_actions}")

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
