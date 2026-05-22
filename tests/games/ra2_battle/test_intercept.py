"""BlocksProjectiles 弹道拦截。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from plugins.games.ra2_battle.repo import load_actors, resolve_weapon
from plugins.games.ra2_battle.projectile_lane import find_projectile_blocker_between
from plugins.games.ra2_battle.simulator import Side, UnitInstance

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2，先运行 openra_ra2_export.py")


def test_mammoth_tusk_not_blockable(require_export):
    w = resolve_weapon("MammothTusk")
    assert w is not None
    assert w.projectile_blockable is False


def test_find_blocker_on_line(require_export):
    """仅 BlocksProjectiles 挡 Blockable 弹道，普通单位不挡。"""
    actors = load_actors()
    weapon = resolve_weapon("120mm")
    assert weapon is not None and weapon.projectile_blockable

    class _Sim:
        def _cell_occupants(self, cell):
            return self.units.get(cell, [])

    sim = _Sim()
    shield_def = replace(
        actors["mtnk"],
        blocks_projectiles=True,
        blocks_projectiles_height=1024,
        blocks_projectiles_relationships=("Enemy", "Neutral", "Ally"),
    )
    red = Side.RED
    blue = Side.BLUE
    attacker = UnitInstance(
        1, "htnk", red, actors["htnk"], 2, 3, float(actors["htnk"].hp), float(actors["htnk"].hp)
    )
    blocker = UnitInstance(
        2, "mtnk", red, shield_def, 5, 3, 50000.0, 50000.0
    )
    victim = UnitInstance(
        3, "e1", blue, actors["e1"], 7, 3, float(actors["e1"].hp), float(actors["e1"].hp)
    )
    sim.units = {
        (5, 3): [blocker],
        (2, 3): [attacker],
        (7, 3): [victim],
    }
    got = find_projectile_blocker_between(sim, attacker, (2, 3), (7, 3), weapon)
    assert got is not None and got.id == blocker.id

    sim.units = {(4, 3): [UnitInstance(4, "e1", blue, actors["e1"], 4, 3, 100.0, 100.0)]}
    assert find_projectile_blocker_between(sim, attacker, (2, 3), (7, 3), weapon) is None
