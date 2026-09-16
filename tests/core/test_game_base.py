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


# =====================================================================
# 整局兜底超时：**全仓库统一**
# =====================================================================
def test_session_timeout_is_unified_24h() -> None:
    """整局兜底超时统一：一个全局配置 + 基类默认值，任何游戏都不再各写一份。

    为什么必须有它：真人**没有单步超时**（大原则：「AI 有超时，真实玩家没有」），
    所以"有人挂机就把这局僵在那儿"是可接受的，但"永久僵着"会把整个群占死。
    """
    from src.settings import get_settings

    assert get_settings().game_session_timeout_hours == 24
    # 任何子类都继承同一个值（示例游戏没有覆盖它）
    assert _SampleGame().default_session_timeout_seconds == 24 * 3600


async def test_create_and_start_falls_back_to_the_unified_timeout(monkeypatch) -> None:
    """`create_and_start` 不显式传超时时，必须自动取游戏的默认值。

    这条锁的是一个真实缺陷：`default_session_timeout_seconds` 以前在三个游戏里
    各定义了一份，但**没有任何地方读它**，等于生产环境根本没有整局超时。
    """
    from unittest.mock import AsyncMock

    from core import scheduler as cscheduler
    from core import session as csession

    monkeypatch.setattr(csession, "register_game_session", AsyncMock())
    monkeypatch.setattr(csession, "unregister_game_session", AsyncMock())
    monkeypatch.setattr(csession, "broadcast", AsyncMock())

    scheduled: list[tuple] = []
    monkeypatch.setattr(
        cscheduler,
        "start_turn_timer",
        AsyncMock(side_effect=lambda *args, **kwargs: scheduled.append((args, kwargs))),
    )

    user = User(qq_id=2001, nickname="P", group_id=8888)
    runner = await game_base.create_and_start(
        "sample_game",
        group_id=8888,
        host_id=2001,
        players=[user],
    )
    await runner.end(EndReason.COMPLETED)

    assert scheduled, "没有排整局超时 —— 有人挂机就会永久僵住"
    _args, _kwargs = scheduled[0]
    assert _args[1] == 24 * 3600
