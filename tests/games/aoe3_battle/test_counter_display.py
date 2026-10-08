# ruff: noqa: RUF001
"""Pre-battle multiplier display must match simulator multiplication."""

from __future__ import annotations

import pytest

from plugins.aoe3.attack_actions import priority_shots
from plugins.aoe3.formatter import render_compare, render_unit_card
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

    assert outgoing == ["克制 帝国野战炮（MeleeHandAttack，炮兵 x1.34 = x1.34）"]
    text = format_side_panel(lineup, "red", "custom", opponent=opponent)
    assert "✅ 克制 帝国野战炮（MeleeHandAttack，炮兵 x1.34 = x1.34）" in text


def test_positive_and_negative_multipliers_are_multiplied(repo: UnitRepo) -> None:
    yumi = repo.get_by_id("ypyumi")
    dragoon = repo.get_by_id("dragoon")
    lineup = Lineup(slots=[UnitSlot(yumi, 20)])
    opponent = Lineup(slots=[UnitSlot(dragoon, 20)])

    outgoing, _ = _find_counter_relations(yumi, opponent)

    assert outgoing == [
        "克制 枪骑兵（VolleyRangedAttack，轻型骑兵 x2.5 × 骑兵 x0.6 = x1.5）",
        "克制 枪骑兵（VolleyHandAttack，轻型骑兵 x2 × 骑兵 x0.75 = x1.5）",
    ]
    text = format_side_panel(lineup, "red", "custom", opponent=opponent)
    assert "✅ 克制 枪骑兵（VolleyRangedAttack，轻型骑兵 x2.5 × 骑兵 x0.6 = x1.5）" in text
    assert "✅ 克制 枪骑兵（VolleyHandAttack，轻型骑兵 x2 × 骑兵 x0.75 = x1.5）" in text


def test_incoming_multipliers_show_complete_product(repo: UnitRepo) -> None:
    cavalry_archer = repo.get_by_id("cavalryarcher")
    yumi = repo.get_by_id("ypyumi")
    opponent = Lineup(slots=[UnitSlot(yumi, 20)])

    outgoing, incoming = _find_counter_relations(cavalry_archer, opponent)

    assert not outgoing
    assert incoming == [
        "被 日本长弓兵 克制（VolleyRangedAttack，轻型骑兵 x2.5 × 骑兵 x0.6 = x1.5）",
        "被 日本长弓兵 克制（VolleyHandAttack，轻型骑兵 x2 × 骑兵 x0.75 = x1.5）",
    ]


def test_priority_shots_keep_tactic_order_on_a_tie():
    from plugins.aoe3.attack_actions import AttackAction

    def _action(name: str, priority: int) -> AttackAction:
        return AttackAction(
            name=name,
            priority=priority,
            damage=10,
            damage_type="Ranged",
            range_min=0,
            range_max=6,
            rof=3,
        )

    shots = priority_shots([
        _action("VolleyRangedAttack", 100),
        _action("BuildingAttack", 75),
        _action("VolleyHandAttack", 75),
    ])
    assert [action.name for action in shots] == ["VolleyRangedAttack", "BuildingAttack"]


def test_unit_card_shows_the_two_highest_priority_actions(repo: UnitRepo) -> None:
    musk = repo.get_by_id("musketeer")
    assert musk is not None
    card = render_unit_card(musk)
    assert "VolleyRangedAttack" in card
    assert "BuildingAttack" in card
    assert "VolleyHandAttack" not in card
    assert "远程攻击" not in card
    compared = render_compare(musk, musk)
    assert "攻击1" in compared and "VolleyRangedAttack" in compared
    assert "远程攻击" not in compared
