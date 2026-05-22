"""AreaBeam 持续伤害、副炮导出、Versus 护甲倍率。"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.games.ra2_battle.beam import beam_damage_pulse_offsets
from plugins.games.ra2_battle.damage import calc_damage
from plugins.games.ra2_battle.miniyaml import load_miniyaml_file
from plugins.games.ra2_battle.openra_yaml import merge_actor, load_rules_dir
from plugins.games.ra2_battle.repo import load_actors, resolve_weapon
from plugins.games.ra2_battle.simulator import BattleSimulator, EventType

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"
_VENDOR = Path(__file__).resolve().parents[3].parent / "vendor-openra" / "yuris-revenge"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2，先运行 openra_ra2_export.py")


@pytest.fixture(scope="module")
def actors(require_export):
    return load_actors()


def test_miniyaml_parses_hyd_secondary_armament():
    if not (_VENDOR / "mods/yr/rules/soviet-naval.yaml").is_file():
        pytest.skip("无 vendor/yuris-revenge")
    chunk = load_miniyaml_file(_VENDOR / "mods/yr/rules/soviet-naval.yaml")
    assert "Armament@secondary" in chunk["hyd"]
    raw = load_rules_dir(_VENDOR / "mods/yr/rules")
    cache: dict = {}
    merged = merge_actor("hyd", raw, cache)
    weapons = {
        block.get("Weapon")
        for key, block in merged.items()
        if key.startswith("Armament") and isinstance(block, dict)
    }
    assert weapons == {"FlakTrackGun", "FlakWeapon"}


def test_hyd_exports_both_armaments(actors):
    weapons = {a.weapon for a in actors["hyd"].armaments}
    assert weapons == {"FlakTrackGun", "FlakWeapon"}


def test_apoc_exports_antiair(actors):
    weapons = {a.weapon for a in actors["apoc"].armaments}
    assert "120mmx" in weapons
    assert "MammothTusk" in weapons


def test_sonic_zap_beam_pulse_count(require_export):
    w = resolve_weapon("SonicZap")
    assert w.projectile_kind == "AreaBeam"
    assert w.beam_duration == 10
    assert w.beam_damage_interval == 5
    assert beam_damage_pulse_offsets(w) == (5, 10)


def test_dlph_beam_damage_vs_hyd(require_export):
    r = BattleSimulator([("hyd", 5)], [("dlph", 9)], seed=0, max_ticks=8000).run()
    dlph_atk = [
        e for e in r.events
        if e.type == EventType.ATTACK and e.payload.get("attacker") == "dlph"
    ]
    total = sum(e.payload.get("damage", 0) for e in dlph_atk)
    assert len(dlph_atk) >= 80, f"海豚应有多段声波伤害，实际 {len(dlph_atk)} 击"
    assert total >= 150, f"海豚总伤过低: {total}"


def test_tany_vs_htnk_uses_c4_not_pistols(require_export):
    """手枪 Versus Heavy=0；对载具应贴脸 C4，不应用手枪。"""
    wh = resolve_weapon("DoublePistols").warheads[0]
    assert calc_damage(wh, "Heavy") == 0
    r = BattleSimulator([("tany", 1)], [("htnk", 1)], seed=0, max_ticks=8000).run()
    pistol_atk = [
        e for e in r.events
        if e.type == EventType.ATTACK
        and e.payload.get("attacker") == "tany"
        and e.payload.get("weapon") == "DoublePistols"
    ]
    c4_atk = [
        e for e in r.events
        if e.type == EventType.ATTACK
        and e.payload.get("attacker") == "tany"
        and e.payload.get("weapon") == "C4"
    ]
    assert not pistol_atk
    assert c4_atk, "谭雅应对犀牛使用 C4"
    assert c4_atk[0].payload.get("damage", 0) > 0


def test_tany_vs_e1_deals_damage(require_export):
    r = BattleSimulator([("tany", 1)], [("e1", 5)], seed=1, max_ticks=4000).run()
    tany_atk = [
        e for e in r.events
        if e.type == EventType.ATTACK and e.payload.get("attacker") == "tany"
    ]
    assert tany_atk
    assert sum(e.payload.get("damage", 0) for e in tany_atk) > 0
