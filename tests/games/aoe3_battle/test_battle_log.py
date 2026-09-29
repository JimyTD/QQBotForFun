"""Battle-log serialization keeps the selected tech IDs auditable."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace

from plugins.games.aoe3_battle.battle_contract import ArmySlot, Side
from plugins.games.aoe3_battle import game
from plugins.games.aoe3_battle.game import _dump_battle_log
from plugins.games.aoe3_battle.lineup import Lineup, MatchLineup, UnitSlot


@dataclass
class _Result:
    winner: Side | None
    events: list
    ticks: int
    duration: float
    red_alive: list
    blue_alive: list
    red_dead: list
    blue_dead: list
    red_army: list
    blue_army: list
    red_count: int
    blue_count: int
    timeout: bool = False


def test_battle_log_records_selected_techs(monkeypatch, tmp_path) -> None:
    red_unit = SimpleNamespace(
        id="xpskullknight",
        name="风云骷髅武士",
        type=("AbstractInfantry",),
        hp=480,
        attack_ranged=0.0,
        attack_melee=30.0,
        attack_siege=72.0,
        armor_ranged=0.0,
        armor_melee=0.2,
        speed=4.25,
        range=0.0,
        range_min=0.0,
        aoe_radius=3,
        pop=2,
        name_en="Skull Knight",
        cost={"gold": 250},
    )
    blue_unit = SimpleNamespace(
        id="decarolean",
        name="护卫卡尔远征军",
        type=("AbstractInfantry",),
        hp=225,
        attack_ranged=28.5,
        attack_melee=30.0,
        attack_siege=20.0,
        armor_ranged=0.0,
        armor_melee=0.2,
        speed=4.25,
        range=15.0,
        range_min=3.0,
        aoe_radius=0,
        pop=1,
        name_en="Carolean",
        cost={"food": 60, "gold": 40},
    )
    match = MatchLineup(
        red=Lineup([UnitSlot(red_unit, 38)]),
        blue=Lineup([UnitSlot(blue_unit, 67)]),
        mode="lineup",
        age=4,
        red_tech_ids=("HCXPGreatTempleHuitzilopochtli",),
        blue_tech_ids=("DEHCSnaplocks", "DEHCPlatoonFire"),
        red_tech_names=("战神大神庙援助",),
        blue_tech_names=("弹簧枪机", "轮射"),
    )
    result = _Result(
        winner=Side.BLUE,
        events=[],
        ticks=199,
        duration=19.9,
        red_alive=[],
        blue_alive=[],
        red_dead=[],
        blue_dead=[],
        red_army=[ArmySlot(red_unit, 38)],
        blue_army=[ArmySlot(blue_unit, 67)],
        red_count=38,
        blue_count=67,
    )
    monkeypatch.setattr(game, "BATTLE_LOG_DIR", tmp_path)

    _dump_battle_log("TECHLOG", match, result)

    summary = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    full = json.loads(next(tmp_path.glob("*.full.json")).read_text(encoding="utf-8"))
    expected = {
        "red": {
            "ids": ["HCXPGreatTempleHuitzilopochtli"],
            "names": ["战神大神庙援助"],
        },
        "blue": {
            "ids": ["DEHCSnaplocks", "DEHCPlatoonFire"],
            "names": ["弹簧枪机", "轮射"],
        },
    }
    assert summary["techs"] == expected
    assert full["techs"] == expected
