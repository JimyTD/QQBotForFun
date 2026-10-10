"""Generate civilization-specific military upgrade overrides.

The generic upgrade seed intentionally prefers shared Veteran/Guard/Imperial
lines. Civ war needs the actual per-civilization upgrade path instead: some
Royal Guard technologies activate a normal Guard technology and add a bonus,
while others contain the whole Guard tier themselves. This parser follows the
TechStatus graph and applies every node once.

Usage:
    uv run python scripts/crawler/aoe3_civ_upgrades_parser.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import aoe3_upgrades_parser as base_parser  # noqa: E402

TECHTREE_PATH = ROOT / "data" / "aoe3" / "raw" / "techtreey.xml"
UNITS_PATH = ROOT / "seeds" / "aoe3" / "units.json"
CIVS_PATH = ROOT / "seeds" / "aoe3" / "civs.json"
BASE_UPGRADES_PATH = ROOT / "seeds" / "aoe3" / "unit_upgrades.json"
OUTPUT_PATH = ROOT / "seeds" / "aoe3" / "civ_unit_upgrades.json"
_SHADOW_UPGRADE_MARKERS = (
    "Veteran", "Guard", "Imperial", "Elite", "Champion", "Honored", "Exalted", "Legendary",
)


def _active_techs(block: str) -> list[str]:
    return re.findall(
        r'<effect\s+type="TechStatus"\s+status="active"[^>]*>([^<]+)</effect>',
        block,
    )


def _is_unit_upgrade_candidate(name: str, block: str) -> bool:
    flags = base_parser.tech_flags(block)
    if "UpgradeTech" in flags:
        return True
    return "Shadow" in flags and any(marker in name for marker in _SHADOW_UPGRADE_MARKERS)


def _tech_closure(name: str, blocks: dict[str, str]) -> list[str]:
    """Return active dependencies before their parent, with no duplicate nodes."""
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(tech_name: str) -> None:
        if tech_name in seen:
            return
        seen.add(tech_name)
        block = blocks.get(tech_name)
        if block is None:
            return
        for child in _active_techs(block):
            visit(child)
        ordered.append(tech_name)

    visit(name)
    return ordered


def _target_matches(target: str | None, unit: dict) -> bool:
    if target is None:
        return False
    return target.lower() == unit["id"] or target in unit.get("type", [])


def _hp_damage_increment(blocks_for_stage: list[str], unit: dict) -> tuple[float, float]:
    hp = damage = 0.0
    for block in blocks_for_stage:
        for attrs, target in base_parser.iter_effects(block):
            if not _target_matches(target, unit):
                continue
            if base_parser._attr(attrs, "type") != "Data":
                continue
            if base_parser._attr(attrs, "relativity") != "BasePercent":
                continue
            raw_amount = base_parser._attr(attrs, "amount")
            if raw_amount is None:
                continue
            increment = float(raw_amount) - 1.0
            if increment <= 0:
                continue
            subtype = base_parser._attr(attrs, "subtype")
            if subtype in base_parser.SUBTYPE_HP:
                hp += increment
            elif subtype in base_parser.SUBTYPE_DMG:
                action = base_parser._attr(attrs, "action")
                allactions = base_parser._attr(attrs, "allactions")
                if not action or allactions == "1":
                    damage += increment
    return hp, damage


def _closure_touches_unit(blocks_for_stage: list[str], unit: dict) -> bool:
    """这组科技里至少有一条 Data 效果写明打到这个兵（id 或标签）。"""
    for block in blocks_for_stage:
        for attrs, target in base_parser.iter_effects(block):
            if _target_matches(target, unit) and base_parser._attr(attrs, "type") == "Data":
                return True
    return False


def _set_name(
    tech_names: list[str],
    blocks: dict[str, str],
    unit_id: str,
    stringtable: dict[str, str],
) -> str | None:
    for tech_name in reversed(tech_names):
        block = blocks[tech_name]
        for match in re.finditer(
            r'type="SetName"[^>]*proto="([^"]+)"[^>]*newname="(\d+)"',
            block,
        ):
            if match.group(1).lower() != unit_id:
                continue
            name = re.sub(r"<[^>]+>", "", stringtable.get(match.group(2), "")).strip()
            if name:
                return name
    return None


def main() -> None:
    blocks = base_parser.parse_tech_blocks(TECHTREE_PATH.read_text(encoding="utf-8"))
    resolver = base_parser.AgeResolver(blocks)
    strings = base_parser._load_stringtable()
    units = json.loads(UNITS_PATH.read_text(encoding="utf-8"))
    units_by_id = {unit["id"]: unit for unit in units}
    civ_data = json.loads(CIVS_PATH.read_text(encoding="utf-8"))
    base_data = json.loads(BASE_UPGRADES_PATH.read_text(encoding="utf-8"))["units"]

    output: dict[str, dict] = {}
    revolution_only = base_parser._revolution_only_techs(blocks)
    for civ_id in civ_data["_meta"]["curated_civs"]:
        civ = civ_data["civs"][civ_id]
        available = set(civ.get("unique_techs", ()))
        civ_result: dict[str, dict] = {}
        for unit_id in civ["units"]:
            unit = units_by_id.get(unit_id)
            if unit is None:
                continue
            candidates: dict[int, list[dict]] = {4: [], 5: []}
            for tech_name in available:
                block = blocks.get(tech_name)
                if block is None:
                    continue
                if base_parser.is_excluded(tech_name, base_parser.tech_flags(block)):
                    continue
                # 只有革命能开放的档不是时代升级。
                if tech_name in revolution_only:
                    continue
                if not _is_unit_upgrade_candidate(tech_name, block):
                    continue
                age = resolver.resolve(tech_name)
                if age not in candidates:
                    continue
                if not resolver.age_reachable(tech_name):
                    continue
                closure = _tech_closure(tech_name, blocks)
                closure_blocks = [blocks[name] for name in closure]
                hp_inc, damage_inc = _hp_damage_increment(closure_blocks, unit)
                name = _set_name(closure, blocks, unit_id, strings)
                if not _closure_touches_unit(closure_blocks, unit):
                    continue
                candidates[age].append({
                    "tech": tech_name,
                    "closure": closure,
                    "hp_inc": hp_inc,
                    "damage_inc": damage_inc,
                    "name": name,
                })

            if not candidates[4]:
                continue
            selected: dict[int, dict] = {}
            for age in (4, 5):
                if candidates[age]:
                    selected[age] = max(
                        candidates[age],
                        key=lambda item: (
                            item["hp_inc"] + item["damage_inc"],
                            len(item["closure"]),
                        ),
                    )

            # 3 时代沿用通用线；4/5 时代用该文明选中的升级（含它经 TechStatus 激活的全部节点）。
            # 只记累计科技 id，效果由运行时按统一算符结算，同一科技只算一次。
            generic = base_data.get(unit_id, {})
            techs: list[str] = list(generic.get("3", {}).get("techs", ()))
            name = generic.get("3", {}).get("name")
            unit_result: dict[str, dict] = {}
            for age in (4, 5):
                stage = selected.get(age)
                if stage is not None:
                    stage_techs = stage["closure"]
                    stage_name = stage["name"]
                else:
                    previous = set(generic.get(str(age - 1), {}).get("techs", ()))
                    stage_techs = [
                        tech for tech in generic.get(str(age), {}).get("techs", ())
                        if tech not in previous
                    ]
                    stage_name = generic.get(str(age), {}).get("name")
                for tech in stage_techs:
                    if tech not in techs:
                        techs.append(tech)
                name = stage_name or name
                entry: dict = {"techs": list(techs)}
                if stage is not None:
                    entry["selected"] = stage["tech"]
                if name:
                    entry["name"] = name
                unit_result[str(age)] = entry
            civ_result[unit_id] = unit_result
        if civ_result:
            output[civ_id] = dict(sorted(civ_result.items()))

    payload = {
        "_meta": {
            "source": [
                "data/aoe3/raw/techtreey.xml",
                "seeds/aoe3/civs.json",
                "seeds/aoe3/unit_upgrades.json",
            ],
            "doc": "docs/games/aoe3-civ-war-wip.md",
            "scope": "civilization-specific age 4/5 upgrade overrides",
        },
        "civs": output,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    count = sum(len(units) for units in output.values())
    print(f"wrote {OUTPUT_PATH}: {len(output)} civs, {count} civ-unit overrides")


if __name__ == "__main__":
    main()
