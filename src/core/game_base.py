"""Core · game_base

游戏基类与注册中心。游戏开发者继承 `GameBase` 并用 `@register_game` 注册。

提供：
- 生命周期钩子：on_create / on_start / on_player_action / on_timeout / on_end
- 运行时状态：ctx.state 自动持久化
- 崩溃恢复：重启后活跃 session 可重新加载
"""

from __future__ import annotations

import asyncio
from abc import ABC
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, TypeVar

from nonebot import logger
from sqlalchemy import select

from core import scheduler, session
from core._models_common import GameSessionRecord
from core.errors import (
    GameAlreadyRunningError,
    GameError,
    GameNotFoundError,
)
from core.storage import get_session
from core.types import EndReason, GameContext, User, new_session_id

# 延迟导入 economy 避免循环（game_base 被 core 模块顶层导入）
# 注意：economy.add 的失败不能阻塞游戏，所以 award() 里做了 try/except 防御


# =====================================================================
# 开局模式定义
# =====================================================================
@dataclass
class GameMode:
    """一种开局模式。游戏类通过 MODES 类属性声明自己支持的所有模式。

    同一份定义同时驱动：
    - QQ bot 的快捷开局（默认模式）和菜单展示
    - CLI 的两层选择（scripts/play_cli.py）
    两者 id 必须一致（由游戏自己控制）。
    """

    id: str                           # 稳定内部 ID，作为 ctx.config["mode"] 的值
    name: str                         # 玩家可见名称
    description: str = ""             # 展示在选项后的简短描述
    aliases: tuple[str, ...] = field(default_factory=tuple)


def resolve_mode(modes: list[GameMode], token: str) -> GameMode | None:
    """解析模式 token，支持编号（'1'）、id（'library'）、别名（'快速'）。"""
    t = token.strip().lower()
    if not t:
        return None
    try:
        idx = int(t)
        if 1 <= idx <= len(modes):
            return modes[idx - 1]
    except ValueError:
        pass
    for m in modes:
        if t == m.id.lower():
            return m
        for alias in m.aliases:
            if t == alias.lower():
                return m
    return None


# =====================================================================
# 游戏基类
# =====================================================================
class GameBase(ABC):
    """所有小游戏的基类。元信息字段必须在子类覆盖。"""

    # 元信息
    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    min_players: ClassVar[int] = 1
    max_players: ClassVar[int] = 10
    version: ClassVar[str] = "1.0"
    # 开局模式（必须声明至少一项）
    MODES: ClassVar[list[GameMode]] = []
    # 行为开关
    serialize_actions: ClassVar[bool] = False  # True 则 on_player_action 串行
    event_driven: ClassVar[bool] = False       # True 则 Core 会把群消息转给 on_player_action

    # ---- 生命周期钩子 ----
    async def on_create(self, ctx: GameContext) -> None:
        """开局前：出题、初始化状态等。"""

    async def on_start(self, ctx: GameContext) -> None:
        """所有玩家就位后调用。"""

    async def on_player_action(
        self, ctx: GameContext, player_id: int, message: str
    ) -> bool:
        """玩家在游戏中发言（仅 event_driven=True 时由 Core 驱动）。

        Returns:
            True 表示本游戏认领并处理了该消息；False 则交给 router 提示或命令。
        """
        return False

    def in_game_hint(self, ctx: GameContext) -> str:
        """@机器人 但本局未能识别输入时的情境提示。"""
        return f"🎮 {self.name}进行中\n💡 @我 结束 可终止本局"

    async def on_timeout(self, ctx: GameContext) -> None:
        """整局超时。"""

    async def on_end(self, ctx: GameContext, reason: EndReason) -> None:
        """结束清理。"""

    # ---- 状态序列化（默认依赖 ctx.state 是 JSON 可序列化）----
    def dump_state(self, ctx: GameContext) -> dict[str, Any]:
        return dict(ctx.state)

    def load_state(self, ctx: GameContext, data: dict[str, Any]) -> None:
        ctx.state.clear()
        ctx.state.update(data)

    # ---- 经济奖励（统一接口）----
    @staticmethod
    async def award(
        qq_id: int,
        amount: int,
        *,
        reason: str,
        currency: str = "coin",
    ) -> None:
        """为玩家发放奖励。

        ─── 产品约束（核心设计哲学，详见 docs/09-conventions.md §0.5）───
        **永不负反馈**：此方法只用于正向奖励。没有对应的 `penalize()`。
        扣款类操作需要 `core.economy.deduct` 直接调用，但原则上游戏内不应该有。

        ─── API 行为约定（实现选择，非哲学条款）───
        - `amount <= 0` 静默跳过（方便调用方，不用每次判断 `if x > 0`）
        - `economy.add` 失败只记 warn 日志、不向外抛（经济异常不应阻塞游戏主线）
        - 所有游戏都应通过此方法发奖，而不是直接调 `economy.add`

        参数：
            qq_id:    玩家 QQ 号
            amount:   奖励数量。<=0 时会直接忽略
            reason:   流水记录原因，推荐格式：``"<game_id>_<event>:<session_id>"``
            currency: 货币类型。常用：``"coin"`` 钱包 / ``"score"`` 排行榜积分

        示例::

            # 参与奖
            await self.award(player_id, 2,
                             reason=f"turtle_soup_key:{ctx.session_id}",
                             currency="score")

            # 赢家奖（双轨：coin 进钱包，score 进排行榜）
            await self.award(winner_id, 100,
                             reason=f"turtle_soup_win:{ctx.session_id}",
                             currency="coin")
            await self.award(winner_id, 20,
                             reason=f"turtle_soup_win:{ctx.session_id}",
                             currency="score")
        """
        if amount <= 0:
            return
        # 延迟导入避免循环（economy 本身不依赖 game_base，但 core 顶层是 economy 先加载）
        from core import economy

        try:
            await economy.add(qq_id, amount, reason=reason, currency=currency)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"[game] award failed: qq={qq_id} amount={amount} "
                f"currency={currency} reason={reason} err={e}"
            )


