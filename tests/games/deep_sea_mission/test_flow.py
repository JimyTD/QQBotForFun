from __future__ import annotations

from unittest.mock import AsyncMock

from core import session
from src.plugins.games.deep_sea_mission.game import DeepSeaMissionGame
from src.testing.harness import GameTestHarness


FIXED_HANDS = {
    "1": ["blue:1", "blue:2"],
    "2": ["blue:3", "yellow:1"],
    "3": ["sub:4", "yellow:2"],
}
FIXED_TASKS = [
    {
        "id": "T001",
        "text": "赢得第一墩",
        "difficulty": 1,
        "assigned_to": None,
        "completed": False,
    }
]


async def test_task_selection_and_play_flow(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.build_deck",
        lambda rng=None: [],
    )
    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.deal",
        lambda deck, player_ids: {k: list(v) for k, v in FIXED_HANDS.items()},
    )
    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.draw_tasks",
        lambda difficulty, player_count, rng=None: [dict(FIXED_TASKS[0])],
    )

    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"difficulty": 1},
    ) as h:
        await h.start()
        assert len(h.whispers) == 3
        assert h.runner is not None
        assert h.runner.ctx.state["captain_id"] == 3

        await h.send(1, "选 1")
        assert h.broadcasts_contain("现在轮到 @P3")
        await h.send(3, "选 1")
        assert h.runner.ctx.state["phase"] == "playing"

        await h.send(3, "潜艇4")
        await h.send(1, "蓝1")
        await h.send(2, "黄1")
        assert h.broadcasts_contain("本墩首牌是潜艇")
        await h.send(2, "蓝3")
        assert h.runner.ctx.state["trick_no"] == 2
        assert h.runner.ctx.state["current_player"] == 3


async def test_manual_completion_and_victory_awards(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.build_deck",
        lambda rng=None: [],
    )
    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.deal",
        lambda deck, player_ids: {k: list(v) for k, v in FIXED_HANDS.items()},
    )
    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.draw_tasks",
        lambda difficulty, player_count, rng=None: [dict(FIXED_TASKS[0])],
    )
    award_mock = AsyncMock()
    monkeypatch.setattr(DeepSeaMissionGame, "award", award_mock)

    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"difficulty": 1},
    ) as h:
        await h.start()
        await h.send(3, "选 1")
        await h.send(3, "完成 1")
        assert h.runner is not None
        assert h.runner.ctx.state["tasks"][0]["completed"] is True
        await h.send(1, "胜利")
        assert h.runner._ended is True
        assert h.runner.ctx.state["completed"] is True
        assert award_mock.await_count == 6


async def test_whisper_failure_ends_game(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from core.errors import WhisperFailedError

    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.build_deck",
        lambda rng=None: [],
    )
    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.deal",
        lambda deck, player_ids: {k: list(v) for k, v in FIXED_HANDS.items()},
    )
    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.draw_tasks",
        lambda difficulty, player_count, rng=None: [dict(FIXED_TASKS[0])],
    )

    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"difficulty": 1},
    ) as h:
        monkeypatch.setattr(session, "whisper", AsyncMock(side_effect=WhisperFailedError("no dm")))
        await h.start()
        assert h.runner is not None
        assert h.runner._ended is True
        assert h.runner.game is not None
        assert h.broadcasts_contain("手牌私聊失败")
