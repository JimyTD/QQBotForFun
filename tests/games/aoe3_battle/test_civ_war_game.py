"""Playable civ-war integration with the existing battle state machine."""

from __future__ import annotations

from datetime import datetime

import pytest

from core.types import GameContext
from plugins.games.aoe3_battle.game import AoE3BattleGame
from plugins.games.aoe3_battle.simulator import BattleSimulator


@pytest.mark.asyncio
async def test_civ_war_on_create_builds_serializable_betting_state() -> None:
    game = AoE3BattleGame()
    ctx = GameContext(
        session_id="TESTCW",
        game_id="aoe3_battle",
        group_id=1,
        host_id=2,
        players=[],
        started_at=datetime.utcnow(),
        config={
            "mode": "civ_war",
            "civ_ids": ["British", "Japanese"],
            "age": 3,
            "budget": 10000,
        },
    )

    await game.on_create(ctx)

    assert ctx.state["mode"] == "civ_war"
    assert ctx.state["phase"] == "betting"
    assert ctx.state["civ_war"]["red_civ_name"] == "英国"
    assert ctx.state["civ_war"]["blue_civ_name"] == "日本"
    assert ctx.state["red_army"] and ctx.state["blue_army"]
    assert game._match.mode == "civ_war"

    result = BattleSimulator(
        red_army=[(slot.unit, slot.count) for slot in game._match.red.slots],
        blue_army=[(slot.unit, slot.count) for slot in game._match.blue.slots],
        seed=1,
    ).run()
    assert result.red_count == game._match.red.total_count
    assert result.blue_count == game._match.blue.total_count


@pytest.mark.asyncio
async def test_random_civ_war_ignores_age_two_group_default() -> None:
    game = AoE3BattleGame()
    ctx = GameContext(
        session_id="TESTCW2",
        game_id="aoe3_battle",
        group_id=1,
        host_id=2,
        players=[],
        started_at=datetime.utcnow(),
        config={"mode": "civ_war", "age": 2},
    )
    await game.on_create(ctx)
    assert ctx.state["age"] == 3
    assert ctx.state["civ_war"]["red_civ_id"] != ctx.state["civ_war"]["blue_civ_id"]