T = TypeVar("T", bound=type[GameBase])


# =====================================================================
# 注册中心
# =====================================================================
_registry: dict[str, type[GameBase]] = {}


def register_game(cls: T) -> T:
    """游戏类装饰器：注册到大厅。"""
    if not issubclass(cls, GameBase):
        raise TypeError(f"{cls} is not a GameBase subclass")
    gid = cls.id
    if not gid:
        raise ValueError(f"{cls.__name__}.id must be set")
    if gid in _registry:
        # 容忍因双路径导入(src.plugins.* vs plugins.*)导致的同一类被注册两次
        if _registry[gid].__name__ == cls.__name__:
            return cls  # type: ignore[return-value]
        raise ValueError(f"game id '{gid}' already registered by {_registry[gid]}")
    _registry[gid] = cls
    logger.info(f"[game] registered '{gid}' -> {cls.__name__} v{cls.version}")
    return cls


def get_game_class(game_id: str) -> type[GameBase]:
    if game_id not in _registry:
        raise GameNotFoundError(f"game not registered: {game_id}")
    return _registry[game_id]


def list_games() -> list[type[GameBase]]:
    return list(_registry.values())


# =====================================================================
# 运行中对局管理
# =====================================================================
class GameRunner:
    """单次对局的运行器，持有 Game 实例与上下文。"""

    def __init__(self, game: GameBase, ctx: GameContext) -> None:
        self.game = game
        self.ctx = ctx
        self._action_lock = asyncio.Lock() if game.serialize_actions else None
        self._ended = False
        self._idle_task: asyncio.Task[Any] | None = None
        self._session_task: asyncio.Task[Any] | None = None

    async def _on_player_action_dispatch(self, qq_id: int, message: str) -> bool:
        if self._action_lock is not None:
            async with self._action_lock:
                handled = await self.game.on_player_action(self.ctx, qq_id, message)
        else:
            handled = await self.game.on_player_action(self.ctx, qq_id, message)
        if handled:
            # 每次玩家有动作，都算一次活跃；idle 计时器由外层重置
            _idle_activity[self.ctx.session_id] = datetime.utcnow()
        return handled

    async def start(self, *, session_timeout_seconds: float | None = None) -> None:
        ctx = self.ctx
        game = self.game

        # 1. 注册到 session 路由器
        await session.register_game_session(
            ctx,
            on_player_action=self._on_player_action_dispatch if game.event_driven else None,
        )

        # 2. 持久化初始记录
        await _persist_session(ctx, status="active")

        # 3. 整局超时
        if session_timeout_seconds and session_timeout_seconds > 0:
            await scheduler.start_turn_timer(
                ctx.session_id, session_timeout_seconds, self._on_session_timeout
            )

        # 4. 触发游戏钩子
        try:
            await game.on_create(ctx)
            await _persist_session_state(ctx)
            await game.on_start(ctx)
            await _persist_session_state(ctx)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[game] start error sid={ctx.session_id}: {e}")
            await self.end(EndReason.ERROR)
            raise

    async def _on_session_timeout(self) -> None:
        if self._ended:
            return
        try:
            await self.game.on_timeout(self.ctx)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[game] on_timeout error sid={self.ctx.session_id}: {e}")
        await self.end(EndReason.TIMEOUT)

    async def end(self, reason: EndReason) -> None:
        if self._ended:
            return
        self._ended = True
        ctx = self.ctx
        try:
            await self.game.on_end(ctx, reason)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[game] on_end error sid={ctx.session_id}: {e}")
        finally:
            await scheduler.cancel_session_timers(ctx.session_id)
            await session.unregister_game_session(ctx.session_id)
            await _persist_session(ctx, status="ended", reason=reason)
            _runners.pop(ctx.session_id, None)
            _runner_by_group.pop(ctx.group_id, None)

    async def persist(self) -> None:
        """游戏在关键节点手动调用以保存状态。"""
        self.ctx.state.update(self.game.dump_state(self.ctx))
        await _persist_session_state(self.ctx)


