"""AoE3 parser 攻击代表动作选型 fixture。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

RAW_DIR = ROOT / "data" / "aoe3" / "raw"
UNITS_PATH = ROOT / "seeds" / "aoe3" / "units.json"

pytestmark = pytest.mark.skipif(
    not RAW_DIR.joinpath("protoy.xml").is_file(),
    reason="data/aoe3/raw/protoy.xml not present",
)


@pytest.fixture(scope="module")
def units_by_id() -> dict[str, dict]:
    assert UNITS_PATH.is_file(), "run aoe3_gamedata_parser.py first"
    units = json.loads(UNITS_PATH.read_text(encoding="utf-8"))
    return {u["id"]: u for u in units}


def _actions(u: dict) -> dict[str, dict]:
    return {a["name"]: a for a in u.get("attack_actions", [])}


@pytest.mark.parametrize(
    "unit_id,action_name,range_val,windup_r",
    [
        ("musketeer", "VolleyRangedAttack", 12.0, 0.48),
        ("skirmisher", "VolleyRangedAttack", 20.0, 0.46),
        ("dragoon", "StaggerRangedAttack", 12.0, 0.43),
        ("mercmanchu", "BowAttack", 12.0, None),
        ("demercirishbrigadier", "VolleyRangedAttack", 12.0, 0.48),
        ("longbowman", "VolleyRangedAttack", 22.0, 0.98),
        ("cannon", "CannonAttack", 28.0, 0.0),
    ],
)
def test_attack_selection(
    units_by_id: dict[str, dict],
    unit_id: str,
    action_name: str,
    range_val: float,
    windup_r: float | None,
) -> None:
    u = units_by_id[unit_id]
    action = _actions(u).get(action_name)
    assert action is not None, u
    assert action["range_max"] == range_val, u
    if windup_r is not None:
        assert action.get("windup", 0.0) == windup_r, u


def test_irish_brigadier_has_ranged_attack(units_by_id: dict[str, dict]) -> None:
    u = units_by_id["demercirishbrigadier"]
    action = _actions(u)["VolleyRangedAttack"]
    assert action["damage"] == 25.0
    assert action["range_max"] == 12.0


def test_explorer_uses_volley_not_sharpshooter(units_by_id: dict[str, dict]) -> None:
    u = units_by_id["explorer"]
    action = _actions(u)["VolleyRangedAttack"]
    assert action["damage"] == 12.0


def test_inca_warchief_no_crackshot_ranged(units_by_id: dict[str, dict]) -> None:
    """Crackshot 是英雄技，不进攻击列表；斗蛐蛐用 HandAttack。"""
    u = units_by_id["deincawarchief"]
    actions = _actions(u)
    assert "CrackshotAttack" not in actions
    assert actions["HandAttack"]["damage"] == 6.0


def test_fire_thrower_uses_real_grenade_not_guardian(
    units_by_id: dict[str, dict],
) -> None:
    u = units_by_id["dehoopthrower"]
    action = _actions(u)["GrenadeAttack"]
    assert action["damage"] == 16.0
    assert action["aoe_radius"] == 2
    assert action["damage_cap"] == 32.0


@pytest.mark.parametrize(
    "unit_id,radius_x,radius_z,radius_equiv",
    [
        ("musketeer", 0.49, 0.49, 0.49),
        ("falconet", 0.99, 0.99, 0.99),
        ("ypmahout", 0.39, 0.89, 0.5892),
        ("deafricancatamaran", 1.59, 1.99, 1.7788),
    ],
)
def test_unit_obstruction_radii_are_parsed(
    units_by_id: dict[str, dict],
    unit_id: str,
    radius_x: float,
    radius_z: float,
    radius_equiv: float,
) -> None:
    u = units_by_id[unit_id]
    assert u.get("obstruction_radius_x") == radius_x
    assert u.get("obstruction_radius_z") == radius_z
    assert u.get("obstruction_radius_equiv") == radius_equiv
