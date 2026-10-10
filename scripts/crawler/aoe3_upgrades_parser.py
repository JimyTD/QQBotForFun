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
CIVS_PATH = PROJECT_ROOT / "seeds" / "aoe3" / "civs.json"
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

    def age_reachable(self, name: str, _seen: frozenset[str] = frozenset()) -> bool:
        """到了时代就能拿到：每个前置都是时代科技，或本身也是这样的升级档。

        需要先研究某个别的科技才触发的（如波兰议会选项 ``DESejmHetman1``）不算时代升级。
        """
        block = self.blocks.get(name)
        if block is None or name in _seen:
            return False
        prereqs = tech_prereq_status(block)
        if not prereqs:
            return True
        results = [self._prereq_age_reachable(prereq, _seen | {name}) for prereq in prereqs]
        # OrPrereqs：任一前置满足即可（如“工业时代 或 某革命”）。
        if "OrPrereqs" in tech_flags(block):
            return any(results)
        return all(results)

    def _prereq_age_reachable(self, prereq: str, seen: frozenset[str]) -> bool:
        if prereq in AGE_STATUS:
            return True
        block = self.blocks.get(prereq)
        if block is None:
            return False
        flags = tech_flags(block)
        # 时代闸门影子（如 DEMilitaryIndustrialAgeEnable：工业时代 或 某革命）也算时代可达。
        if not (is_candidate_flags(flags, allow_age_upgrade=False) or "Shadow" in flags):
            return False
        return self.age_reachable(prereq, seen)


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


def _is_revolution(name: str, flags: set[str]) -> bool:
    low = name.lower()
    return "RevoltTech" in flags or low.startswith(("rev", "derev", "dehcrev", "derevolution"))


def _revolution_only_techs(blocks: dict[str, str]) -> set[str]:
    """只有革命科技会让它变得可得的科技（TechStatus active/obtainable 的来源全是革命）。"""
    sources: dict[str, set[str]] = {}
    for name, block in blocks.items():
        for match in re.finditer(
            r'<effect\s+type="TechStatus"\s+status="(active|obtainable)"[^>]*>([^<]+)</effect>',
            block,
            re.IGNORECASE,
        ):
            sources.setdefault(match.group(2).strip(), set()).add(name)
    return {
        tech
        for tech, makers in sources.items()
        if makers and all(_is_revolution(m, tech_flags(blocks.get(m, ""))) for m in makers)
    }


# 逐时代选链优先级：通用线（Veteran/Guard/Imperial 前缀）优于 RG/其他
def _line_priority(name: str) -> int:
    base = re.sub(r"^(DE|YP|XP|de|yp|xp)", "", name)
    if base.startswith(("Veteran", "Guard", "Imperial", "Champion", "Legendary")):
        return 0
    if name.startswith("RG"):
        return 2
    return 1


def _build_tag_to_units(units_by_id: dict) -> dict[str, set[str]]:
    """构建 abstract tag (lower) → concrete unit_ids 映射。

    仅保留映射到少量单位（≤ 10）的窄标签（如 AbstractSepoy → {ypsepoy, ypsepoymansabdar}），
    排除宽泛类别标签（如 AbstractInfantry → 几百个单位）以免误匹配。
    """
    tag_map: dict[str, set[str]] = {}
    for uid, u in units_by_id.items():
        for tag in u.get("type", []):
            tag_map.setdefault(tag.lower(), set()).add(uid)
    return {tag: ids for tag, ids in tag_map.items() if len(ids) <= 10}


