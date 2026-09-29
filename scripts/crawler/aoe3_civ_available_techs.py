"""Export the authoritative per-civilization available-tech lists.

Source of truth:
  - civs.xml: each civilization's agetech entry points
  - techtreey.xml: TechStatus active/obtainable closure from those entries
  - homecity/homecity<Civ>.xml: the civilization's actual card definitions

Unit targets are never used to infer civilization ownership.

Usage:
    uv run python scripts/crawler/aoe3_civ_available_techs.py
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "aoe3" / "raw"
TECHTREE_PATH = RAW_DIR / "techtreey.xml"
CIVS_PATH = RAW_DIR / "civs.xml"
HOMECITY_DIR = RAW_DIR / "homecity"
OUTPUT_PATH = ROOT / "seeds" / "aoe3" / "civ_available_techs.json"

NON_CURATED_PREFIXES = ("SPC", "XPSPC")
NON_CURATED_IDS = {
    "NativeAmerican",
    "Pirate",
    "TheCircle",
    "Saltpeter",
}


def _load_tech_effects() -> dict[str, list[dict[str, str]]]:
    root = ET.parse(TECHTREE_PATH).getroot()
    techs: dict[str, list[dict[str, str]]] = {}
    for tech in root.findall("tech"):
        name = (tech.get("name") or "").strip()
        if not name:
            continue
        effects: list[dict[str, str]] = []
        for effect in tech.findall("./effects/effect"):
            target = effect.find("target")
            effects.append(
                {
                    "type": effect.get("type") or "",
                    "subtype": effect.get("subtype") or "",
                    "status": effect.get("status") or "",
                    "target_type": target.get("type") if target is not None else "",
                    "target": (
                        (target.text or "").strip()
                        if target is not None
                        else (effect.text or "").strip()
                    ),
                }
            )
        techs[name] = effects
    return techs


def _load_civs() -> dict[str, dict[str, object]]:
    root = ET.parse(CIVS_PATH).getroot()
    civs: dict[str, dict[str, object]] = {}
    for civ in root.findall("civ"):
        civ_id = (civ.findtext("name") or "").strip()
        if not civ_id:
            continue
        age_techs = [
            (entry.findtext("tech") or "").strip()
            for entry in civ.findall("agetech")
            if (entry.findtext("tech") or "").strip()
        ]
        civs[civ_id] = {
            "is_main": (civ.findtext("main") or "0").strip() == "1",
            "homecity": (civ.findtext("homecityfilename") or "").strip(),
            "age_techs": age_techs,
        }
    return civs


def _expand_age_techs(
    techs: dict[str, list[dict[str, str]]],
    roots: list[str],
) -> tuple[set[str], set[str]]:
    active: set[str] = set()
    obtainable: set[str] = set()
    queue = list(roots)
    seen: set[str] = set()
    while queue:
        tech_id = queue.pop()
        if not tech_id or tech_id in seen:
            continue
        seen.add(tech_id)
        active.add(tech_id)
        for effect in techs.get(tech_id, ()):
            if effect["type"] != "TechStatus":
                continue
            target = effect["target"]
            if effect["status"] == "active" and target:
                queue.append(target)
            elif effect["status"] == "obtainable" and target:
                obtainable.add(target)
    return active, obtainable


def _load_homecity_cards() -> dict[str, set[str]]:
    by_civ: dict[str, set[str]] = {}
    for path in sorted(HOMECITY_DIR.glob("homecity*.xml")):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        civ_id = (root.findtext("civ") or "").strip()
        if not civ_id:
            continue
        cards = {
            (card.findtext("name") or "").strip()
            for card in root.findall("./cards/card")
            if (card.findtext("name") or "").strip()
        }
        by_civ.setdefault(civ_id, set()).update(cards)
    return by_civ


def _is_curated(civ_id: str, is_main: bool) -> bool:
    if not is_main or civ_id in NON_CURATED_IDS:
        return False
    return not any(civ_id.startswith(prefix) for prefix in NON_CURATED_PREFIXES)


def build() -> dict[str, object]:
    techs = _load_tech_effects()
    civs = _load_civs()
    homecity_cards = _load_homecity_cards()
    result: dict[str, dict[str, list[str]]] = {}
    for civ_id, civ in sorted(civs.items()):
        if not _is_curated(civ_id, bool(civ["is_main"])):
            continue
        active, obtainable = _expand_age_techs(techs, list(civ["age_techs"]))
        cards = homecity_cards.get(civ_id, set())
        result[civ_id] = {
            "active": sorted(active),
            "obtainable": sorted(obtainable),
            "homecity_card": sorted(cards),
            "all": sorted(active | obtainable | cards),
        }
    return {
        "_meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "source": [
                "data/aoe3/raw/civs.xml",
                "data/aoe3/raw/techtreey.xml",
                "data/aoe3/raw/homecity/homecity*.xml",
            ],
            "rule": (
                "文明可获得科技 = age tech 递归 active/obtainable "
                "+ 该文明 homecity 文件 cards/card/name; 不使用目标单位反推文明"
            ),
            "civ_count": len(result),
        },
        "civs": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-priority", action="store_true")
    args = parser.parse_args()

    payload = build()
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    total = sum(len(data["all"]) for data in payload["civs"].values())
    print(f"civs={len(payload['civs'])} entries={total}")
    print(f"wrote {OUTPUT_PATH}")

    if args.check_priority:
        priority = json.loads(
            (ROOT / "seeds" / "aoe3" / "civ_war_priority_techs.json").read_text(
                encoding="utf-8"
            )
        )["techs"]
        owners: dict[str, list[str]] = {}
        for civ_id, data in payload["civs"].items():
            for tech_id in data["all"]:
                owners.setdefault(tech_id, []).append(civ_id)
        for row in priority:
            tech_id = row["id"]
            print(f"{tech_id}: {', '.join(owners.get(tech_id, [])) or 'MISSING'}")


if __name__ == "__main__":
    main()
