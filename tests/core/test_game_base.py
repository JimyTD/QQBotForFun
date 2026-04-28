"""game_base 测试。"""

from __future__ import annotations

import pytest

from core import game_base
from core.errors import GameAlreadyRunningError, GameNotFoundError
from core.game_base import GameBase, register_game
from core.types import EndReason, GameContext, User


@register_game
class _SampleGame(GameBase):
    id = "sample_game"
    name = "示例游戏"
    description = "for tests"
    min_players = 1
    max_players = 5
    version = "1.0"
    event_driven = False

    started: bool = False
    ended_reason: EndReason | None = None

    async def on_start(self, ctx: GameContext) -> None:
        self.__class__.started = True
        ctx.state["started"] = True

    async def on_end(self, ctx: GameContext, reason: EndReason) -> None:
        self.__class__.ended_reason = reason


async def test_register_and_list() -> None:
    assert any(g.id == "sample_game" for g in game_base.list_games())
    assert game_base.get_game_class("sample_game") is _SampleGame


async def test_get_unknown_raises() -> None:
    with pytest.raises(GameNotFoundError):
        game_base.get_game_class("__no_such__")


async def test_create_and_end(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # mock session.register/unregister 以避免真实 NoneBot 调用
    from unittest.mock import AsyncMock

    from core import session as csession

    monkeypatch.setattr(csession, "register_game_session", AsyncMock())
    monkeypatch.setattr(csession, "unregister_game_session", AsyncMock())
    monkeypatch.setattr(csession, "broadcast", AsyncMock())

    _SampleGame.started = False
    _SampleGame.ended_reason = None

    user = User(qq_id=1001, nickname="P", group_id=9999)
    runner = await game_base.create_and_start(
        "sample_game",
        group_id=9999,
        host_id=1001,
        players=[user],
    )
    assert _SampleGame.started is True
    assert runner.ctx.group_id == 9999

    # 同群再开一局应报错
    with pytest.raises(GameAlreadyRunningError):
        await game_base.create_and_start(
            "sample_game",
            group_id=9999,
            host_id=1001,
            players=[user],
        )

    await runner.end(EndReason.COMPLETED)
    assert _SampleGame.ended_reason == EndReason.COMPLETED
    assert game_base.get_runner_by_group(9999) is None
