"""红警2斗蛐蛐 —— 中文展示名（QQ 群消息用，与 OpenRA 英文 yaml 导出分离）。"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parents[4] / "data" / "ra2" / "locale_zh.json"

# 常见武器内部 id → 简短中文（未收录则只显示伤害/射程）
_WEAPON_ZH: dict[str, str] = {
    "M60": "步枪",
    "M60E": "精英步枪",
    "para": "机枪碉堡",
    "paraE": "精英机枪碉堡",
    "MP5": "冲锋枪",
    "MP5E": "精英冲锋枪",
    "105mm": "105mm 炮",
    "105mmE": "精英 105mm 炮",
    "120mm": "120mm 炮",
    "120mmE": "精英 120mm 炮",
    "120mmx": "双管炮",
    "120mmxE": "精英双管炮",
    "155mm": "155mm 炮",
    "155mmE": "精英 155mm 炮",
    "20mm": "20mm 机炮",
    "20mme": "精英 20mm 机炮",
    "20mmrapid": "20mm 机炮",
    "20mmrapidE": "精英 20mm 机炮",
    "FlakGuyGun": "高射炮",
    "FlakGuyAAGun": "防空炮",
    "CRM60": "步枪",
    "CRMP5": "冲锋枪",
    "CR105mm": "105mm 炮",
    "CR120mm": "120mm 炮",
    "CRRadBeamWeapon": "辐射束",
    "CRRadBeamWeaponE": "精英辐射束",
    "CRTeslaZap": "磁能电弧",
    "CRTeslaZapE": "精英磁能电弧",
    "CRPrism": "光棱束",
    "CRPrismE": "精英光棱束",
    "MindControl": "心灵控制",
    "DogJaw": "撕咬",
    "NeutronRifle": "中子步枪",
    "DiskLaser": "激光",
    "DiskDrain": "吸取",
    "HornetBomb": "炸弹",
    "ASWBomb": "反潜弹",
    "SubTorpedo": "鱼雷",
    "Missile": "导弹",
    "MissileE": "精英导弹",
    "Medusa": "导弹",
    "MedusaE": "精英导弹",
    "Dragon": "导弹",
    "DragonE": "精英导弹",
    "DoublePistols": "双枪",
    "DoublePistolsE": "精英双枪",
    "awp": "狙击枪",
    "awpe": "精英狙击枪",
}


def _translate_description_en_to_zh(text: str) -> str:
    """将 OpenRA 英文 Description 粗略译为群消息可读中文（无 locale 条目时的兜底）。"""
    if not text.strip():
        return ""
    t = text.replace("\\n", "\n")
    repl = [
        (r"\bStrong vs\s*", "强对："),
        (r"\bWeak vs\s*", "弱对："),
        (r"\bSpecial [Aa]bility:\s*", "特殊："),
        (r"\bSpecial ability:\s*", "特殊："),
        (r"\bUnarmed\b", "无武器"),
        (r"\bInfantry\b", "步兵"),
        (r"\bVehicles?\b", "车辆"),
        (r"\bAircraft\b", "飞行器"),
        (r"\bShips?\b", "舰艇"),
        (r"\bStructures?\b", "建筑"),
        (r"\bBuildings?\b", "建筑"),
        (r"\bGeneral-purpose\b", "通用"),
        (r"\bAnti-infantry\b", "反步兵"),
        (r"\bAnti-Air\b", "防空"),
        (r"\bnaval unit\b", "海军单位"),
        (r"\bMain Battle Tank\b", "主战坦克"),
        (r"\bAdvanced Battle Tank\b", "先进主战坦克"),
    ]
    for pat, sub in repl:
        t = re.sub(pat, sub, t, flags=re.IGNORECASE)
    lines = [re.sub(r"\s+", " ", ln.strip()) for ln in t.split("\n") if ln.strip()]
    return " / ".join(lines[:3])


@lru_cache(maxsize=1)
def _load_locale() -> dict:
    if not _DATA.is_file():
        return {"actors": {}, "weapons": {}}
    raw = json.loads(_DATA.read_text(encoding="utf-8"))
    return {
        "actors": raw.get("actors") or {},
        "weapons": {**_WEAPON_ZH, **(raw.get("weapons") or {})},
    }


def localized_actor_name(actor_id: str, fallback: str) -> str:
    entry = _load_locale()["actors"].get(actor_id)
    if entry and entry.get("name"):
        return str(entry["name"])
    return fallback


def localized_actor_description(actor_id: str, fallback: str) -> str:
    entry = _load_locale()["actors"].get(actor_id)
    if entry and entry.get("description"):
        return str(entry["description"]).replace("\\n", "\n")
    return _translate_description_en_to_zh(fallback)


def localized_weapon_label(weapon_id: str) -> str:
    zh = _load_locale()["weapons"].get(weapon_id)
    if zh:
        return zh
    # 去掉常见前缀，避免 CR/AG 等内部代号
    label = weapon_id
    if label.startswith("CR"):
        label = label[2:]
    if label.endswith("E") and len(label) > 2:
        return f"精英{label[:-1]}"
    return label


def locale_actor_ids() -> frozenset[str]:
    return frozenset(_load_locale()["actors"].keys())