_runners: dict[str, GameRunner] = {}
_runner_by_group: dict[int, GameRunner] = {}
_idle_activity: dict[str, datetime] = {}


def get_runner(session_id: str) -> GameRunner | None:
    return _runners.get(session_id)


def get_runner_by_group(group_id: int) -> GameRunner | None:
    return _runner_by_group.get(group_id)


def in_game_hint_for_group(group_id: int) -> str | None:
    """活跃对局的情境提示；无对局时返回 None。"""
    runner = _runner_by_group.get(group_id)
    if runner is None:
        return None
    return runner.game.in_game_hint(runner.ctx)


async def create_and_start(
    game_id: str,
    *,
    group_id: int,
    host_id: int,
    players: list[User],
    config: dict[str, Any] | None = None,
    session_timeout_seconds: float | None = None,
) -> GameRunner:
    """启动一局新游戏。"""
    if group_id in _runner_by_group:
        existing = _runner_by_group[group_id]
        raise GameAlreadyRunningError(
            f"group {group_id} already has active game '{existing.ctx.game_id}'"
        )
    cls = get_game_class(game_id)
    game = cls()
    ctx = GameContext(
        session_id=new_session_id(),
        game_id=game_id,
        group_id=group_id,
        host_id=host_id,
        players=players,
        started_at=datetime.utcnow(),
        config=dict(config or {}),
        state={},
    )
    runner = GameRunner(game, ctx)
    _runners[ctx.session_id] = runner
    _runner_by_group[group_id] = runner
    try:
        await runner.start(session_timeout_seconds=session_timeout_seconds)
    except Exception:
        _runners.pop(ctx.session_id, None)
        _runner_by_group.pop(group_id, None)
        raise
    return runner


async def abort_by_group(group_id: int) -> bool:
    r = _runner_by_group.get(group_id)
    if r is None:
        return False
    await r.end(EndReason.ABORTED)
    return True


# =====================================================================
# 崩溃恢复
# =====================================================================
async def recover_active_sessions(
    on_recovered: Callable[[GameRunner], Awaitable[None]] | None = None,
) -> int:
    """重启时加载数据库里 status='active' 的对局。

    当前实现：保守地将它们标记为 aborted（重启导致运行态丢失，无法无缝续跑）。
    如果游戏想真正续跑，应实现 load_state 并在此处新建 runner。
    """
    recovered = 0
    async with get_session() as sess:
        stmt = select(GameSessionRecord).where(GameSessionRecord.status == "active")
        rows = (await sess.execute(stmt)).scalars().all()
        for row in rows:
            row.status = "ended"
            row.end_reason = EndReason.ABORTED.value
            row.ended_at = datetime.utcnow()
            recovered += 1
            logger.warning(
                f"[game] recovered session {row.session_id} game={row.game_id}: marked as aborted"
            )
    _ = on_recovered  # 未来扩展用
    return recovered


# =====================================================================
# 持久化工具
# =====================================================================
async def _persist_session(
    ctx: GameContext, *, status: str, reason: EndReason | None = None
) -> None:
    async with get_session() as sess:
        row = await sess.get(GameSessionRecord, ctx.session_id)
        if row is None:
            sess.add(
                GameSessionRecord(
                    session_id=ctx.session_id,
                    game_id=ctx.game_id,
                    group_id=ctx.group_id,
                    host_id=ctx.host_id,
                    players=[p.qq_id for p in ctx.players],
                    state=dict(ctx.state),
                    status=status,
                    end_reason=reason.value if reason else None,
                    started_at=ctx.started_at,
                    ended_at=datetime.utcnow() if status == "ended" else None,
                )
            )
        else:
            row.status = status
            if reason:
                row.end_reason = reason.value
            if status == "ended":
                row.ended_at = datetime.utcnow()
            row.state = dict(ctx.state)


async def _persist_session_state(ctx: GameContext) -> None:
    async with get_session() as sess:
        row = await sess.get(GameSessionRecord, ctx.session_id)
        if row is not None:
            row.state = dict(ctx.state)


# 错误未使用的导入消除
_ = GameError
