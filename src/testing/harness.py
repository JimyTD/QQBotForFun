"""测试辅助：GameTestHarness。

用于在无真实 NoneBot/OneBot/LLM 的情况下驱动一局游戏。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

from core import game_base, session
from core.types import EndReason, GameContext, User, new_session_id


class GameTestHarness:
    """简易测试驱动器。

    用法：
        async with GameTestHarness(MyGame, players=[1001]) as h:
            await h.start()
            await h.send(1001, "hello")
            assert "xxx" in h.last_broadcast()
    """

    def __init__(
        self,
        game_cls: type[game_base.GameBase],
        *,
        players: list[int],
        group_id: int = 9999,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.game_cls = game_cls
        self.group_id = group_id
        self.players = [User(qq_id=p, nickname=f"P{p}", group_id=group_id) for p in players]
        self.config = dict(config or {})

        self.broadcasts: list[str] = []
        self.whispers: list[tuple[int, str]] = []
        self.runner: game_base.GameRunner | None = None

        self._patches: list[Any] = []

    async def __aenter__(self) -> GameTestHarness:
        async def _fake_broadcast(group_id: int, message, *, at=None) -> None:  # noqa: ARG001
            self.broadcasts.append(str(message))

        async def _fake_whisper(qq_id: int, message) -> None:
            self.whispers.append((qq_id, str(message)))

        p1 = patch.object(session, "broadcast", AsyncMock(side_effect=_fake_broadcast))
        p2 = patch.object(session, "whisper", AsyncMock(side_effect=_fake_whisper))
        for p in (p1, p2):
            p.start()
            self._patches.append(p)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        # 先确保 runner 结束（此时 patches 还有效，broadcast 等会被 mock 拦截）
        if self.runner and not self.runner._ended:
            try:
                await self.runner.end(EndReason.ABORTED)
            except Exception:
                pass
        # 最后再停掉 patches
        for p in self._patches:
            p.stop()
        self._patches.clear()

    async def start(self, *, session_timeout_seconds: float | None = None) -> None:
        ctx = GameContext(
            session_id=new_session_id(),
            game_id=self.game_cls.id,
            group_id=self.group_id,
            host_id=self.players[0].qq_id,
            players=self.players,
            started_at=datetime.utcnow(),
            config=self.config,
            state={},
        )
        game = self.game_cls()
        self.runner = game_base.GameRunner(game, ctx)
        # 登记到 game_base 的全局 registry，让游戏代码中的 get_runner 能找到
        game_base._runners[ctx.session_id] = self.runner
        game_base._runner_by_group[ctx.group_id] = self.runner
        await self.runner.start(session_timeout_seconds=session_timeout_seconds)

    async def send(self, qq_id: int, text: str) -> None:
        assert self.runner is not None
        await session.route_incoming_message(qq_id, self.group_id, text)

    def last_broadcast(self) -> str:
        return self.broadcasts[-1] if self.broadcasts else ""

    def broadcasts_contain(self, text: str) -> bool:
        return any(text in m for m in self.broadcasts)
