"""战中升级与出战星级（对齐 OpenRA GainsExperience）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.games.ra2_battle.experience import (
    apply_initial_stars,
    grant_experience,
    xp_thresholds,
)
from plugins.games.ra2_battle.repo import load_actors, load_veterancy_rules
from plugins.games.ra2_battle.simulator import BattleSimulator, EventType
from plugins.games.ra2_battle.experience import UnitVeterancy

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "veterancy.json"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2/veterancy.json，先运行 openra_ra2_export.py")


@pytest.fixture(scope="module")
def actors(require_export):
    return load_actors()


def test_xp_threshold_scales_with_cost(actors):
    htnk = actors["htnk"]
    ge = htnk.gains_experience
    assert ge is not None
    assert xp_thresholds(htnk, ge) == [4500, 9000]


def test_initial_stars_zero_is_rookie(actors):
    htnk = actors["htnk"]
    ge = htnk.gains_experience
    assert ge is not None
    vet = UnitVeterancy()
    apply_initial_stars(vet, 0, htnk, ge)
    assert vet.level == 0
    assert vet.experience == 0


def test_initial_stars_one_is_veteran(actors):
    htnk = actors["htnk"]
    ge = htnk.gains_experience
    assert ge is not None
    vet = UnitVeterancy()
    apply_initial_stars(vet, 1, htnk, ge)
    assert vet.level == 1
    assert vet.experience == 4500


def test_initial_stars_three_is_elite(actors):
    htnk = actors["htnk"]
    ge = htnk.gains_experience
    assert ge is not None
    vet = UnitVeterancy()
    apply_initial_stars(vet, 3, htnk, ge)
    assert vet.level == 2
    assert vet.experience == 9000


def test_grant_experience_unit(actors):
    htnk = actors["htnk"]
    ge = htnk.gains_experience
    assert ge is not None
    vet = UnitVeterancy()
    assert grant_experience(vet, 4500, htnk, ge) == 1
    assert vet.level == 1


def test_three_star_mtnk_uses_elite_weapon(require_export):
    result = BattleSimulator(
        [("mtnk", 1, 3)],
        [("e1", 5, 1)],
        seed=0,
        max_ticks=6000,
        width=12,
        height=6,
    ).run()
    weapons = {
        e.payload["weapon"]
        for e in result.events
        if e.type == EventType.ATTACK and e.payload.get("attacker") == "mtnk"
    }
    assert any(w.endswith("E") for w in weapons), f"三星应使用精英武器: {weapons}"


def test_veterancy_rules_loaded(require_export):
    rules = load_veterancy_rules()
    assert rules.firepower_elite == 130
    assert rules.reload_delay_elite == 75
