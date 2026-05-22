"""心控与航母子机。"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.games.ra2_battle.repo import load_actors
from plugins.games.ra2_battle.simulator import BattleSimulator, EventType

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2，先运行 openra_ra2_export.py")


def test_yuri_mind_controls_htnk(require_export):
    result = BattleSimulator(
        [("yuri", 1)],
        [("htnk", 1)],
        seed=3,
        max_ticks=6000,
        width=12,
        height=6,
    ).run()
    mc = [e for e in result.events if e.type == EventType.MIND_CONTROL]
    assert mc, "尤里应对犀牛施放心控"
    assert mc[0].payload["victim"] == "htnk"


def test_carrier_spawns_hornets(require_export):
    actors = load_actors()
    assert "hornet" in actors
    assert actors["carrier"].carrier_parent is not None
    result = BattleSimulator(
        [("carrier", 1)],
        [("e1", 4, 1)],
        seed=7,
        max_ticks=8000,
        width=16,
        height=8,
    ).run()
    spawns = [e for e in result.events if e.type == EventType.SPAWN_CHILD]
    assert len(spawns) >= 1
    attacks = [
        e
        for e in result.events
        if e.type == EventType.ATTACK and e.payload.get("attacker") == "hornet"
    ]
    assert len(attacks) >= 1


def test_carrier_vs_e1_resolves_not_draw(require_export):
    """航母被步兵打沉后舰载机应一并阵亡，不应双方存活拖到 MAX_TICKS 平局。"""
    result = BattleSimulator(
        [("carrier", 1)],
        [("e1", 8, 1)],
        seed=0,
        max_ticks=15000,
        width=14,
        height=8,
    ).run()
    assert result.winner is not None, (
        f"不应平局 ticks={result.ticks} "
        f"red={len(result.red_alive)} blue={len(result.blue_alive)}"
    )
    hornet_alive = [u for u in result.red_alive if u.actor_id == "hornet"]
    assert not hornet_alive