def build_unit_upgrades(
    blocks,
    resolver,
    units_by_id,
    stringtable: dict[str, str] | None = None,
    *,
    civ_specific_techs: set[str] | None = None,
    shared_unit_ids: set[str] | None = None,
):
    """返回 {id: {age: {hp_mult, damage_mult, name, ...}}}（cumulative）。"""
    valid_ids = set(units_by_id)
    tag_to_units = _build_tag_to_units(units_by_id)
    if stringtable is None:
        stringtable = {}
    civ_specific_techs = civ_specific_techs or set()
    shared_unit_ids = shared_unit_ids or set()
    revolution_only = _revolution_only_techs(blocks)
    # 收集：id -> age -> list[(line_priority, hp_inc, dmg_inc, tech_name, setname_proto)]
    # setname_proto: SetName 查找时需要用原始大小写 proto 名
    per_id: dict[str, dict[int, list]] = {}
    # 候选门槛里的“必须给这个兵加正百分比生命/伤害”不能删（2026-10-10 实测）：
    # 时代升级档都带它；研究科技的影子档（RiflingShadow、CaracoleShadow、
    # IncendiaryGrenadesShadow、BayonetShadow 等）不带，它们的前置是一个 UpgradeTech，
    # 会被 age_reachable 判成时代可达，只靠这条挡住。原始数据没有“时代升级”字段，
    # 按钮面板 + 时代前置也覆盖不全（帝王加农炮的按钮在工厂、游骑兵跟随长弓兵线）。
    for name, block in blocks.items():
        flags = tech_flags(block)
        if is_excluded(name, flags):
            continue
        if has_setage(block):
            continue
        if not is_candidate_flags(flags, allow_age_upgrade=False):
            continue
        age = resolver.resolve(name)
        if age is None or age not in (2, 3, 4, 5):
            continue
        if not resolver.age_reachable(name):
            continue
        # 前置里要求某个文明专属科技（如帝国红衫军要求红衫军），共享单位的通用线不能用它。
        if any(prereq in civ_specific_techs for prereq in tech_prereq_status(block)):
            civ_specific_techs = civ_specific_techs | {name}
        targets = {t for _, t in iter_effects(block) if t}
        for tgt in targets:
            tid = tgt.lower()
            if tid in valid_ids:
                if name in civ_specific_techs and tid in shared_unit_ids:
                    continue
                hp_inc, dmg_inc = hp_dmg_increments(block, tid)
                if not hp_inc and not dmg_inc:
                    continue
                per_id.setdefault(tid, {}).setdefault(age, []).append(
                    (_line_priority(name), hp_inc or 0.0, dmg_inc or 0.0, name, tgt)
                )
            elif tid in tag_to_units:
                hp_inc, dmg_inc = hp_dmg_increments(block, tid)
                if not hp_inc and not dmg_inc:
                    continue
                for resolved_uid in tag_to_units[tid]:
                    if name in civ_specific_techs and resolved_uid in shared_unit_ids:
                        continue
                    per_id.setdefault(resolved_uid, {}).setdefault(age, []).append(
                        (_line_priority(name), hp_inc or 0.0, dmg_inc or 0.0, name, tgt)
                    )

    # 逐时代选一条：同一时代的多条候选是不同文明的替代升级线（通用护卫线、皇家卫队…），
    # 无文明时选通用线。输出累计科技 id；效果由运行时按统一算符结算。
    result: dict[str, dict] = {}
    for tid, by_age in per_id.items():
        picked_tech: dict[int, str] = {}
        for age, cands in by_age.items():
            # 只能由革命科技开放的档不是时代升级（迫击炮战船的哥伦比亚海军档、大元帅的革命档）。
            cands = [c for c in cands if c[3] not in revolution_only]
            if not cands:
                continue
            cands.sort(key=lambda c: (c[0], -(c[1] + c[2])))
            picked_tech[age] = cands[0][3]
        base: dict[str, dict] = {}
        cumulative: list[str] = []
        for age in sorted(picked_tech):
            cumulative.append(picked_tech[age])
            base[str(age)] = {"techs": list(cumulative)}
        # SetName: 遍历该时代所有候选科技，取含基础名的最短名（通用线最短）
        base_zh = units_by_id[tid].get("name", "")
        for age in sorted(by_age):
            best_name = None
            fallback_name = None
            for cand in by_age[age]:
                cand_tech = cand[3]
                cand_block = blocks[cand_tech]
                zh = _extract_setname(cand_block, tid, stringtable)
                if zh is None:
                    continue
                if base_zh and base_zh in zh:
                    if best_name is None or len(zh) < len(best_name):
                        best_name = zh
                elif fallback_name is None:
                    fallback_name = zh
            name = best_name or fallback_name
            if name:
                base.setdefault(str(age), {})["name"] = name
        if base:
            result[tid] = base
    return result


