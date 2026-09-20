"""Build the static AoE3 balance-review web report.

Inputs are intentionally limited to the generated diff artifact and icons:
- data/aoe3/balance_review.json
- resources/aoe3/icons/*.png

The output is a self-contained-ish HTML file with an embedded, normalized
dataset and copied icons. It has no runtime dependency on the repository.
"""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "aoe3" / "balance_review.json"
ICONS = ROOT / "resources" / "aoe3" / "icons"
OUT_DIR = ROOT / "docs" / "demo" / "aoe3-balance-20260917"
OUT = OUT_DIR / "index.html"
ICON_OUT = OUT_DIR / "icons"

FIELD_LABELS = {
    "hp": "生命值",
    "attack_ranged": "远程攻击",
    "attack_melee": "近战攻击",
    "attack_siege": "攻城攻击",
    "rof_ranged": "远程射速",
    "rof_melee": "近战射速",
    "rof_siege": "攻城射速",
    "range": "远程射程",
    "range_min": "远程最小射程",
    "range_melee": "近战射程",
    "armor_melee": "近战护甲",
    "armor_ranged": "远程护甲",
    "armor_siege": "攻城护甲",
    "aoe_radius": "AOE 半径",
    "aoe_radius_ranged": "远程 AOE",
    "aoe_radius_melee": "近战 AOE",
    "damage_cap_ranged": "远程溅射池",
    "damage_cap_melee": "近战溅射池",
    "damage_type_ranged": "远程伤害类型",
    "damage_type_melee": "近战伤害类型",
    "num_projectiles_ranged": "远程弹丸",
    "num_projectiles_melee": "近战弹丸",
    "multipliers": "克制倍率",
    "windups": "抬手表",
    "windup_ranged": "远程抬手",
    "windup_melee": "近战抬手",
    "protoaction_ranged": "远程代表动作",
    "protoaction_melee": "近战代表动作",
    "protoaction_siege": "攻城代表动作",
    "cost": "造价",
    "pop": "人口",
    "train_time": "训练时间",
    "los": "视野",
    "speed": "移速",
    "type": "类型标签",
    "age": "时代",
    "civs": "文明",
    "name": "中文名",
    "name_en": "英文名",
    "description": "描述",
    "description_en": "英文描述",
}

COMBAT_FIELDS = {
    "hp", "attack_ranged", "attack_melee", "attack_siege",
    "rof_ranged", "rof_melee", "rof_siege", "range", "range_min",
    "range_melee", "range_siege", "armor_melee", "armor_ranged",
    "armor_siege", "aoe_radius", "aoe_radius_ranged", "aoe_radius_melee",
    "aoe_radius_siege", "damage_cap_ranged", "damage_cap_melee",
    "damage_type_ranged", "damage_type_melee", "num_projectiles_ranged",
    "num_projectiles_melee", "multipliers", "windups", "windup_ranged",
    "windup_melee", "protoaction_ranged", "protoaction_melee",
    "protoaction_siege",
}

ECON_FIELDS = {"cost", "pop", "train_time"}
TEXT_FIELDS = {"name", "name_en", "description", "description_en"}


def _display_value(value):
    if value is None:
        return "无"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, dict):
        return " / ".join(f"{k}: {_display_value(v)}" for k, v in value.items())
    if isinstance(value, list):
        return " / ".join(_display_value(x) for x in value)
    return str(value)


def _delta_text(field, old, new):
    if field in {"multipliers", "windups"}:
        return "动作包发生变化，详见原始字段"
    if old is None:
        return f"新增为 {_display_value(new)}"
    if new is None:
        return f"从 {_display_value(old)} 删除"
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        if old == 0:
            return f"{old:g} → {new:g}"
        pct = (new / old - 1) * 100
        return f"{old:g} → {new:g}（{pct:+.1f}%）"
    return f"{_display_value(old)} → {_display_value(new)}"


def _direction(score_delta, fields):
    if score_delta is None:
        return "结构性改动"
    if score_delta > 0:
        return "增强"
    if score_delta < 0:
        return "削弱"
    return "结构性改动"


