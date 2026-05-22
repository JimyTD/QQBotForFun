"""红警2斗蛐蛐基础测试（依赖 data/ra2 导出）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.games.ra2_battle.damage import calc_damage
from plugins.games.ra2_battle.repo import WarheadDef, load_actors, resolve_weapon
from plugins.games.ra2_battle.simulator import BattleSimulator
from plugins.games.ra2_battle.targeting import armament_allowed, weapon_valid_against

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2，先运行 openra_ra2_export.py")


def test_armament_non_elite(require_export):
    from plugins.games.ra2_battle.repo import ArmamentDef

    elite = ArmamentDef("b", "120mmE", "rank-elite", "primary")
    normal = ArmamentDef("a", "120mm", "!rank-elite", "primary")
    assert armament_allowed(normal, veterancy_level=0)
    assert not armament_allowed(elite, veterancy_level=0)
    assert armament_allowed(elite, veterancy_level=2)
    assert not armament_allowed(normal, veterancy_level=2)


def test_120mm_vs_heavy(require_export):
    w = resolve_weapon("120mm")
    assert w is not None
    wh = w.warheads[0]
    assert calc_damage(wh, "Heavy") == 90


def test_htnk_vs_mtnk_completes(require_export):
    sim = BattleSimulator([("htnk", 1)], [("mtnk", 1)], seed=42, max_ticks=3000)
    result = sim.run()
    assert result.winner is not None
    assert len(result.red_alive) + len(result.blue_alive) >= 1


def test_mammoth_tusk_not_vs_ground_vehicle(require_export):
    """MammothTusk 继承 ^AAMissile，ValidTargets 仅 Air。"""
    actors = load_actors()
    from plugins.games.ra2_battle.repo import load_weapons

    weapons = load_weapons()
    assert not weapon_valid_against(weapons["MammothTusk"], actors["htnk"])


def test_apoc_vs_htnk_completes(require_export):
    result = BattleSimulator(
        [("apoc", 1)], [("htnk", 5)], seed=0, max_ticks=8000
    ).run()
    assert result.winner is not None
    weapons_used = {
        e.payload["weapon"]
        for e in result.events
        if e.type.value == "ATTACK" and e.payload.get("attacker") == "apoc"
    }
    assert "120mmx" in weapons_used or "120mmxE" in weapons_used
    assert "MammothTusk" not in weapons_used


def test_projectile_delays_first_hit(require_export):
    """有 Projectile.Speed 的武器，首段伤害不落在开火 tick。"""
    result = BattleSimulator(
        [("e1", 1)],
        [("e1", 1)],
        seed=0,
        max_ticks=2000,
        width=10,
        height=6,
    ).run()
    attacks = [e for e in result.events if e.type.value == "ATTACK"]
    assert attacks, "应对射并产生伤害事件"
    assert attacks[0].tick > 0


def test_naval_can_fight(require_export):
    result = BattleSimulator(
        [("dest", 1)],
        [("dest", 1)],
        seed=1,
        max_ticks=8000,
        width=12,
    ).run()
    attacks = [e for e in result.events if e.type.value == "ATTACK"]
    assert len(attacks) >= 1
    assert result.ticks <= 8000
