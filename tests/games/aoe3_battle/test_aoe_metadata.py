"""Regression checks for AOE metadata flowing from tactics into the seed."""

import json
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parents[3] / "seeds" / "aoe3" / "units.json"


def _unit(unit_id: str) -> dict:
    units = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return next(unit for unit in units if unit["id"] == unit_id)


def test_falconet_exposes_directional_outer_damage_metadata() -> None:
    falconet = _unit("falconet")
    cannon = next(a for a in falconet["attack_actions"] if a["name"] == "CannonAttack")

    assert cannon["area_sort_mode"] == "Directional"
    assert cannon["outer_damage_area_distance"] == 0.25
    assert cannon["outer_damage_area_factor"] == 0.2


def test_mortar_uses_radial_area_sort_metadata() -> None:
    mortar = _unit("mortar")
    action = next(
        a for a in mortar["attack_actions"] if a.get("area_sort_mode") == "Radial"
    )

    assert action["area_sort_mode"] == "Radial"