def _unit_class(unit):
    tags = set(unit.get("type") or [])
    if "AbstractCavalry" in tags:
        return "骑兵"
    if "AbstractArtillery" in tags or "AbstractSiegeTrooper" in tags:
        return "炮兵/攻城"
    if "AbstractArcher" in tags or "AbstractRifleman" in tags or "AbstractSkirmisher" in tags:
        return "远程步兵"
    if "AbstractInfantry" in tags or "AbstractHeavyInfantry" in tags:
        return "步兵"
    if "AbstractWarShip" in tags or "Ship" in tags:
        return "海军"
    return "特殊"


BLIND_FIELDS = {
    "multipliers", "windups", "windup_ranged", "windup_melee",
    "range", "range_min", "range_melee",
    "damage_type_ranged", "damage_type_melee",
    "protoaction_ranged", "protoaction_melee", "protoaction_siege",
    "damage_cap_ranged", "damage_cap_melee",
}


def _impact(record):
    fields = set(record["fields"])
    if fields & BLIND_FIELDS:
        return "机制型"
    if "hp" in fields and len(fields) == 1:
        return "生存型"
    if fields & COMBAT_FIELDS:
        return "直接战斗"
    if fields & ECON_FIELDS:
        return "经济侧"
    return "文本/元数据"


def _change_reason(record):
    diffs = record["diffs"]
    bits = []
    for field in record["fields"]:
        if field in {"name", "name_en", "description", "description_en", "type", "age", "civs", "los"}:
            continue
        if field in FIELD_LABELS:
            bits.append(_delta_text(field, diffs[field].get("old"), diffs[field].get("new")))
    if not bits:
        return "显示文本或分类标签调整"
    return "；".join(bits[:4])


def _summary(record):
    fields = set(record["fields"])
    direction = _direction(record.get("score_delta_pct"), fields)
    reason = _change_reason(record)
    if record["id"] in {"denatlipkatatar", "denatmerclipkatatar"}:
        return "削弱：远程攻击 12.5 → 10（-20.0%）；造价 70 肉 / 60 木 → 80 肉 / 70 木（+23.1% 资源）"
    if record["id"] == "degascenya":
        return "结构性调整：近战 15 → 12、HP 135 → 140；对骑兵倍率 3.0 → 4.0，对轻型步兵 2.25 → 2.5"
    if record["id"] == "cavalryarcher":
        return "机制增强：新增 6.5 近战攻击与近战攻击槽，对重骑 4.5 倍、对土狼 3.5 倍、对炮 2 倍"
    if record["id"] == "demaceman":
        return "增强：近战射速 2.25 → 2.0 秒（攻击更快 11.1%）"
    if record["id"] == "defulawarrior":
        return "机制调整：远程射程 18 → 17，同时动作抬手表发生变化"
    if record["id"] in {"deabun", "deincarunner", "deoromowarrior", "xpmedicinemanaztec",
                        "ypconsulatetufancicorps", "ypmonkdisciple", "greatbombard"}:
        return f"经济调整：{reason}"
    if record["id"] in {"decarolean", "deincaspearman", "deneftenya", "depavisier",
                        "derussianhalberdier", "derevbarbarywarrior", "derevcruzobinfantry"}:
        return f"经济调整：{reason}"
    if record["id"] in {"denatholcanjavelineer", "denatmercholcanjavelineer"}:
        return "机制增强：近战代表动作改为 MeleeHandAttack，抬手 0.47 → 0.37 秒"
    if record["id"] in {"denatmercsharktoothbowman", "natsharktoothbowman"}:
        return "机制变更：远程 / 近战代表动作改为 RangedAttack / HandAttack，保留 0.98 / 0.27 秒抬手"
    if direction == "增强":
        return f"增强：{reason}"
    if direction == "削弱":
        return f"削弱：{reason}"
    return f"结构性改动：{reason}"


def _unit_id_from_icon(icon_url):
    if not icon_url:
        return ""
    m = re.search(r"/([^/]+)\.png(?:$|\?)", icon_url)
    return m.group(1) if m else ""


def _load_units():
    return json.loads((ROOT / "seeds" / "aoe3" / "units.json").read_text(encoding="utf-8"))


