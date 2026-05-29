"""AoE3 单位改良（科技加成）Parser —— 从 techtreey.xml 生成 unit_upgrades.json。

权威源：data/aoe3/raw/techtreey.xml（升级科技）+ seeds/aoe3/units.json（合法 id/标签）。

产物：seeds/aoe3/unit_upgrades.json
  {
    "_meta": {...},
    "units": { "<id>": { "3": {"hp_mult":1.2,"damage_mult":1.2}, "4":..., "5":... } },
    "category": { "AbstractOutlaw": {...}, "Mercenary": {...}, "AbstractNativeWarrior": {...} }
  }

设计依据：docs/games/aoe3-battle.md §3.10。要点：
  - 候选 = 可研究 UpgradeTech ∪ 通用 Shadow 自动档（类别另含 AgeUpgrade 政客线）。
  - 按 prereq 解时代（Colonialize=2/Fortressize=3/Industrialize=4/Imperialize=5）；
    解不出时代（如文明专属 Age0* 空 prereq）→ 丢弃。
  - 排除 HomeCity 卡、革命 Rev*。
  - 逐时代「只选一条」：同档多变体取增量最大者（通用线 ≥ RG/和平者）。
  - BasePercent 增量累加：cumulative(ageN) = 1 + Σ 各档增量。
  - Damage 用 allactions=1 → 远近一致缩放。

用法：
  uv run python scripts/crawler/aoe3_upgrades_parser.py
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TECHTREE_PATH = PROJECT_ROOT / "data" / "aoe3" / "raw" / "techtreey.xml"
UNITS_PATH = PROJECT_ROOT / "seeds" / "aoe3" / "units.json"
OUTPUT_PATH = PROJECT_ROOT / "seeds" / "aoe3" / "unit_upgrades.json"

# 升时代状态 → 游戏时代号（与 units.json age 名口径一致：探索1/商业2/要塞3/工业4/帝王5）
AGE_STATUS = {
    "Colonialize": 2,
    "Fortressize": 3,
    "Industrialize": 4,
    "Imperialize": 5,
}

# 类别科技标签（按标签匹配，不按 id）
CATEGORY_TAGS = ("AbstractOutlaw", "AbstractNativeWarrior", "Mercenary")

# 佣兵唯一的逐时代加成来自升帝王政客（AgeUpgrade，靠 SetAge 定时代）。
# 政客是「一档一选」的文明选项，自动扫描会混入文明专属政客（如 FederalNewYork +25），
# 故对佣兵走精选 allowlist；其余政客（SetAge）一律排除出自动扫描。详见 §3.10.4。
MERC_AGEUPGRADE_ALLOW = {"DEPoliticianMercContractor"}

# 我们改良的 subtype（血/攻）。relativity 只接受 BasePercent（增量累加）。
SUBTYPE_HP = {"Hitpoints", "HitPoints"}
SUBTYPE_DMG = {"Damage"}

# ArmorSpecific newtype → Unit 护甲字段（Hand=近战吃，Ranged=远程吃）
ARMOR_KIND = {"Hand": "melee", "Melee": "melee", "Ranged": "ranged"}

# 离谱占位值黑名单（按 tech × subtype 精确点名，不用一刀切数值上限，以免误伤真实大改良）。
# 已知：DEEliteSlingersShadow 给投石手「齐射」+147 射程（同 tech 其余姿势才 +7）= 占位/bug；
# 它恰好在投石手精锐主升级线上，不能整条拉黑（会丢 +血攻），故只点名这一条 effect。
# 实测：全候选范围内被点名的离谱值仅此 1 条。将来如发现新占位值，在此追加。
# 详见 docs/games/aoe3-battle.md §3.10.2。
DIRTY_EFFECTS = {
    ("DEEliteSlingersShadow", "MaximumRange"),
}


def _attr(attrs: str, key: str) -> str | None:
    m = re.search(rf'{key}="([^"]*)"', attrs)
    return m.group(1) if m else None


def parse_tech_blocks(text: str) -> dict[str, str]:
    """name -> inner xml。"""
    return dict(re.findall(r'<tech name="([^"]+)"[^>]*>(.*?)</tech>', text, re.DOTALL))


def tech_flags(block: str) -> set[str]:
    return set(re.findall(r"<flag>([^<]+)</flag>", block))


def tech_prereq_status(block: str) -> list[str]:
    return re.findall(r'<techstatus[^>]*>([^<]+)</techstatus>', block)


def tech_setage(block: str) -> int | None:
    """<effect type="SetAge">AgeN</effect> → 游戏时代号（Age0=1 … Age4=5）。"""
    m = re.search(r'<effect type="SetAge">Age(\d)</effect>', block)
    return int(m.group(1)) + 1 if m else None


def has_setage(block: str) -> bool:
    return "<effect type=\"SetAge\">" in block


def iter_effects(block: str):
    """yield (attrs, target_proto|None) for each <effect> in block."""
    for m in re.finditer(r"<effect\b([^>]*?)(?:/>|>(.*?)</effect>)", block, re.DOTALL):
        attrs = m.group(1)
        inner = m.group(2) or ""
        tgt = re.search(r'<target type="ProtoUnit">([^<]+)</target>', inner)
        yield attrs, (tgt.group(1) if tgt else None)


def hp_dmg_increments(block: str, want_target_lower: str):
    """返回 (hp_inc, dmg_inc)：amount-1 的增量；无则 None。

    want_target_lower：要匹配的 ProtoUnit 名（小写）。
    Damage 仅接受 allactions=1 或无 action 限定（避免拆动作）。
    """
    hp_inc = None
    dmg_inc = None
    for attrs, target in iter_effects(block):
        if target is None or target.lower() != want_target_lower:
            continue
        if _attr(attrs, "type") != "Data":
            continue
        if _attr(attrs, "relativity") != "BasePercent":
            continue
        subtype = _attr(attrs, "subtype")
        amount = _attr(attrs, "amount")
        if amount is None:
            continue
        inc = float(amount) - 1.0
        if inc <= 0:
            continue  # 只取正向加成；amount<1 的削弱/置换不属于「改良」
        if subtype in SUBTYPE_HP:
            hp_inc = inc if hp_inc is None else max(hp_inc, inc)
        elif subtype in SUBTYPE_DMG:
            # 仅整体动作（allactions）或无 action 限定
            if _attr(attrs, "action") and _attr(attrs, "allactions") != "1":
                continue
            dmg_inc = inc if dmg_inc is None else max(dmg_inc, inc)
    return hp_inc, dmg_inc


def _slots_for_action(action: str | None, allactions: str | None, u: dict) -> list[str]:
    """effect 的 action 命中哪些槽（仅 ranged/melee；siege 斗蛐蛐不用）。

    按攻击数据铁律：**只认代表动作**（units.json 的 protoaction_ranged/melee）。
    allactions=1 或无 action → 落该兵实际拥有的所有槽；
    action 不等于任一代表动作（如 Defend/Stagger/BuildingAttack 变体）→ 不计，
    避免把同一 effect 的多条动作变体重复相加。
    """
    if allactions == "1" or not action:
        slots = []
        if u.get("attack_ranged"):
            slots.append("ranged")
        if u.get("attack_melee"):
            slots.append("melee")
        return slots
    if action == u.get("protoaction_ranged"):
        return ["ranged"]
    if action == u.get("protoaction_melee"):
        return ["melee"]
    return []


def tech_extra_effects(block: str, u: dict, tech_name: str = "") -> dict:
    """从**单条**代表科技提取 range/aoe/rof/速度/护甲/倍率 的单档效果（未累加）。

    仅取 target==该兵 id 或 target∈该兵 type 标签 的 effect；按代表动作落槽。
    relativity 决定数学：Absolute→delta、Assign→override、BasePercent→倍率。
    带代价升级（如 +血 −速）**如实计入副作用**，不只取好处；离谱占位值按
    DIRTY_EFFECTS 精确丢弃。
    """
    uid = u["id"].lower()
    types = set(u.get("type", []))
    out = {
        "range_add": {}, "aoe_add": {}, "rof_set": {}, "armor_add": {}, "mult_add": {},
        "speed_add": 0.0, "speed_mult": 1.0, "speed_set": None,
    }
    for attrs, target in iter_effects(block):
        if target is None:
            continue
        if target.lower() != uid and target not in types:
            continue
        if _attr(attrs, "type") != "Data":
            continue
        sub = _attr(attrs, "subtype")
        rel = _attr(attrs, "relativity")
        amount = _attr(attrs, "amount")
        if amount is None:
            continue
        amt = float(amount)
        action = _attr(attrs, "action")
        allact = _attr(attrs, "allactions")

        if (tech_name, sub) in DIRTY_EFFECTS:
            continue  # 已知占位/bug 值，精确点名丢弃（如投石手 +147 射程）
        if sub == "MaximumRange" and rel == "Absolute" and amt > 0:
            for s in _slots_for_action(action, allact, u):
                out["range_add"][s] = out["range_add"].get(s, 0.0) + amt
        elif sub == "DamageArea" and rel == "Absolute" and amt > 0:
            for s in _slots_for_action(action, allact, u):
                out["aoe_add"][s] = out["aoe_add"].get(s, 0.0) + amt
        elif sub == "RateOfFire" and rel == "Assign" and amt > 0:
            for s in _slots_for_action(action, allact, u):
                out["rof_set"][s] = amt  # 覆盖（攻速直接置值）
        elif sub == "MaximumVelocity":
            # 如实计入副作用：细红线式「+血 −速」的减速必须照减，不只取好处
            if rel == "Absolute" and amt != 0:
                out["speed_add"] += amt
            elif rel == "BasePercent" and amt > 0:
                out["speed_mult"] *= amt  # 含 <1（减速）
            elif rel == "Assign" and amt > 0:
                out["speed_set"] = amt
        elif sub == "ArmorSpecific" and rel == "Absolute" and amt > 0:
            kind = ARMOR_KIND.get(_attr(attrs, "newtype") or "")
            if kind:
                out["armor_add"][kind] = out["armor_add"].get(kind, 0.0) + amt
        elif sub == "DamageBonus" and rel == "Absolute" and amt > 0:
            # 倍率：只对「已存在的正倍率 vs <unittype>」做加法（§3.10.2）
            vs = _attr(attrs, "unittype")
            if vs:
                for s in _slots_for_action(action, allact, u):
                    out["mult_add"].setdefault(s, {})
                    out["mult_add"][s][vs] = out["mult_add"][s].get(vs, 0.0) + amt
    return out


def _accumulate_extras(picked_tech: dict[int, str], blocks: dict, u: dict) -> dict[str, dict]:
    """沿选定科技链按时代累加 extras，返回 {age: {extra字段...}}（cumulative）。"""
    per_age = {age: tech_extra_effects(blocks[picked_tech[age]], u, picked_tech[age])
               for age in picked_tech}
    range_add: dict[str, float] = {}
    aoe_add: dict[str, float] = {}
    armor_add: dict[str, float] = {}
    mult_add: dict[str, dict[str, float]] = {}
    rof_set: dict[str, float] = {}
    speed_add = 0.0
    speed_mult = 1.0
    speed_set = None
    out: dict[str, dict] = {}
    for age in sorted(per_age):
        ex = per_age[age]
        for s, v in ex["range_add"].items():
            range_add[s] = range_add.get(s, 0.0) + v
        for s, v in ex["aoe_add"].items():
            aoe_add[s] = aoe_add.get(s, 0.0) + v
        for k, v in ex["armor_add"].items():
            armor_add[k] = armor_add.get(k, 0.0) + v
        for s, dd in ex["mult_add"].items():
            mult_add.setdefault(s, {})
            for vs, v in dd.items():
                mult_add[s][vs] = mult_add[s].get(vs, 0.0) + v
        for s, v in ex["rof_set"].items():
            rof_set[s] = v  # 高档覆盖低档
        speed_add += ex["speed_add"]
        speed_mult *= ex["speed_mult"]
        if ex["speed_set"] is not None:
            speed_set = ex["speed_set"]

        entry: dict = {}
        clean = {s: round(v, 3) for s, v in range_add.items() if abs(v) > 1e-9}
        if clean:
            entry["range_add"] = clean
        clean = {s: round(v, 3) for s, v in aoe_add.items() if abs(v) > 1e-9}
        if clean:
            entry["aoe_add"] = clean
        clean = {k: round(v, 3) for k, v in armor_add.items() if abs(v) > 1e-9}
        if clean:
            entry["armor_add"] = clean
        if rof_set:
            entry["rof_set"] = dict(rof_set)
        if abs(speed_add) > 1e-9:
            entry["speed_add"] = round(speed_add, 3)
        if abs(speed_mult - 1.0) > 1e-9:
            entry["speed_mult"] = round(speed_mult, 4)
        if speed_set is not None:
            entry["speed_set"] = round(speed_set, 3)
        m_clean = {s: {vs: round(v, 3) for vs, v in dd.items() if abs(v) > 1e-9}
                   for s, dd in mult_add.items()}
        m_clean = {s: dd for s, dd in m_clean.items() if dd}
        if m_clean:
            entry["mult_add"] = m_clean
        if entry:
            out[str(age)] = entry
    return out


class AgeResolver:
    def __init__(self, blocks: dict[str, str]):
        self.blocks = blocks
        self._memo: dict[str, int | None] = {}

    def resolve(self, name: str, _seen: frozenset[str] = frozenset()) -> int | None:
        if name in self._memo:
            return self._memo[name]
        block = self.blocks.get(name)
        if block is None:
            return None
        # 政客升时代科技：时代写在 SetAge，不在 prereq
        setage = tech_setage(block)
        if setage is not None:
            self._memo[name] = setage
            return setage
        statuses = tech_prereq_status(block)
        direct = [AGE_STATUS[s] for s in statuses if s in AGE_STATUS]
        if direct:
            self._memo[name] = max(direct)
            return self._memo[name]
        # 递归：prereq 指向另一条科技
        sub: list[int] = []
        for s in statuses:
            if s in self.blocks and s not in _seen:
                a = self.resolve(s, _seen | {name})
                if a:
                    sub.append(a)
        self._memo[name] = max(sub) if sub else None
        return self._memo[name]


def is_excluded(name: str, flags: set[str]) -> bool:
    """排除主城卡、革命、文明专属。"""
    if "HomeCity" in flags:
        return True
    if "RevoltTech" in flags:
        return True
    # 革命科技（含 DEREV*/DEHCREV* 等 Shadow 变体，大小写不一）：单位转换的副作用
    # （如减速）不是正经升级，排除。
    low = name.lower()
    if low.startswith(("rev", "derev", "dehcrev", "derevolution")):
        return True
    # 文明专属自动档：空 prereq 的 Shadow（Age0*）会因解不出时代被丢弃，
    # 这里再加名字前缀兜底，挡住带 civ age-up 的 Shadow（如 ImperializeDutch）
    if name.startswith(("Age0", "DEAge0", "Colonialize", "Fortressize",
                        "Industrialize", "Imperialize")):
        return True
    return False


def is_candidate_flags(flags: set[str], *, allow_age_upgrade: bool) -> bool:
    if "UpgradeTech" in flags or "Shadow" in flags:
        return True
    if allow_age_upgrade and "AgeUpgrade" in flags:
        return True
    return False


# 逐时代选链优先级：通用线（Veteran/Guard/Imperial 前缀）优于 RG/其他
def _line_priority(name: str) -> int:
    base = re.sub(r"^(DE|YP|XP|de|yp|xp)", "", name)
    if base.startswith(("Veteran", "Guard", "Imperial", "Champion", "Legendary")):
        return 0
    if name.startswith("RG"):
        return 2
    return 1


def build_unit_upgrades(blocks, resolver, units_by_id):
    """返回 {id: {age: {hp_mult, damage_mult, range_add, ...}}}（cumulative）。"""
    valid_ids = set(units_by_id)
    # 收集：id -> age -> list[(line_priority, hp_inc, dmg_inc, tech_name)]
    per_id: dict[str, dict[int, list]] = {}
    for name, block in blocks.items():
        flags = tech_flags(block)
        if is_excluded(name, flags):
            continue
        # 政客升时代科技（SetAge）= 玩家级一档一选选项，不作逐兵升级
        if has_setage(block):
            continue
        if not is_candidate_flags(flags, allow_age_upgrade=False):
            continue
        age = resolver.resolve(name)
        if age is None or age not in (2, 3, 4, 5):
            continue
        # 找出该 tech 命中的合法单位 id（target=ProtoUnit 且在 units.json）
        targets = {t for _, t in iter_effects(block) if t}
        for tgt in targets:
            tid = tgt.lower()
            if tid not in valid_ids:
                continue
            hp_inc, dmg_inc = hp_dmg_increments(block, tid)
            if not hp_inc and not dmg_inc:
                continue
            per_id.setdefault(tid, {}).setdefault(age, []).append(
                (_line_priority(name), hp_inc or 0.0, dmg_inc or 0.0, name)
            )

    # 逐时代选一条：通用线优先，其次增量大者
    result: dict[str, dict] = {}
    for tid, by_age in per_id.items():
        picks: dict[int, tuple[float, float]] = {}
        picked_tech: dict[int, str] = {}
        for age, cands in by_age.items():
            cands.sort(key=lambda c: (c[0], -(c[1] + c[2])))
            picks[age] = (cands[0][1], cands[0][2])
            picked_tech[age] = cands[0][3]
        base = _accumulate(picks)
        # 整包：从同一条代表科技提取 range/aoe/rof/速度/护甲/倍率，按链累加后合并
        extras = _accumulate_extras(picked_tech, blocks, units_by_id[tid])
        for age_str, ex in extras.items():
            base.setdefault(age_str, {}).update(ex)
        if base:
            result[tid] = base
    return result


def build_category_upgrades(blocks, resolver):
    """返回 {tag: {age: {hp_mult, damage_mult}}}（cumulative），按标签匹配。"""
    out: dict[str, dict] = {}
    for tag in CATEGORY_TAGS:
        tag_lower = tag.lower()
        is_merc = tag == "Mercenary"
        by_age: dict[int, list] = {}
        for name, block in blocks.items():
            flags = tech_flags(block)
            if is_excluded(name, flags):
                continue
            if has_setage(block):
                # 政客升时代：佣兵走精选 allowlist；其余类别一律不取政客
                if not (is_merc and name in MERC_AGEUPGRADE_ALLOW):
                    continue
            elif not is_candidate_flags(flags, allow_age_upgrade=False):
                continue
            age = resolver.resolve(name)
            if age is None or age not in (2, 3, 4, 5):
                continue
            hp_inc, dmg_inc = hp_dmg_increments(block, tag_lower)
            if not hp_inc and not dmg_inc:
                continue
            by_age.setdefault(age, []).append((hp_inc or 0.0, dmg_inc or 0.0, name))
        if not by_age:
            continue
        picks: dict[int, tuple[float, float]] = {}
        for age, cands in by_age.items():
            # 同档取增量最大（通用线/Shadow 近卫 > 和平者 +10）
            cands.sort(key=lambda c: -(c[0] + c[1]))
            picks[age] = (cands[0][0], cands[0][1])
        out[tag] = _accumulate(picks)
    return out


def _accumulate(picks: dict[int, tuple[float, float]]) -> dict[str, dict]:
    """picks: age -> (hp_inc, dmg_inc) → cumulative mult per age（含低档累加）。"""
    out: dict[str, dict] = {}
    hp_cum = 1.0
    dmg_cum = 1.0
    for age in sorted(picks):
        hp_inc, dmg_inc = picks[age]
        hp_cum += hp_inc
        dmg_cum += dmg_inc
        entry = {}
        if abs(hp_cum - 1.0) > 1e-9:
            entry["hp_mult"] = round(hp_cum, 4)
        if abs(dmg_cum - 1.0) > 1e-9:
            entry["damage_mult"] = round(dmg_cum, 4)
        if entry:
            out[str(age)] = entry
    return out


def main():
    print("=== AoE3 单位改良 Parser ===")
    text = TECHTREE_PATH.read_text(encoding="utf-8")
    units = json.loads(UNITS_PATH.read_text(encoding="utf-8"))
    units_by_id = {u["id"]: u for u in units}
    print(f"techtree blocks loading... units={len(units)}")

    blocks = parse_tech_blocks(text)
    print(f"  tech blocks: {len(blocks)}")
    resolver = AgeResolver(blocks)

    unit_up = build_unit_upgrades(blocks, resolver, units_by_id)
    cat_up = build_category_upgrades(blocks, resolver)

    out = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "data/aoe3/raw/techtreey.xml",
            "doc": "docs/games/aoe3-battle.md §3.10",
            "fields": ["hp_mult", "damage_mult", "range_add", "aoe_add", "rof_set",
                       "armor_add", "speed_add", "speed_mult", "speed_set", "mult_add"],
            "age_status": AGE_STATUS,
        },
        "units": dict(sorted(unit_up.items())),
        "category": cat_up,
    }
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  units with upgrades: {len(unit_up)}")
    print(f"  category tags: {list(cat_up)}")
    print(f"  wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
