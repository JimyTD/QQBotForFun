"""session.route_incoming_message 路由测试。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from core import game_base, session
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