def build_category_upgrades(blocks, resolver):
    """返回 {tag: {age: [累计科技 id]}}，按标签匹配。"""
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
        picked: dict[int, str] = {}
        for age, cands in by_age.items():
            # 同档是不同建筑/文明的替代科技，无文明时选增量最大的那条
            # （通用线/Shadow 近卫 > 和平者 +10）。
            cands.sort(key=lambda c: -(c[0] + c[1]))
            picked[age] = cands[0][2]
        cumulative: list[str] = []
        out[tag] = {}
        for age in sorted(picked):
            cumulative.append(picked[age])
            out[tag][str(age)] = list(cumulative)
    return out


def _extract_setname(block: str, unit_id_lower: str,
                     stringtable: dict[str, str]) -> str | None:
    """从科技 block 提取 unit_id 对应的默认 SetName（无 reqtech 条件、大小写不敏感）。"""
    for m in re.finditer(
        r'type="SetName"\s+proto="([^"]+)"([^>]*)newname="(\d+)"', block
    ):
        if m.group(1).lower() != unit_id_lower:
            continue
        rest = m.group(2)
        if "reqtech=" in rest:
            continue
        locid = m.group(3)
        zh = stringtable.get(locid)
        if zh:
            zh = re.sub(r"<[^>]+>", "", zh).strip()
            if zh:
                return zh
    return None


def _load_stringtable() -> dict[str, str]:
    st_path = PROJECT_ROOT / "data" / "aoe3" / "raw" / "stringtabley_zh.xml"
    st_text = st_path.read_text(encoding="utf-8")
    return dict(re.findall(r'<string _locid="(\d+)"[^>]*>(.*?)</string>', st_text, re.S))


def main():
    print("=== AoE3 单位改良 Parser ===")
    text = TECHTREE_PATH.read_text(encoding="utf-8")
    units = json.loads(UNITS_PATH.read_text(encoding="utf-8"))
    units_by_id = {u["id"]: u for u in units}
    print(f"techtree blocks loading... units={len(units)}")

    blocks = parse_tech_blocks(text)
    print(f"  tech blocks: {len(blocks)}")
    resolver = AgeResolver(blocks)
    stringtable = _load_stringtable()

    civ_data = json.loads(CIVS_PATH.read_text(encoding="utf-8"))
    unique_upgrade_techs = {
        tech
        for civ_id in civ_data["_meta"]["curated_civs"]
        for tech in civ_data["civs"][civ_id].get("unique_techs", ())
    }
    # Shared units must use their neutral upgrade line in ordinary battles.
    # Most Royal Guard lines use RG/DERG prefixes; Italy and Malta use named
    # artillery upgrades instead. Unique-unit Guard lines remain valid because
    # there is no cross-civilization ambiguity for those unit ids.
    civ_specific_techs = {
        tech
        for tech in unique_upgrade_techs
        if tech.startswith(("RG", "DERG"))
        or tech in {"DESpingardes", "DEGalileans", "DEBasilisks"}
    }
    shared_unit_ids = {
        unit_id
        for unit_id, owners in civ_data.get("unit_civs", {}).items()
        if len(owners) > 1
    }
    unit_up = build_unit_upgrades(
        blocks,
        resolver,
        units_by_id,
        stringtable,
        civ_specific_techs=civ_specific_techs,
        shared_unit_ids=shared_unit_ids,
    )
    cat_up = build_category_upgrades(blocks, resolver)

    out = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "data/aoe3/raw/techtreey.xml",
            "doc": "docs/games/aoe3-battle.md §3.10",
            "rule": (
                "units[id][age].techs / category[tag][age] = 该时代已生效的累计科技 id；"
                "效果在运行时按统一算符结算，同一科技只生效一次"
            ),
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