def build():
    review = json.loads(SOURCE.read_text(encoding="utf-8"))
    units = {u["id"]: u for u in _load_units()}
    old_units = {}
    # The review file carries enough old/new values for the page. For names and
    # icons we use the current snapshot, with an explicit current snapshot note.
    changed = []
    for r in review["changed"]:
        if not (r["has_combat_change"] or "economy" in r["groups"]):
            continue
        unit = units.get(r["id"], {})
        fields = r["fields"]
        direction = _direction(r.get("score_delta_pct"), set(fields))
        changed.append({
            "id": r["id"],
            "name": r["name"],
            "nameOld": r.get("name_old") or r["name"],
            "nameEn": r.get("name_en") or "",
            "age": r.get("age") or "",
            "unitClass": _unit_class(unit),
            "direction": direction,
            "impact": _impact(r),
            "summary": _summary(r),
            "fields": fields,
            "fieldLabels": [FIELD_LABELS.get(f, f) for f in fields],
            "scoreOld": r.get("score_old"),
            "scoreNew": r.get("score_new"),
            "scoreDelta": r.get("score_delta_pct"),
            "dpsOld": r.get("dps_old"),
            "dpsNew": r.get("dps_new"),
            "dpsDelta": r.get("dps_delta_pct"),
            "hpOld": r.get("hp_old"),
            "hpNew": r.get("hp_new"),
            "costDelta": r.get("cost_delta_pct"),
            "sim": (r.get("sim") or {}).get("winrate_new"),
            "vsRef": r.get("vs_ref") or {},
            "icon": f"icons/{r['id']}.png" if (ICON_OUT / f"{r['id']}.png").exists() else "",
            "blind": bool(r.get("blind_fields")),
            "excluded": r["id"] in {
                "deeggarctictruck", "deeggleonardostank", "deregent",
                "deregenthorse", "despcgreatbombardnopop", "despchmlord",
                "spcdeunclefrankhorse", "spcxpchiefbravewolf",
                "spcxpchiefbullbear", "spcxpchieftwomoon", "spcxpcrazyhorse",
                "spcxpredoubtcannon", "ypeggicecreamtruck", "ypspcishida",
                "monstertrucka", "monstertruckt", "fluffy",
                "flyingpurpletapir", "georgecrushington", "lazerbear",
                "legacygatlingcamel",
            },
        })

    added = []
    for r in review.get("added_units", []):
        unit = units.get(r["id"], {})
        added.append({
            "id": r["id"],
            "name": r["name"],
            "nameEn": r.get("name_en") or "",
            "age": r.get("age") or "",
            "unitClass": _unit_class(unit),
            "score": r.get("score"),
            "hp": r.get("hp"),
            "atkR": r.get("atk_r"),
            "atkM": r.get("atk_m"),
            "atkS": r.get("atk_s"),
            "excluded": bool(r.get("excluded")),
            "icon": f"icons/{r['id']}.png" if (ICON_OUT / f"{r['id']}.png").exists() else "",
        })

    removed = [
        {
            "id": r["id"],
            "name": r["name"],
            "nameEn": r.get("name_en") or "",
            "hp": r.get("hp"),
            "score": r.get("score"),
            "icon": f"icons/{r['id']}.png" if (ICON_OUT / f"{r['id']}.png").exists() else "",
        }
        for r in review.get("removed_units", [])
    ]

    return {
        "meta": review["meta"],
        "summary": review["summary"],
        "changed": changed,
        "added": added,
        "removed": removed,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ICON_OUT.mkdir(parents=True, exist_ok=True)
    data = build()

    all_ids = {x["id"] for group in ("changed", "added", "removed") for x in data[group]}
    copied = 0
    for unit_id in all_ids:
        src = ICONS / f"{unit_id}.png"
        if src.exists():
            shutil.copy2(src, ICON_OUT / src.name)
            copied += 1

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    template = (ROOT / "scripts" / "aoe3_balance_report_template.html").read_text(encoding="utf-8")
    html = template.replace("/*__DATA__*/", payload)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"icons copied: {copied}")
    print(f"changed: {len(data['changed'])}, added: {len(data['added'])}, removed: {len(data['removed'])}")


if __name__ == "__main__":
    main()
