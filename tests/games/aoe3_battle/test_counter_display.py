# ruff: noqa: RUF001
"""Pre-battle multiplier display must match simulator multiplication."""

from __future__ import annotations

import pytest

from plugins.aoe3.repository import UnitRepo
from plugins.aoe3.upgrades import apply_upgrades
from plugins.games.aoe3_battle.lineup import (
    Lineup,
    UnitSlot,
    _find_counter_relations,
    format_side_panel,
)


@pytest.fixture(scope="module")
def repo() -> UnitRepo:
    return UnitRepo.get()


def test_low_positive_multiplier_is_visible(repo: UnitRepo) -> None:
    meteor = apply_upgrades(repo.get_by_id("ypmeteorhammer"), 5)
    falconet = apply_upgrades(repo.get_by_id("falconet"), 5)
    lineup = Lineup(slots=[UnitSlot(meteor, 52)])
    opponent = Lineup(slots=[UnitSlot(falconet, 19)])

    outgoing, _ = _find_counter_relations(meteor, opponent)

    assert outgoing == ["对帝国野战炮 近战 x1.34（炮兵 x1.34）"]
    text = format_side_panel(lineup, "red", "custom", opponent=opponent)
    assert "🎯 对帝国野战炮 近战 x1.34（炮兵 x1.34）" in text


def test_positive_and_negative_multipliers_are_multiplied(repo: UnitRepo) -> None:
    yumi = repo.get_by_id("ypyumi")
    dragoon = repo.get_by_id("dragoon")
    lineup = Lineup(slots=[UnitSlot(yumi, 20)])
    opponent = Lineup(slots=[UnitSlot(dragoon, 20)])

    outgoing, _ = _find_counter_relations(yumi, opponent)

    assert outgoing == [
        "对枪骑兵 远程 x1.5（轻型骑兵 x2.5 × 骑兵 x0.6）",
        "对枪骑兵 近战 x1.5（轻型骑兵 x2 × 骑兵 x0.75）",
    ]
    text = format_side_panel(lineup, "red", "custom", opponent=opponent)
    assert "🎯 对枪骑兵 远程 x1.5（轻型骑兵 x2.5 × 骑兵 x0.6）" in text
    assert "🎯 对枪骑兵 近战 x1.5（轻型骑兵 x2 × 骑兵 x0.75）" in text


def test_incoming_multipliers_show_complete_product(repo: UnitRepo) -> None:
    cavalry_archer = repo.get_by_id("cavalryarcher")
    yumi = repo.get_by_id("ypyumi")
    opponent = Lineup(slots=[UnitSlot(yumi, 20)])

    outgoing, incoming = _find_counter_relations(cavalry_archer, opponent)

    assert not outgoing
    assert incoming == [
        "受日本长弓兵远程攻击 承伤 x1.5（轻型骑兵 x2.5 × 骑兵 x0.6）",
        "受日本长弓兵近战攻击 承伤 x1.5（轻型骑兵 x2 × 骑兵 x0.75）",
    ]
