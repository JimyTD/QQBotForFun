"""YR Tier B/C 单位斗蛐蛐降级规则测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.games.ra2_battle.battle_armament import (
    armament_battle_allowed,
    weapon_battle_denied,
)
from plugins.games.ra2_battle.repo import load_actors
from plugins.games.ra2_battle.simulator import BattleSimulator, EventType
from plugins.games.ra2_battle.targeting import armament_allowed

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2，先运行 openra_ra2_export.py")


@pytest.fixture(scope="module")
def actors(require_export):
    return load_actors()


def test_slav_shovel_always_allowed(actors):
    slav = actors["slav"]
    shovel = next(a for a in slav.armaments if a.weapon == "shovel")
    assert armament_battle_allowed(shovel, slav, veterancy_level=0)


def test_ytnk_stage1_only(actors):
    ytnk = actors["ytnk"]
    allowed = {
        a.weapon
        for a in ytnk.armaments
        if armament_battle_allowed(a, ytnk, veterancy_level=0)
    }
    assert allowed == {"AGGattling", "AAGattling"}


def test_schp_flight_cannon_only(actors):
    schp = actors["schp"]
    allowed = {
        a.weapon
        for a in schp.armaments
        if armament_battle_allowed(a, schp, veterancy_level=0)
    }
    assert "BlackHawkCannon" in allowed
    assert "160mm" not in allowed


def test_disk_no_drain(actors):
    assert weapon_battle_denied("disk", "DiskDrain")
    assert not weapon_battle_denied("disk", "DiskLaser")


def test_mind_capacity_exported(actors):
    assert actors["mind"].mind_control_capacity == 3


def test_slav_vs_e2_completes(actors):
    r = BattleSimulator([("slav", 3)], [("e2", 5)], seed=1, max_ticks=6000).run()
    assert r.ticks > 0
    assert {e.type for e in r.events} & {EventType.ATTACK, EventType.DEATH}


def test_disk_vs_htnk_completes(actors):
    r = BattleSimulator([("disk", 1)], [("htnk", 2)], seed=2, max_ticks=8000).run()
    attacks = [e for e in r.events if e.type == EventType.ATTACK]
    assert any(e.payload.get("weapon") == "DiskLaser" for e in attacks)
    assert not any(e.payload.get("weapon") == "DiskDrain" for e in attacks)


def test_tele_magneshake_only(actors):
    tele = actors["tele"]
    allowed = {
        a.weapon
        for a in tele.armaments
        if armament_allowed(a, actor=tele)
    }
    assert allowed == {"MagneShake"}


def test_dlph_sonic_zap_deals_damage(actors):
    """SonicZap AreaBeam 多段伤害（Duration/DamageInterval）。"""
    r = BattleSimulator([("hyd", 5)], [("dlph", 9)], seed=0, max_ticks=8000).run()
    dlph_attacks = [
        e for e in r.events if e.type == EventType.ATTACK and e.payload.get("attacker") == "dlph"
    ]
    total = sum(e.payload.get("damage", 0) for e in dlph_attacks)
    assert len(dlph_attacks) >= 80
    assert total >= 150


def test_mind_controls_up_to_three(require_export):
    r = BattleSimulator(
        [("mind", 1)],
        [("e1", 1), ("e2", 1), ("init", 1), ("brute", 1)],
        seed=5,
        max_ticks=8000,
        width=14,
        height=8,
    ).run()
    mc = [e for e in r.events if e.type == EventType.MIND_CONTROL]
    assert len(mc) >= 2, "心灵控制车应能控多个目标"
