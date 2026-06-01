"""离线生成通用科技池 seeds/aoe3/generic_techs.json（roguelike 随机研发科技）。

通用科技 = 玩家可研发的「横向」战斗增益（兵工厂/教堂研发 + 本城卡片 + 文明近卫 RG），
区别于单位随时代的纵向 tier 成长（精锐→近卫→帝国 / 印度纪律严明→光荣→高贵，见
aoe3_upgrades_parser.py）。

设计依据 docs/games/aoe3-battle.md §3.10（通用科技）。要点：
  - **作用域白名单**：只收作用于 BROAD_TAGS（真跨兵种大类）的科技，或手工精选的
    SPECIFIC_WHITELIST（特色具体兵：细红线→火枪、旧朝改革→中国兵）、RG 近卫。
    AbstractSepoy/Rajput/Sowar 等**窄单兵标签**是文明纵向 tier（已由 tier 模块处理），
    不在 BROAD_TAGS，自动排除，避免横向再叠一遍 = 双重成长。
  - **结构去重取最强**：各文明同质的「骑兵战斗力 +X% 血攻」按 (作用域, 效果结构) 合并，
    保留数值最强一条；机制独立的（燧发=+血 / 纸包弹=+攻 / 半回旋 / 细红线…）各自保留。
  - 排除：tier、革命、SPC、Team 队伍卡、SetAge、Age0 自动档；土著/亡命徒/佣兵类别
    （类别模块已处理）；vs 建筑/船/英雄倍率与「带具体 action 的伤害」（场上无目标/拆动作）。
  - op 保留 action 原文：通用科技作用于标签，落 ranged/melee 槽要在运行时按每个具体单位
    的代表动作（protoaction_ranged/melee）决定。
  - **匹配校验**：每条科技的 scope 必须能命中 units.json 真实单位，否则丢弃。
  - age：研发科技读 prereq；卡片 prereq 多解不出 → 启发式（Church=2、RG=4、卡片=3）。
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import scripts.crawler.aoe3_upgrades_parser as P  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "aoe3" / "raw"
OUT = ROOT / "seeds" / "aoe3" / "generic_techs.json"

# 真·跨兵种大类（通用科技只收作用于这些标签的；窄单兵标签如 AbstractSepoy 是文明 tier，排除）
BROAD_TAGS = {
    "AbstractInfantry", "AbstractCavalry", "AbstractArtillery",
    "AbstractHeavyInfantry", "AbstractLightInfantry", "AbstractRangedInfantry",
    "AbstractHandInfantry", "AbstractFootArcher", "AbstractRifleman",
    "AbstractMusketeer", "AbstractPikeman", "AbstractGrenadier",
    "AbstractHeavyCavalry", "AbstractLightCavalry", "AbstractRangedCavalry",
    "AbstractHandCavalry", "AbstractGunpowderTrooper", "AbstractDragoon",
    "AbstractLancer", "AbstractAbusGun",
}
# 手工精选的特色具体兵科技（按**科技 id**放行其具体兵 target；按兵 id 放行会误收同兵的纵向 tier）
TECH_WHITELIST = {
    "ChurchThinRedLine",        # 细红线：火枪 +20血 −10速
    "YPHCOldHanArmyReforms",    # 旧朝改革：中国连弩/长矛/怯薛/草原骑兵 +50血攻
}
# 场上无目标的倍率维度（vs 建筑/船/英雄/墙）
DEAD_VS = {"AbstractShip", "Ship", "Building", "AbstractBuilding", "Wall", "AbstractWall",
           "Huntable", "AbstractHuntable", "Tower",
           "Guardian", "AbstractGuardian"}
TIER_PREFIX = ("Veteran", "Guard", "Imperial", "Champion", "Legendary", "Elite")

COMBAT_SUB = {"Hitpoints": "hp", "HitPoints": "hp", "Damage": "damage",
              "DamageBonus": "mult", "ArmorSpecific": "armor", "MaximumRange": "range",
              "DamageArea": "aoe", "RateOfFire": "rof", "MaximumVelocity": "speed"}


def load_stringtable() -> dict[str, str]:
    st = (RAW / "stringtabley_zh.xml").read_text(encoding="utf-8")
    return dict(re.findall(r'<string _locid="(\d+)"[^>]*>(.*?)</string>', st, re.S))


def is_tier(name: str) -> bool:
    base = re.sub(r"^(DE|YP|XP|de|yp|xp)", "", name)
    return base.startswith(TIER_PREFIX)


def is_royal_guard(name: str) -> bool:
    return name.startswith(("RG", "DERG", "DEHCRG", "XPRG", "YPRG"))


def classify_source(name: str, flags: set[str]) -> str:
    if is_royal_guard(name):
        return "RoyalGuard"
    if "church" in name.lower():
        return "Church"
    if "HomeCity" in flags:
        return "HomeCity"
    return "Arsenal"


def op_from_effect(attrs: str, sub: str) -> dict | None:
    """把单条 effect 规整成 op（保留 action 供运行时分槽）；无效返回 None。"""
    stat = COMBAT_SUB[sub]
    rel = P._attr(attrs, "relativity")
    amount = P._attr(attrs, "amount")
    if amount is None:
        return None
    amt = float(amount)
    action = P._attr(attrs, "action")
    allact = P._attr(attrs, "allactions") == "1"
    vs = P._attr(attrs, "unittype")

    if stat in ("hp", "damage"):
        # 伤害只收整体动作（allactions/无 action）：带具体 action 的多是
        # 拆动作或 vs 建筑伤害（如「掠夺」action=BuildingAttack），场上无意义。
        if stat == "damage" and action and not allact:
            return None
        if rel == "BasePercent" and amt > 1.0:
            return {"stat": stat, "kind": "mult", "value": round(amt, 4),
                    "action": action, "allactions": allact}
        if rel == "Absolute" and amt > 0:
            return {"stat": stat, "kind": "add", "value": round(amt, 3),
                    "action": action, "allactions": allact}
        return None
    if stat == "range" and rel == "Absolute" and amt > 0:
        return {"stat": "range", "kind": "add", "value": round(amt, 3),
                "action": action, "allactions": allact}
    if stat == "aoe" and rel == "Absolute" and amt > 0:
        return {"stat": "aoe", "kind": "add", "value": round(amt, 3),
                "action": action, "allactions": allact}
    if stat == "rof" and rel == "Assign" and amt > 0:
        return {"stat": "rof", "kind": "set", "value": round(amt, 3),
                "action": action, "allactions": allact}
    if stat == "speed":
        # 含减速（双刃升级如细红线 −10% 速）如实计入
        if rel == "BasePercent" and amt > 0 and abs(amt - 1.0) > 1e-9:
            return {"stat": "speed", "kind": "mult", "value": round(amt, 4)}
        if rel == "Absolute" and abs(amt) > 1e-9:
            return {"stat": "speed", "kind": "add", "value": round(amt, 3)}
        if rel == "Assign" and amt > 0:
            return {"stat": "speed", "kind": "set", "value": round(amt, 3)}
        return None
    if stat == "armor" and rel == "Absolute" and amt > 0:
        kind = P.ARMOR_KIND.get(P._attr(attrs, "newtype") or "")
        if kind:
            return {"stat": "armor", "kind": "add", "value": round(amt, 3), "armor_kind": kind}
        return None
    if stat == "mult":
        # 倍率：只取对正倍率的 Absolute 加成，且 vs 必须是场上可能存在的目标
        if rel == "Absolute" and amt > 0 and vs and vs not in DEAD_VS:
            return {"stat": "mult", "kind": "add", "value": round(amt, 3),
                    "vs": vs, "action": action, "allactions": allact}
        return None
    return None


def full_sig(op: dict) -> tuple:
    return (op["stat"], op["kind"], op["value"], op.get("action") or "",
            op.get("allactions", False), op.get("vs") or "", op.get("armor_kind") or "",
            op.get("resource") or "")


def struct_sig(op: dict) -> tuple:
    """效果结构（去掉数值），用于同质卡合并。"""
    return (op["stat"], op["kind"], op.get("action") or "",
            op.get("allactions", False), op.get("vs") or "", op.get("armor_kind") or "",
            op.get("resource") or "")


def gain_score(t: dict) -> float:
    """粗略增益度量，用于同结构组取最强（减速等扣分自然落选）。"""
    s = 0.0
    for o in t["ops"]:
        v = o["value"]
        if o["kind"] == "mult":
            s += (v - 1.0)
        elif o["kind"] == "add":
            s += v * 0.1
    return s


def resolve_age(name: str, source: str, resolver) -> int:
    a = resolver.resolve(name)
    if a is not None:
        return a
    if source == "Church":
        return 2
    if source == "RoyalGuard":
        return 4
    return 3  # 卡片 prereq 解不出 → 默认 age3


def build(stringtable: dict[str, str]) -> dict:
    text = (RAW / "techtreey.xml").read_text(encoding="utf-8")
    units = json.loads((ROOT / "seeds" / "aoe3" / "units.json").read_text("utf-8"))
    valid_ids = {u["id"] for u in units}
    # 标签 → 命中单位 id（用于匹配校验）
    tag_index: dict[str, list[str]] = defaultdict(list)
    for u in units:
        for tag in u.get("type", []):
            tag_index[tag].append(u["id"])
    blocks = P.parse_tech_blocks(text)
    resolver = P.AgeResolver(blocks)

    raw: list[dict] = []
    for name, block in blocks.items():
        flags = P.tech_flags(block)
        low = name.lower()
        if low.startswith(("rev", "derev", "dehcrev", "derevolution")):
            continue
        if "RevoltTech" in flags or "Team" in name or "SPC" in name:
            continue
        if name.startswith(("Age0", "DEAge0", "Colonialize", "Fortressize",
                             "Industrialize", "Imperialize")):
            continue
        is_card = "HomeCity" in flags
        is_research = bool({"UpgradeTech", "UniqueTech"} & flags)
        if not (is_card or is_research):
            continue
        if is_tier(name) or P.has_setage(block):
            continue

        source = classify_source(name, flags)
        rg = source == "RoyalGuard"
        allow_specific = name in TECH_WHITELIST
        ops_by_sig: dict[tuple, dict] = {}
        scope: set[str] = set()
        for attrs, target in P.iter_effects(block):
            if target is None or P._attr(attrs, "type") != "Data":
                continue
            sub = P._attr(attrs, "subtype")

            # Cost 效果：影响造价 → 影响阵容数量
            if sub == "Cost":
                rel = P._attr(attrs, "relativity")
                amt_s = P._attr(attrs, "amount")
                res = P._attr(attrs, "resource")
                if not amt_s or not res or rel != "BasePercent":
                    continue
                amt = float(amt_s)
                if abs(amt - 1.0) < 1e-9:
                    continue
                tl = target.lower()
                if tl in valid_ids:
                    if not (rg or allow_specific):
                        continue
                    store = tl
                elif target in BROAD_TAGS:
                    store = target
                else:
                    continue
                op = {"stat": "cost", "kind": "mult", "value": round(amt, 4),
                      "resource": res.lower()}
                ops_by_sig[full_sig(op)] = op
                scope.add(store)
                continue

            if sub not in COMBAT_SUB:
                continue
            tl = target.lower()
            # 作用域白名单：广谱大类 / RG 近卫 / 手工放行的特色科技。
            # 具体兵 id 统一存小写（与 units.json 一致，避免大小写漏匹配）。
            if tl in valid_ids:
                if not (rg or allow_specific):
                    continue
                store = tl
            elif target in BROAD_TAGS:
                store = target
            else:
                continue
            op = op_from_effect(attrs, sub)
            if op is None:
                continue
            ops_by_sig[full_sig(op)] = op  # 同 effect 去重（旧朝改革对 4 兵重复 hp/dmg）
            scope.add(store)
        ops = list(ops_by_sig.values())
        if not ops or not scope:
            continue

        age = resolve_age(name, source, resolver)
        m = re.search(r"<displaynameid>(\d+)</displaynameid>", block)
        nm = stringtable.get(m.group(1), name) if m else name
        nm = re.sub(r"<[^>]+>", "", nm).strip() or name
        if nm.startswith("队伍"):  # 团队卡（英文名未必含 Team），不纳入
            continue
        raw.append({"id": name, "name_zh": nm, "source": source, "age": age,
                    "scope": sorted(scope), "ops": ops})

    # RG-as-tier 过滤：RG 如果 hp 加成 ≥30%（如乌鲁菲利斯 +40%），说明它就是该兵的 tier
    # 近卫线本身（已被 unit_upgrades.json 消化），不是叠在通用近卫之上的横向加成。
    _rg_filtered = []
    for t in raw:
        if t["source"] == "RoyalGuard":
            hp_ops = [o for o in t["ops"] if o["stat"] == "hp" and o["kind"] == "mult"]
            if hp_ops and max(o["value"] for o in hp_ops) >= 1.3:
                continue
        _rg_filtered.append(t)
    raw = _rg_filtered

    # 结构去重取最强：同 (作用域集合, 效果结构集合) 仅保留增益最强一条
    by_struct: dict[tuple, dict] = {}
    for t in raw:
        key = (frozenset(t["scope"]), frozenset(struct_sig(o) for o in t["ops"]))
        cur = by_struct.get(key)
        if cur is None:
            by_struct[key] = t
        else:
            keep = max((cur, t), key=lambda x: (gain_score(x), _name_rank(x)))
            keep["age"] = min(cur["age"], t["age"])
            by_struct[key] = keep

    # 匹配校验：scope 必须命中真实单位
    techs: list[dict] = []
    dropped: list[str] = []
    for t in by_struct.values():
        hit = set()
        for s in t["scope"]:
            if s in valid_ids:
                hit.add(s)
            else:
                hit.update(tag_index.get(s, []))
        if not hit:
            dropped.append(f"{t['name_zh']}({t['id']}) scope={t['scope']}")
            continue
        t["match_count"] = len(hit)
        techs.append(t)

    techs.sort(key=lambda x: (x["age"], x["source"], x["id"]))
    return {
        "_meta": {
            "source": "techtreey.xml",
            "note": "通用科技池（roguelike，横向加成）。BROAD_TAGS+特色兵白名单收窄，"
                    "按 (scope,效果结构) 去重取最强。op 保留 action，运行时按单位代表动作分槽。"
                    "age 对卡片为启发式估计。",
            "count": len(techs),
            "dropped_unmatched": dropped,
        },
        "techs": techs,
    }


def _name_rank(t: dict) -> tuple:
    zh = t["name_zh"] != t["id"]
    src = {"Church": 3, "Arsenal": 3, "RoyalGuard": 2, "HomeCity": 1}.get(t["source"], 0)
    return (zh, src)


def _op_desc(o: dict) -> str:
    if o["stat"] in ("hp", "damage") and o["kind"] == "mult":
        return f"{o['stat']}×{o['value']}"
    if o["stat"] == "speed":
        return f"速{o['kind']}{o['value']}"
    if o["stat"] == "mult":
        return f"倍率vs{o['vs'].replace('Abstract', '')}+{o['value']}"
    if o["stat"] == "armor":
        return f"{o.get('armor_kind')}甲+{o['value']}"
    return f"{o['stat']}{o['kind']}{o['value']}"


def write_preview(data: dict, path: Path) -> None:
    lines = [f"通用科技池：{data['_meta']['count']} 条"]
    by_age = defaultdict(list)
    for t in data["techs"]:
        by_age[t["age"]].append(t)
    for age in sorted(by_age):
        lines.append(f"\n========== age {age} ==========")
        for t in sorted(by_age[age], key=lambda x: x["source"]):
            scope = "/".join(s.replace("Abstract", "") for s in t["scope"])
            ops = "; ".join(_op_desc(o) for o in t["ops"])
            lines.append(f"  [{t['source']:<10}] {t['name_zh']}  «{scope}»  {ops}  "
                         f"(命中{t['match_count']}兵)")
    if data["_meta"]["dropped_unmatched"]:
        lines.append("\n--- 因无法匹配单位而丢弃 ---")
        lines.extend("  " + d for d in data["_meta"]["dropped_unmatched"])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    st = load_stringtable()
    data = build(st)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_preview(data, ROOT / "scripts" / "_tmp_generic_preview.txt")
    print(f"wrote {OUT}  ({data['_meta']['count']} techs, "
          f"dropped {len(data['_meta']['dropped_unmatched'])})")


if __name__ == "__main__":
    main()
