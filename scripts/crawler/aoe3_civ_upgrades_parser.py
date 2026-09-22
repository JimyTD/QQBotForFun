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

import copy
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


def _merge_nested_add(target: dict, source: dict) -> None:
    for slot, values in source.items():
        target.setdefault(slot, {})
        for key, value in values.items():
            target[slot][key] = target[slot].get(key, 0.0) + value


def _stage_extras(tech_names: list[str], blocks: dict[str, str], unit: dict) -> dict:
    out = {
        "range_add": {},
        "aoe_add": {},
        "rof_set": {},
        "rof_add": {},
        "armor_add": {},
        "mult_add": {},
        "speed_add": 0.0,
        "speed_mult": 1.0,
        "speed_set": None,
    }
    for tech_name in tech_names:
        block = blocks[tech_name]
        parsed = base_parser.tech_extra_effects(block, unit, tech_name)
        for key in ("range_add", "aoe_add", "armor_add"):
            for slot, value in parsed[key].items():
                out[key][slot] = out[key].get(slot, 0.0) + value
        _merge_nested_add(out["mult_add"], parsed["mult_add"])
        out["rof_set"].update(parsed["rof_set"])
        out["speed_add"] += parsed["speed_add"]
        out["speed_mult"] *= parsed["speed_mult"]
        if parsed["speed_set"] is not None:
            out["speed_set"] = parsed["speed_set"]

        for attrs, target in base_parser.iter_effects(block):
            if not _target_matches(target, unit):
                continue
            if base_parser._attr(attrs, "type") != "Data":
                continue
            if base_parser._attr(attrs, "subtype") != "RateOfFire":
                continue
            if base_parser._attr(attrs, "relativity") != "Absolute":
                continue
            raw_amount = base_parser._attr(attrs, "amount")
            if raw_amount is None or float(raw_amount) == 0:
                continue
            for slot in base_parser._slots_for_action(
                base_parser._attr(attrs, "action"),
                base_parser._attr(attrs, "allactions"),
                unit,
            ):
                out["rof_add"][slot] = out["rof_add"].get(slot, 0.0) + float(raw_amount)
    return out


def _apply_cost_effects(
    cost: dict[str, float],
    tech_names: list[str],
    blocks: dict[str, str],
    unit: dict,
) -> dict[str, int]:
    result = {resource: float(value) for resource, value in cost.items()}
    for tech_name in tech_names:
        for attrs, target in base_parser.iter_effects(blocks[tech_name]):
            if not _target_matches(target, unit):
                continue
            if base_parser._attr(attrs, "type") != "Data":
                continue
            if base_parser._attr(attrs, "subtype") != "Cost":
                continue
            resource = (base_parser._attr(attrs, "resource") or "").lower()
            raw_amount = base_parser._attr(attrs, "amount")
            relativity = base_parser._attr(attrs, "relativity")
            if not resource or raw_amount is None:
                continue
            amount = float(raw_amount)
            current = result.get(resource, 0.0)
            if relativity == "BasePercent":
                result[resource] = current * amount
            elif relativity == "Absolute":
                result[resource] = current + amount
            elif relativity == "Assign":
                result[resource] = amount
    return {
        resource: max(0, round(value))
        for resource, value in result.items()
        if round(value) > 0
    }


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


def _merge_stage(state: dict, stage: dict) -> None:
    state["hp_mult"] += stage["hp_inc"]
    state["damage_mult"] += stage["damage_inc"]
    for key in ("range_add", "aoe_add", "armor_add", "rof_add"):
        for slot, value in stage[key].items():
            state[key][slot] = state[key].get(slot, 0.0) + value
    _merge_nested_add(state["mult_add"], stage["mult_add"])
    state["rof_set"].update(stage["rof_set"])
    state["speed_add"] += stage["speed_add"]
    state["speed_mult"] *= stage["speed_mult"]
    if stage["speed_set"] is not None:
        state["speed_set"] = stage["speed_set"]
    state["cost"] = stage["cost"]
    if stage["name"]:
        state["name"] = stage["name"]


