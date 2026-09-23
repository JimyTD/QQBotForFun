"""Playable civ-war integration with the existing battle state machine."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from core.types import GameContext
from plugins.games.aoe3_battle.game import AoE3BattleGame, session
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D


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

    result = BattleSimulator2D(
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


@pytest.mark.asyncio
async def test_civ_war_sends_image_and_short_bet_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game = AoE3BattleGame()
    ctx = GameContext(
        session_id="TESTCW3",
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
    rich = AsyncMock()
    plain = AsyncMock()
    monkeypatch.setattr(session, "broadcast_rich", rich)
    monkeypatch.setattr(session, "broadcast", plain)

    await game.on_start(ctx)

    rich.assert_awaited_once()
    image_message = rich.await_args.args[1]
    assert "base64://" in str(image_message)
    fallback = rich.await_args.args[2]
    assert "押红方" in fallback
    assert "押蓝方" in fallback
    plain.assert_not_awaited()
