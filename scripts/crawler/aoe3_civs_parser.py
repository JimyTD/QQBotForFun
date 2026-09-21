"""AoE3 文明 Parser —— 从 civs.xml + techtreey.xml 生成 seeds/aoe3/civs.json。

权威源（入库 git）：
  - data/aoe3/raw/civs.xml        （文明定义：主城、起始单位、agetech 链、culture、main）
  - data/aoe3/raw/techtreey.xml   （tech effects：Enable ProtoUnit / AddTrain / TechStatus）
  - data/aoe3/raw/stringtabley_zh.xml（文明中文名）
  - seeds/aoe3/units.json         （合法单位 id 集合，用于过滤掉建筑/装饰）

原理
----
`protoy.xml` 里**没有**国家字段（只有 `civflagoverride` 旗帜覆盖），所以从 protoy 直接解国家
解不出来 —— 这是「解不出国家」说法的来源。单位归属由 `techtreey.xml` 的 tech effects 决定，
且**三类文明的入口不同**：

  1. 主文明 / 原住民部落：civs.xml 给出 `agetech`（`Age0Xxx`；部落为 `NativeXxx`），
     对它做 tech 闭包展开。
  2. 革命文明（`DERev*`）：civs.xml 里**没有 agetech**（它们不是从 Age0 起步的文明）。
     入口在 techtreey：革命 tech 带 `<revolutionciv>DERevUSA</revolutionciv>` 字段，
     该 tech 的 effects 即「革命后可用单位」。
  3. 战役文明（`SPC*`）：同 1，有 agetech。

闭包展开规则：
  - `Data/Enable` + `<target type="ProtoUnit">U</target>`  → 可用单位 U
  - `Data/AddTrain` + `unittype="U"`                       → 把 U 加入建筑训练列表，也算可用
  - `TechStatus status="active"` + 文本 T                  → 递归展开共享 tech T
  - `TechStatus status="obtainable"` + 文本 T              → 该文明可研究科技 T

实测：单位**可用性不随时代变化**（agetech 链只 enable 科技），故不按时代分级；
登场时代由 `units.json` 的 `age` 字段负责（`lineup._age_filter` 已实现）。

产出 `seeds/aoe3/civs.json`
--------------------------
  - `civs.<Civ>`：中文名 / culture / 起始单位 / 主城 / `units` / `unique_units` /
    `unique_techs` / 科技计数 / `is_playable`（可玩主文明）/ `is_revolution`（革命）
  - `unit_civs`：单位 → 可玩主文明（回填 `units.json` 的 `civs` 字段用）
  - `unit_rev_civs`：单位 → 革命文明
  - 「专属」口径：只在 `_meta.curated_civs`（24 个可玩主文明）之间比较，避免战役/革命/
    变体条目把真正的专属单位稀释掉（长弓兵在 SPC 战役文明里也有，但那不算「英国不专属」）

用法::

    uv run python scripts/crawler/aoe3_civs_parser.py
    uv run python scripts/crawler/aoe3_civs_parser.py --civ DERevUSA --verbose
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aoe3_gamedata_parser import load_string_table  # noqa: E402

EXTRACTED_DIR = Path(os.environ.get("AOE3_EXTRACTED_DIR", str(ROOT / "data" / "aoe3" / "raw")))
SEEDS_DIR = ROOT / "seeds" / "aoe3"
CIVS_XML = EXTRACTED_DIR / "civs.xml"
TECHTREEY_XML = EXTRACTED_DIR / "techtreey.xml"
STRING_ZH = EXTRACTED_DIR / "stringtabley_zh.xml"
UNITS_JSON = SEEDS_DIR / "units.json"
OUTPUT_PATH = SEEDS_DIR / "civs.json"

# 非「可玩主文明」的 id 特征。
# ⚠️ 不要按 `XP` 前缀排除 —— 原住民三文明的可玩条目 id 就是 `XPAztec` / `XPIroquois` /
# `XPSioux`（main=1、有主城文件）；而 `Aztecs` / `Iroquois` / `Lakota` 反而是壳条目
# （main=0、无主城）。真正的壳判定看 main 与 homecity 是否为空。
NON_CURATED_PREFIXES = ("SPC", "XPSPC")  # 战役/剧情文明
NON_CURATED_IDS = {
    "NativeAmerican",  # 通用模板（主城指向 homecitybritish.xml）
    "Pirate",
    "TheCircle",
    "Saltpeter",
}


# ============================================================
# 载入
# ============================================================
def load_techs() -> tuple[dict[str, list[dict]], dict[str, list[str]]]:
    """返回 (tech 名 → effects, 革命文明 → 革命 tech 名列表)。"""
    root = ET.parse(TECHTREEY_XML).getroot()
    techs: dict[str, list[dict]] = {}
    revolution: dict[str, list[str]] = {}
    for tech in root.findall("tech"):
        name = tech.get("name")
        if not name:
            continue
        rev = (tech.findtext("revolutionciv") or "").strip()
        if rev:
            revolution.setdefault(rev, []).append(name)
        effs: list[dict] = []
        for eff in tech.findall("effects/effect"):
            tgt = eff.find("target")
            effs.append(
                {
                    "type": eff.get("type"),
                    "subtype": eff.get("subtype"),
                    "status": eff.get("status"),
                    "unittype": eff.get("unittype"),
                    "target_type": tgt.get("type") if tgt is not None else None,
                    "target": (tgt.text or "").strip() if tgt is not None else (eff.text or "").strip(),
                }
            )
        techs[name] = effs
    return techs, revolution


def load_civs() -> list[dict]:
    """civs.xml → 文明定义列表。"""
    root = ET.parse(CIVS_XML).getroot()
    civs: list[dict] = []
    for civ in root.findall("civ"):
        name = civ.findtext("name")
        if not name:
            continue
        age_techs = [
            (at.findtext("tech") or "").strip()
            for at in civ.findall("agetech")
            if (at.findtext("tech") or "").strip()
        ]
        civs.append(
            {
                "id": name,
                "displaynameid": (civ.findtext("displaynameid") or "").strip(),
                "culture": (civ.findtext("culture") or "").strip(),
                "statsid": (civ.findtext("statsid") or "").strip(),
                "is_main": (civ.findtext("main") or "0").strip() == "1",
                "homecity": (civ.findtext("homecityfilename") or "").strip(),
                "age_techs": age_techs,
                "starting_units": [e.text.strip() for e in civ.findall("startingunit") if e.text],
            }
        )
    return civs


# ============================================================
# tech 闭包
# ============================================================
def expand(techs: dict[str, list[dict]], roots: list[str]) -> tuple[set[str], set[str], set[str]]:
    """展开 tech 闭包 → (启用单位, 激活科技, 可研究科技)。"""
    units: set[str] = set()
    active: set[str] = set()
    obtainable: set[str] = set()
    seen: set[str] = set()
    queue = [t for t in roots if t]
    while queue:
        t = queue.pop()
        if t in seen:
            continue
        seen.add(t)
        active.add(t)
        for e in techs.get(t, []):
            if e["type"] == "Data" and e["subtype"] == "Enable" and e["target_type"] == "ProtoUnit":
                if e["target"]:
                    units.add(e["target"])
            elif e["type"] == "Data" and e["subtype"] == "AddTrain" and e["unittype"]:
                units.add(e["unittype"])
            elif e["type"] == "Data" and e["subtype"] == "FreeHomeCityUnit" and e["unittype"]:
                # 革命/文明效果「白送」的单位（如利沃尼亚革命送 deREVHighMaster）。
                units.add(e["unittype"])
            elif e["type"] == "TechStatus" and e["status"] == "active" and e["target"]:
                queue.append(e["target"])
            elif e["type"] == "TechStatus" and e["status"] == "obtainable" and e["target"]:
                obtainable.add(e["target"])
    return units, active, obtainable


def is_curated(civ_id: str, is_main: bool) -> bool:
    if not is_main or civ_id in NON_CURATED_IDS:
        return False
    return not any(civ_id.startswith(p) for p in NON_CURATED_PREFIXES)


def main() -> None:
    ap = argparse.ArgumentParser(description="AoE3 civs parser")
    ap.add_argument("--civ", default=None, help="只处理某个文明（调试用）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    for path in (CIVS_XML, TECHTREEY_XML, UNITS_JSON):
        if not path.is_file():
            raise SystemExit(f"missing: {path}")

    units_data = json.loads(UNITS_JSON.read_text(encoding="utf-8"))
    valid_units = {u["id"].lower(): u["id"] for u in units_data}

    strings_zh = load_string_table(STRING_ZH) if STRING_ZH.is_file() else {}
    techs, revolution = load_techs()
    civs = load_civs()
    print("=== AoE3 Civs Parser ===")
    print(f"tech {len(techs)} | civ {len(civs)} | 革命 tech 指向 {len(revolution)} 个文明 | 合法单位 {len(valid_units)}")

    if args.civ:
        civs = [c for c in civs if c["id"] == args.civ] or civs

    out: dict[str, dict] = {}
    per_civ: dict[str, tuple[set[str], set[str], set[str]]] = {}

    for civ in civs:
        is_rev = civ["id"] in revolution
        roots = civ["age_techs"] or revolution.get(civ["id"], [])
        raw_units, active, obtainable = expand(techs, roots)
        ids = {valid_units[e.lower()] for e in raw_units if e.lower() in valid_units}
        per_civ[civ["id"]] = (ids, active, obtainable)
        if args.verbose:
            print(f"    {civ['id']:22s} roots={len(roots):2d} 单位 {len(ids):3d}｜科技 {len(active):4d}+{len(obtainable):4d}")
        out[civ["id"]] = {
            "name": strings_zh.get(civ["displaynameid"], "") or civ["id"],
            "name_en": civ["id"],
            "culture": civ["culture"],
            "statsid": civ["statsid"],
            "is_main": civ["is_main"],
            "is_revolution": is_rev,
            "homecity": civ["homecity"],
            "age_techs": civ["age_techs"],
            "revolution_techs": revolution.get(civ["id"], []),
            "starting_units": sorted({e.lower() for e in civ["starting_units"]}),
            "units": sorted(ids),
            "tech_counts": {"active": len(active), "obtainable": len(obtainable)},
        }

    curated = sorted(cid for cid in out if is_curated(cid, out[cid]["is_main"]))
    rev_civs = sorted(cid for cid in out if out[cid]["is_revolution"] and per_civ[cid][0])
    print(f"可玩主文明 {len(curated)} 个｜革命文明有单位 {len(rev_civs)} 个")

    def uniques(getter, scope: list[str]) -> dict[str, list[str]]:
        owner: dict[str, list[str]] = {}
        for cid in scope:
            for item in getter(cid):
                owner.setdefault(item, []).append(cid)
        by_civ: dict[str, list[str]] = {cid: [] for cid in scope}
        for item, owners in owner.items():
            if len(owners) == 1:
                by_civ[owners[0]].append(item)
        return {cid: sorted(v) for cid, v in by_civ.items()}

    uni_units = uniques(lambda cid: per_civ[cid][0], curated)
    uni_techs = uniques(lambda cid: per_civ[cid][1] | per_civ[cid][2], curated)
    for cid in curated:
        out[cid]["unique_units"] = uni_units[cid]
        out[cid]["unique_techs"] = uni_techs[cid]
    for cid in out:
        out[cid].setdefault("unique_units", [])
        out[cid].setdefault("unique_techs", [])
        out[cid]["is_playable"] = cid in curated

    def reverse_index(scope: list[str]) -> dict[str, list[str]]:
        idx: dict[str, list[str]] = {}
        for cid in scope:
            for i in per_civ[cid][0]:
                idx.setdefault(i, []).append(cid)
        return {k: sorted(v) for k, v in sorted(idx.items())}

    unit_civs = reverse_index(curated)
    unit_rev_civs = reverse_index(rev_civs)

    payload = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": ["data/aoe3/raw/civs.xml", "data/aoe3/raw/techtreey.xml"],
            "units_source": "seeds/aoe3/units.json",
            "doc": "docs/games/aoe3-data-refresh.md",
            "counts": {
                "civs": len(out),
                "curated_civs": len(curated),
                "revolution_civs_with_units": len(rev_civs),
                "units_with_civ": len(unit_civs),
                "units_with_rev_civ": len(unit_rev_civs),
            },
            "curated_civs": curated,
            "notes": [
                "单位可用性不随时代变化（agetech 只 enable 科技），登场时代看 units.json 的 age 字段",
                "革命文明没有 agetech，单位来自 techtreey 中 <revolutionciv> 指向它们的革命 tech",
                "收集口径：Enable ProtoUnit / AddTrain unittype / FreeHomeCityUnit unittype（革命白送）",
                "个别革命（如加拿大）通过「改造现有单位」实现（给村民加攻击），不产生新单位条目，故 units 为空属如实",
                "原住民部落（NativeXxx）的 units 是部落特色兵（结盟后可用）",
                "unique_units / unique_techs 只在 curated_civs 之间比较",
                "unit_civs 只列可玩主文明；革命文明见 unit_rev_civs；其余 137 条目明细都在 civs 中",
            ],
        },
        "civs": out,
        "unit_civs": unit_civs,
        "unit_rev_civs": unit_rev_civs,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Stats ===")
    print(f"  文明 {len(out)}（可玩主文明 {len(curated)} / 革命有单位 {len(rev_civs)}）")
    print(f"  单位归属：主文明 {len(unit_civs)} 个 / 革命 {len(unit_rev_civs)} 个（共 {len(valid_units)} 个单位）")
    for cid in ("Spanish", "British", "Chinese", "DEInca", "Ottomans", "XPAztec"):
        c = out[cid]
        print(f"  {cid:10s} {c['name']:6s} 单位 {len(c['units']):3d}｜专属 {len(c['unique_units']):3d}")
    for cid in rev_civs[:6]:
        print(f"  [革命] {cid:16s} 单位 {len(out[cid]['units']):3d}: {out[cid]['units'][:8]}")
    print(f"\nWrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