def _entry_from_state(state: dict) -> dict:
    entry: dict = {
        "hp_mult": round(state["hp_mult"], 4),
        "damage_mult": round(state["damage_mult"], 4),
        "techs": list(state["techs"]),
    }
    for key in ("range_add", "aoe_add", "armor_add", "rof_add", "rof_set"):
        if state[key]:
            entry[key] = copy.deepcopy(state[key])
    if state["mult_add"]:
        entry["mult_add"] = copy.deepcopy(state["mult_add"])
    if abs(state["speed_add"]) > 1e-9:
        entry["speed_add"] = round(state["speed_add"], 3)
    if abs(state["speed_mult"] - 1.0) > 1e-9:
        entry["speed_mult"] = round(state["speed_mult"], 4)
    if state["speed_set"] is not None:
        entry["speed_set"] = round(state["speed_set"], 3)
    if state["cost"] != state["base_cost"]:
        entry["cost"] = dict(state["cost"])
    if state["name"]:
        entry["name"] = state["name"]
    return entry


def main() -> None:
    blocks = base_parser.parse_tech_blocks(TECHTREE_PATH.read_text(encoding="utf-8"))
    resolver = base_parser.AgeResolver(blocks)
    strings = base_parser._load_stringtable()
    units = json.loads(UNITS_PATH.read_text(encoding="utf-8"))
    units_by_id = {unit["id"]: unit for unit in units}
    civ_data = json.loads(CIVS_PATH.read_text(encoding="utf-8"))
    base_data = json.loads(BASE_UPGRADES_PATH.read_text(encoding="utf-8"))["units"]

    output: dict[str, dict] = {}
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
                if not _is_unit_upgrade_candidate(tech_name, block):
                    continue
                age = resolver.resolve(tech_name)
                if age not in candidates:
                    continue
                closure = _tech_closure(tech_name, blocks)
                closure_blocks = [blocks[name] for name in closure]
                hp_inc, damage_inc = _hp_damage_increment(closure_blocks, unit)
                extras = _stage_extras(closure, blocks, unit)
                cost = _apply_cost_effects(unit.get("cost", {}), closure, blocks, unit)
                name = _set_name(closure, blocks, unit_id, strings)
                has_extras = any(
                    extras[key]
                    for key in (
                        "range_add", "aoe_add", "rof_set", "rof_add",
                        "armor_add", "mult_add",
                    )
                ) or extras["speed_set"] is not None or extras["speed_add"] or (
                    extras["speed_mult"] != 1.0
                )
                if not (hp_inc or damage_inc or has_extras or name or cost != unit.get("cost", {})):
                    continue
                candidates[age].append({
                    "tech": tech_name,
                    "closure": closure,
                    "hp_inc": hp_inc,
                    "damage_inc": damage_inc,
                    "cost": cost,
                    "name": name,
                    **extras,
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

            base_age3 = base_data.get(unit_id, {}).get("3", {})
            state = {
                "hp_mult": float(base_age3.get("hp_mult", 1.0)),
                "damage_mult": float(base_age3.get("damage_mult", 1.0)),
                "range_add": copy.deepcopy(base_age3.get("range_add", {})),
                "aoe_add": copy.deepcopy(base_age3.get("aoe_add", {})),
                "rof_set": copy.deepcopy(base_age3.get("rof_set", {})),
                "rof_add": copy.deepcopy(base_age3.get("rof_add", {})),
                "armor_add": copy.deepcopy(base_age3.get("armor_add", {})),
                "mult_add": copy.deepcopy(base_age3.get("mult_add", {})),
                "speed_add": float(base_age3.get("speed_add", 0.0)),
                "speed_mult": float(base_age3.get("speed_mult", 1.0)),
                "speed_set": base_age3.get("speed_set"),
                "base_cost": dict(unit.get("cost", {})),
                "cost": dict(unit.get("cost", {})),
                "name": base_age3.get("name"),
                "techs": [],
            }
            unit_result: dict[str, dict] = {}
            for age in (4, 5):
                stage = selected.get(age)
                if stage is not None:
                    # Cost effects are cumulative from the previous stage.
                    stage = dict(stage)
                    stage["cost"] = _apply_cost_effects(
                        state["cost"],
                        stage["closure"],
                        blocks,
                        unit,
                    )
                    state["techs"].append(stage["tech"])
                    _merge_stage(state, stage)
                elif age == 5:
                    generic_age5 = base_data.get(unit_id, {}).get("5")
                    generic_age4 = base_data.get(unit_id, {}).get("4", {})
                    if generic_age5:
                        state["hp_mult"] += float(generic_age5.get("hp_mult", 1.0)) - float(
                            generic_age4.get("hp_mult", 1.0)
                        )
                        state["damage_mult"] += float(
                            generic_age5.get("damage_mult", 1.0)
                        ) - float(generic_age4.get("damage_mult", 1.0))
                        state["name"] = generic_age5.get("name", state["name"])
                unit_result[str(age)] = _entry_from_state(state)
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
