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


# =====================================================================
# 收场：清理链出错也不许把群永久占住
# =====================================================================
async def test_end_clears_group_even_if_cleanup_fails(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """收尾步骤抛异常时，注册表必须**已经**被摘掉。

    这条锁的是一个真实缺陷：`end()` 以前把「取消定时器 / 注销会话 / 写 DB」
    串在 finally 里、`_runner_by_group.pop` 放最后，而 `_ended` 在开头就置了 True。
    于是任何一步抛异常（DB 抖动、任务被取消）都会：
      1. 跳过 pop → 这一局永久占住这个群（之后开任何游戏都提示"已有进行中"）；
      2. 且因为 `_ended` 已经是 True，`@我 结束` 走到 `end()` 直接 return，
         bot 还回一句"本局游戏已终止"，用户以为结束了，实际永远开不了新局。
    只能重启 bot 才能救。
    """
    from unittest.mock import AsyncMock

    from core import session as csession

    monkeypatch.setattr(csession, "register_game_session", AsyncMock())
    monkeypatch.setattr(csession, "unregister_game_session", AsyncMock())
    monkeypatch.setattr(csession, "broadcast", AsyncMock())

    user = User(qq_id=3001, nickname="P", group_id=7777)
    runner = await game_base.create_and_start(
        "sample_game",
        group_id=7777,
        host_id=3001,
        players=[user],
    )
    sid = runner.ctx.session_id

    async def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("db down")

    # 收尾时 DB 写失败：不允许连坐注册表清理
    monkeypatch.setattr(game_base, "_persist_session", _boom)

    await runner.end(EndReason.ABORTED)

    assert game_base.get_runner(sid) is None, "session 注册表残留 → 内存泄漏"
    assert game_base.get_runner_by_group(7777) is None, "群被永久占住"


async def test_end_is_idempotent_and_never_reruns_on_end(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """重复 `end()` 不重复播报，但必须仍然能清场。

    典型场景：玩家先 `@我 结束` 收掉一局，紧接着超时定时器/重复指令又触发一次
    `end()`；结算卡片和汤底不能二次广播。
    """
    from unittest.mock import AsyncMock

    from core import session as csession

    monkeypatch.setattr(csession, "register_game_session", AsyncMock())
    monkeypatch.setattr(csession, "unregister_game_session", AsyncMock())
    monkeypatch.setattr(csession, "broadcast", AsyncMock())

    calls: list[EndReason] = []

    user = User(qq_id=3002, nickname="P", group_id=7778)
    runner = await game_base.create_and_start(
        "sample_game",
        group_id=7778,
        host_id=3002,
        players=[user],
    )

    async def _record(ctx: GameContext, reason: EndReason) -> None:
        calls.append(reason)

    monkeypatch.setattr(runner.game, "on_end", _record)

    await runner.end(EndReason.ABORTED)
    await runner.end(EndReason.TIMEOUT)

    assert calls == [EndReason.ABORTED], "on_end 被重复调用（会重复播报结算）"
    assert game_base.get_runner_by_group(7778) is None


async def test_session_timeout_clears_registry_and_marks_ended(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """整局超时走完后：两个注册表都必须清空，DB 必须落 `ended`。

    线上真实事故：群 209358399 的海龟汤 EF8WHU，09-18 07:53 开局、09-19 07:53
    超时。之后群里的表现是"斗蛐蛐开不了（提示本群已有进行中的海龟汤）、
    `@我 提示` 却还能买到线索"，而 `game_session` 一直停在 `status='active'`。
    根因是超时回调把自己的 task 取消掉了，见 tests/core/test_scheduler.py。
    """
    import asyncio
    from unittest.mock import AsyncMock

    from core import session as csession
    from core._models_common import GameSessionRecord
    from core.storage import get_session

    monkeypatch.setattr(csession, "register_game_session", AsyncMock())
    monkeypatch.setattr(csession, "unregister_game_session", AsyncMock())
    monkeypatch.setattr(csession, "broadcast", AsyncMock())

    user = User(qq_id=3003, nickname="P", group_id=7780)
    runner = await game_base.create_and_start(
        "sample_game",
        group_id=7780,
        host_id=3003,
        players=[user],
        session_timeout_seconds=0.05,
    )
    sid = runner.ctx.session_id

    # 等超时回调整条链走完（定时器 → on_timeout → end → 落库）
    await asyncio.sleep(0.8)

    assert game_base.get_runner(sid) is None, "session 注册表残留（该局仍然占着群）"
    assert game_base.get_runner_by_group(7780) is None, "群被永久占住"

    async with get_session() as sess:
        row = await sess.get(GameSessionRecord, sid)
    assert row is not None
    assert row.status == "ended", "整局超时没落库（线上表现为那一局永远 active）"
    assert row.end_reason == EndReason.TIMEOUT.value
