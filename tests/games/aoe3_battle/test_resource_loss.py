"""帝国3斗蛐蛐战损资源统计测试。"""
from __future__ import annotations

from plugins.aoe3.models import Unit
from plugins.games.aoe3_battle.battle_contract import (
    ArmySlot,
    BattleResult,
    Side,
)
from plugins.games.aoe3_battle.broadcaster import (
    battle_resource_loss,
    format_battle_report,
)


class _DeadSoldier:
    def __init__(self, *, side: Side, unit: Unit, alive: bool) -> None:
        self.side = side
        self.unit = unit
        self.hp = 50.0 if alive else 0.0
        self.max_hp = 50.0
        self.alive = alive
        self.kills = 0
        self.total_damage_dealt = 0.0
        self.raw_damage_dealt = 0.0
        self.overkill_damage = 0.0
        self.id = 1
        self.name = getattr(unit, "name", unit.id)


def _soldier(
    *,
    side: Side,
    unit: Unit,
    alive: bool,
    ) -> _DeadSoldier:
    return _DeadSoldier(side=side, unit=unit, alive=alive)


def _unit(unit_id: str, *, food: int = 0, wood: int = 0, gold: int = 0, pop: int = 99) -> Unit:
    return Unit(
        id=unit_id,
        name=unit_id,
        name_en=unit_id,
        hp=50,
        cost={"food": food, "wood": wood, "gold": gold},
        pop=pop,
    )


def _result(
    red_dead: list[_DeadSoldier],
    blue_dead: list[_DeadSoldier],
) -> BattleResult:
    red_unit = red_dead[0].unit if red_dead else _unit("red")
    blue_unit = blue_dead[0].unit if blue_dead else _unit("blue")
    return BattleResult(
        winner=Side.RED,
        events=[],
        ticks=1,
        duration=1.0,
        red_alive=[],
        blue_alive=[],
        red_dead=red_dead,
        blue_dead=blue_dead,
        red_army=[ArmySlot(red_unit, max(1, len(red_dead)))],
        blue_army=[ArmySlot(blue_unit, max(1, len(blue_dead)))],
        red_count=max(1, len(red_dead)),
        blue_count=max(1, len(blue_dead)),
    )


def test_battle_resource_loss_sums_all_resources_without_pop():
    red = _unit("red", food=80, wood=20, gold=40, pop=100)
    blue = _unit("blue", food=10, wood=30, gold=60, pop=100)
    result = _result(
        [_soldier(side=Side.RED, unit=red, alive=False)],
        [_soldier(side=Side.BLUE, unit=blue, alive=False)],
    )

    assert battle_resource_loss(result) == (140, 100)


def test_battle_resource_loss_counts_only_dead():
    red = _unit("red", food=80, gold=20)
    result = _result(
        [
            _soldier(side=Side.RED, unit=red, alive=False),
            _soldier(side=Side.RED, unit=red, alive=False),
        ],
        [],
    )

    assert battle_resource_loss(result) == (200, 0)


def test_battle_report_contains_resource_loss_line():
    red = _unit("red", food=100, gold=50)
    blue = _unit("blue", wood=100, gold=80)
    result = _result(
        [_soldier(side=Side.RED, unit=red, alive=False)],
        [_soldier(side=Side.BLUE, unit=blue, alive=False)],
    )

    report = format_battle_report(result)

    assert "💸 战损资源：红方 150 ｜ 蓝方 180" in report
    assert "全灭" not in report
    assert "存活0" in report


def test_battle_resource_loss_zero_when_nobody_died():
    result = _result([], [])

    assert battle_resource_loss(result) == (0, 0)
