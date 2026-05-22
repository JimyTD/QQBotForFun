"""炮塔转向与 Blockable 弹道。"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.games.ra2_battle.repo import load_actors, load_weapons, resolve_weapon
from plugins.games.ra2_battle.simulator import BattleSimulator, EventType

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2，先运行 openra_ra2_export.py")


def test_htnk_has_turret_export(require_export):
    h = load_actors()["htnk"]
    assert h.turret_turn_speed == 5
    assert h.facing_tolerance is not None


def test_120mm_projectile_blockable(require_export):
    w = resolve_weapon("120mm")
    assert w is not None
    assert w.projectile_blockable is True


def test_missile_not_blockable(require_export):
    w = resolve_weapon("MammothTusk")
    assert w is not None
    assert w.projectile_blockable is False


def test_turreted_fires_after_turning(require_export):
    """有炮塔的单位在短对战里仍能造成伤害。"""
    result = BattleSimulator(
        [("htnk", 1)],
        [("e1", 3, 1)],
        seed=11,
        max_ticks=4000,
        width=10,
        height=6,
    ).run()
    attacks = [e for e in result.events if e.type == EventType.ATTACK]
    assert any(e.payload.get("attacker") == "htnk" for e in attacks)
