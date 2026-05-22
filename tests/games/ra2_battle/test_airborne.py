"""空中 Targetable 层与对战星级。"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.games.ra2_battle.repo import load_actors
from plugins.games.ra2_battle.simulator import BattleSimulator, EventType
from plugins.games.ra2_battle.targeting import (
    effective_target_types,
    weapon_valid_against_unit,
)

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2，先运行 openra_ra2_export.py")


def test_hornet_airborne_target_types(require_export):
    actors = load_actors()
    from plugins.games.ra2_battle.simulator import UnitInstance, Side

    h = actors["hornet"]
    u = UnitInstance(
        id=1,
        actor_id="hornet",
        side=Side.RED,
        actor=h,
        x=0,
        y=0,
        hp=float(h.hp),
        max_hp=float(h.hp),
        airborne=False,
    )
    assert "Ground" in effective_target_types(u) or "Vehicle" in effective_target_types(u)
    u.airborne = True
    assert "Air" in effective_target_types(u)


def test_flak_hits_airborne_hornet(require_export):
    actors = load_actors()
    from plugins.games.ra2_battle.repo import resolve_weapon
    from plugins.games.ra2_battle.simulator import UnitInstance, Side

    hornet = actors["hornet"]
    u = UnitInstance(
        id=1,
        actor_id="hornet",
        side=Side.BLUE,
        actor=hornet,
        x=5,
        y=5,
        hp=float(hornet.hp),
        max_hp=float(hornet.hp),
        airborne=True,
    )
    w = resolve_weapon("FlakTrackAAGun")
    assert w is not None
    assert weapon_valid_against_unit(
        w, hornet, target_types=effective_target_types(u)
    )


def test_initial_stars_in_simulator(require_export):
    result = BattleSimulator(
        [("mtnk", 1, 3)],
        [("e1", 2, 1)],
        seed=5,
        max_ticks=2000,
        width=12,
        height=6,
    ).run()
    elite_attacks = [
        e
        for e in result.events
        if e.type == EventType.ATTACK
        and e.payload.get("attacker") == "mtnk"
        and e.payload.get("attacker_level", 0) >= 2
    ]
    assert elite_attacks
