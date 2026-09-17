"""session.route_incoming_message 路由测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from core import game_base, session
from core.errors import TimeoutError as GameTimeoutError
from core.game_base import GameBase, register_game
from core.types import GameContext, User


@register_game
class _EchoGame(GameBase):
    id = "echo_game_route_test"
    name = "回声测试"
    description = "for route tests"
    event_driven = True

    async def on_player_action(
        self, ctx: GameContext, player_id: int, message: str
    ) -> bool:
        if message.strip() == "ping":
            return True
        return False

    def in_game_hint(self, ctx: GameContext) -> str:
        return "ECHO_HINT"


@pytest.fixture
async def active_echo(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(session, "broadcast", AsyncMock())
    ctx = GameContext(
        session_id="TEST01",
        game_id="echo_game_route_test",
        group_id=4242,
        host_id=1,
        players=[User(qq_id=1, nickname="P", group_id=4242)],
        started_at=datetime.utcnow(),
        config={},
        state={},
    )
    game = _EchoGame()
    runner = game_base.GameRunner(game, ctx)
    game_base._runners[ctx.session_id] = runner
    game_base._runner_by_group[ctx.group_id] = runner
    await session.register_game_session(
        ctx, on_player_action=runner._on_player_action_dispatch
    )
    yield ctx
    await session.unregister_game_session(ctx.session_id)
    game_base._runners.pop(ctx.session_id, None)
    game_base._runner_by_group.pop(ctx.group_id, None)


async def test_route_handled_message_consumed(active_echo) -> None:  # noqa: ARG001
    consumed = await session.route_incoming_message(1, 4242, "ping")
    assert consumed is True


async def test_route_unhandled_not_consumed(active_echo) -> None:  # noqa: ARG001
    consumed = await session.route_incoming_message(1, 4242, "unknown")
    assert consumed is False


async def test_in_game_hint_for_group(active_echo) -> None:  # noqa: ARG001
    assert game_base.in_game_hint_for_group(4242) == "ECHO_HINT"
    assert game_base.in_game_hint_for_group(9999) is None


# =====================================================================
# 等待位的更替：后来者优先，先到的必须**明确收场**
# =====================================================================
async def test_superseded_waiter_fails_instead_of_hanging() -> None:
    """同一 (人, 场景) 只有一个等待位，后到的会把先到的结清。

    静默覆盖的后果是"先到的那个永远等下去"，玩家看到的是某局莫名卡死。
    结清后它走的是既有的"没拿到输入"路径（`TimeoutError`），调用方无需改。
    """
    first = asyncio.create_task(session._wait_message(7, 4242, None))  # noqa: SLF001
    await asyncio.sleep(0.01)  # 让它真正登记上
    second = asyncio.create_task(session._wait_message(7, 4242, None))  # noqa: SLF001
    await asyncio.sleep(0.01)

    with pytest.raises(GameTimeoutError):
        await first

    # 后来者仍然活着，而且真的能收到消息
    assert await session.route_incoming_message(7, 4242, "回答") is True
    assert await second == "回答"


async def test_new_waiter_survives_the_old_one_settling() -> None:
    """旧等待结清时**不能**把新等待从登记表里清掉（那会把新等待也弄死）。"""
    first = asyncio.create_task(session._wait_message(8, 4242, None))  # noqa: SLF001
    await asyncio.sleep(0.01)
    second = asyncio.create_task(session._wait_message(8, 4242, None))  # noqa: SLF001
    await asyncio.sleep(0.01)

    with pytest.raises(GameTimeoutError):
        await first
    await asyncio.sleep(0.01)  # 让旧等待的 finally 跑完

    key = ("user", 8, 4242)
    assert key in session._pending_private_or_group  # noqa: SLF001
    assert await session.route_incoming_message(8, 4242, "还在") is True
    assert await second == "还在"


async def test_a_single_waiter_is_unaffected() -> None:
    """顺序等待（绝大多数情况）行为不变，且结清后登记表干净。"""
    key = ("user", 9, 4242)
    task = asyncio.create_task(session._wait_message(9, 4242, None))  # noqa: SLF001
    await asyncio.sleep(0.01)

    assert await session.route_incoming_message(9, 4242, "正常") is True
    assert await task == "正常"
    assert key not in session._pending_private_or_group  # noqa: SLF001
