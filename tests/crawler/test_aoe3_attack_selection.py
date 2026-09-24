"""AoE3 parser 攻击代表动作选型 fixture。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "crawler"))

from aoe3_gamedata_parser import (  # noqa: E402
    TIER_GUARDIAN,
    _melee_hand_priority,
    _ranged_attack_priority,
    _siege_attack_priority,
)

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


@pytest.mark.parametrize(
    "unit_id,proto_ranged,range_val,windup_r",
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
    proto_ranged: str,
    range_val: float,
    windup_r: float | None,
) -> None:
    u = units_by_id[unit_id]
    assert u.get("protoaction_ranged") == proto_ranged, u
    assert u.get("range") == range_val, u
    if windup_r is not None:
        assert u.get("windup_ranged") == windup_r, u


def test_irish_brigadier_has_ranged_attack(units_by_id: dict[str, dict]) -> None:
    u = units_by_id["demercirishbrigadier"]
    assert u.get("attack_ranged") == 25.0
    assert u.get("range") == 12.0
    assert u.get("range") > 0


def test_explorer_uses_volley_not_sharpshooter(units_by_id: dict[str, dict]) -> None:
    u = units_by_id["explorer"]
    assert u.get("protoaction_ranged") == "VolleyRangedAttack"
    assert u.get("attack_ranged") == 12.0


def test_inca_warchief_no_crackshot_ranged(units_by_id: dict[str, dict]) -> None:
    """Crackshot 是英雄技，斗蛐蛐只用 HandAttack 近战槽。"""
    u = units_by_id["deincawarchief"]
    assert u.get("protoaction_ranged") is None
    assert not u.get("attack_ranged")
    assert u.get("protoaction_melee") == "HandAttack"
    assert u.get("attack_melee") == 6.0


@pytest.mark.parametrize(
    "action",
    [
        "GrenadeAttackGuardian",
        "GuardianAttack",
        "GuardianCoverAttack",
        "GuardianHandAttack",
        "GuardianRangedAttack",
        "GuardianSweepAttack",
        "HandAttackGuardian",
        "RocketAttackGuardian",
    ],
)
def test_guardian_actions_are_lowest_priority(action: str) -> None:
    assert _ranged_attack_priority(action, set()) == TIER_GUARDIAN
    assert _melee_hand_priority(action) == TIER_GUARDIAN
    assert _siege_attack_priority(action) == TIER_GUARDIAN


def test_fire_thrower_uses_real_grenade_not_guardian(
    units_by_id: dict[str, dict],
) -> None:
    u = units_by_id["dehoopthrower"]
    assert u.get("protoaction_ranged") == "GrenadeAttack"
    assert u.get("attack_ranged") == 16.0
    assert u.get("aoe_radius_ranged") == 2
    assert u.get("damage_cap_ranged") == 32.0


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
