"""游戏启动流程的群维度选择状态机。

职责：
  /开始              → 进入 [选游戏] → [选模式] → 开局
  /开始 <id>         → 跳过 [选游戏]，直接 [选模式]
  /开始 <id> <mode>  → 两步都跳过，直接开局
  /结束              → 清除任何选择态或游戏

设计要点：
  - 每个群最多一个"待选择"会话（和"进行中游戏"互斥）
  - 60 秒超时自动取消，并向群里通知
  - 选择态下任何群友都可选，但必须 @机器人 + 数字/ID（避免误触发）
  - CLI 里等价机制为直接 input()，不走这里

铁律：与 scripts/play_cli.py 的交互逻辑保持 1:1 对齐。
    详见 docs/13-cli-bot-parity.md。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from nonebot import logger

from core import game_base, session, user
from core.errors import GameAlreadyRunningError
from core.game_base import GameBase, GameMode, resolve_mode


SELECTION_TIMEOUT_SECONDS = 60


# =====================================================================
# 状态定义
# =====================================================================
@dataclass
class PendingSelection:
    """群维度的待选择会话。"""

    group_id: int
    initiator_id: int                  # 谁发起的（用于日志，不限制谁能选）
    stage: str                         # "game" | "mode"
    game_cls: type[GameBase] | None = None   # stage=mode 时已选定游戏
    created_at: datetime = field(default_factory=datetime.utcnow)
    timeout_task: asyncio.Task | None = None  # 超时 task


_pending: dict[int, PendingSelection] = {}


def get_pending(group_id: int) -> PendingSelection | None:
    return _pending.get(group_id)


def has_pending(group_id: int) -> bool:
    return group_id in _pending


# =====================================================================
# 启动入口（由 /开始 handler 调用）
# =====================================================================
async def begin(
    group_id: int,
    initiator_id: int,
    *,
    game_preselect: str | None = None,
    mode_preselect: str | None = None,
) -> None:
    """按参数情况进入选择流程或直接开局。

    需要调用方先检查：
      - 群里没有进行中游戏（game_base.get_runner_by_group）
      - 群里没有待选择会话（has_pending）
    """
    # 1. 解析游戏（可跳过）
    game_cls: type[GameBase] | None = None
    if game_preselect:
        game_cls = _resolve_game(game_preselect)
        if game_cls is None:
            await session.broadcast(
                group_id,
                f"⚠️ 未找到游戏「{game_preselect}」。@我 菜单 查看可用游戏。",
            )
            return

    # 2. 解析模式（必须先有 game_cls 才能解析）
    mode: GameMode | None = None
    if game_cls is not None and mode_preselect:
        mode = resolve_mode(game_cls.MODES, mode_preselect)
        if mode is None:
            names = "、".join(f"{i+1}.{m.name}" for i, m in enumerate(game_cls.MODES))
            await session.broadcast(
                group_id,
                f"⚠️ 未找到模式「{mode_preselect}」。可选：{names}",
            )
            return

    # 3. 分流
    if game_cls is not None and mode is not None:
        # 两步都跳过，直接开局
        await _launch_game(group_id, initiator_id, game_cls, mode)
        return

    if game_cls is not None and mode is None:
        # 跳过选游戏，进入[选模式]
        await _enter_mode_stage(group_id, initiator_id, game_cls)
        return

    # 都没指定，进入[选游戏]
    await _enter_game_stage(group_id, initiator_id)


# =====================================================================
# 进入选择阶段
# =====================================================================
async def _enter_game_stage(group_id: int, initiator_id: int) -> None:
    games = game_base.list_games()
    if not games:
        await session.broadcast(group_id, "🎮 大厅暂无可用游戏")
        return

    ps = PendingSelection(
        group_id=group_id, initiator_id=initiator_id, stage="game"
    )
    _pending[group_id] = ps
    ps.timeout_task = asyncio.create_task(_timeout_watcher(group_id))

    lines = ["🎮 可用游戏（@我 发送数字或 ID 选择）", ""]
    for i, g in enumerate(games, 1):
        emoji = getattr(g, "emoji", "🎮")
        lines.append(f"  {i}. {emoji} {g.name}  [{g.id}]")
    lines.append("")
    lines.append(f"⏱ {SELECTION_TIMEOUT_SECONDS}s 内未选择将自动取消 · @我 结束 可随时退出")

    await session.broadcast(group_id, "\n".join(lines))


async def _enter_mode_stage(
    group_id: int, initiator_id: int, game_cls: type[GameBase]
) -> None:
    if not game_cls.MODES:
        # 游戏没声明模式（理论上所有游戏都应该有），直接用空 mode 启动
        await _launch_game(
            group_id, initiator_id, game_cls,
            GameMode(id="", name="默认"),
        )
        return

    ps = PendingSelection(
        group_id=group_id,
        initiator_id=initiator_id,
        stage="mode",
        game_cls=game_cls,
    )
    _pending[group_id] = ps
    ps.timeout_task = asyncio.create_task(_timeout_watcher(group_id))

    emoji = getattr(game_cls, "emoji", "🎮")
    lines = [f"🎮 {emoji} {game_cls.name} · 选择开局模式", ""]
    for i, m in enumerate(game_cls.MODES, 1):
        sub = f"  · {m.description}" if m.description else ""
        lines.append(f"  {i}. {m.name}{sub}")
    lines.append("")
    lines.append(
        "@我 发送数字或别名选择 · "
        f"⏱ {SELECTION_TIMEOUT_SECONDS}s 超时 · @我 结束 退出"
    )

    await session.broadcast(group_id, "\n".join(lines))


# =====================================================================
# 处理选择消息（由 message_router 调用）
# =====================================================================
async def handle_selection_message(
    group_id: int, qq_id: int, text: str, at_bot: bool
) -> bool:
    """如果群里处于选择态且这条消息看起来是一次选择，处理之并返回 True。

    规则：
    - 必须 @机器人（at_bot=True）
    - 消息内容应当是编号、ID 或模式别名
    """
    ps = _pending.get(group_id)
    if ps is None:
        return False

    if not at_bot:
        return False

    content = text.strip()
    if not content:
        return False

    if ps.stage == "game":
        game_cls = _resolve_game(content)
        if game_cls is None:
            await session.broadcast(
                group_id,
                f"⚠️ 未识别「{content}」，请发送正确的编号或游戏 ID。",
            )
            return True
        # 进入模式选择
        _cancel(group_id)  # 取消游戏选择态
        await _enter_mode_stage(group_id, qq_id, game_cls)
        return True

    if ps.stage == "mode":
        assert ps.game_cls is not None
        mode = resolve_mode(ps.game_cls.MODES, content)
        if mode is None:
            await session.broadcast(
                group_id,
                f"⚠️ 未识别模式「{content}」，请发送正确的编号或模式名。",
            )
            return True
        _cancel(group_id)
        await _launch_game(group_id, qq_id, ps.game_cls, mode)
        return True

    return False


# =====================================================================
# 取消与超时
# =====================================================================
def cancel(group_id: int) -> bool:
    """外部（如 /结束 命令）取消一次选择。返回是否实际取消了。"""
    return _cancel(group_id)


def _cancel(group_id: int) -> bool:
    ps = _pending.pop(group_id, None)
    if ps is None:
        return False
    if ps.timeout_task and not ps.timeout_task.done():
        ps.timeout_task.cancel()
    return True


async def _timeout_watcher(group_id: int) -> None:
    try:
        await asyncio.sleep(SELECTION_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        return
    ps = _pending.get(group_id)
    if ps is None:
        return
    _pending.pop(group_id, None)
    try:
        stage_desc = "游戏选择" if ps.stage == "game" else f"{ps.game_cls.name if ps.game_cls else ''} 模式选择"  # noqa: E501
        await session.broadcast(group_id, f"⏱ {stage_desc} 超时，已自动取消。")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[selection] timeout broadcast failed: {e}")


# =====================================================================
# 开局执行
# =====================================================================
async def _launch_game(
    group_id: int,
    initiator_id: int,
    game_cls: type[GameBase],
    mode: GameMode,
) -> None:
    # 不限制 players —— 海龟汤/趣味问答等群游戏允许所有群友参与
    # player_ids 为空时 session.route_incoming_message 会放行所有人
    players: list = []
    # default_session_timeout_seconds 是实例 @property，不能在类上 getattr
    # 传 None 让 create_and_start 内部处理
    session_timeout = None

    try:
        await game_base.create_and_start(
            game_cls.id,
            group_id=group_id,
            host_id=initiator_id,
            players=players,
            config={"mode": mode.id} if mode.id else {},
            session_timeout_seconds=session_timeout,
        )
    except GameAlreadyRunningError as e:
        await session.broadcast(group_id, f"⚠️ {e}")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[selection] launch failed game={game_cls.id}: {e}")
        await session.broadcast(group_id, f"⚠️ 启动失败：{e}")


# =====================================================================
# 工具
# =====================================================================
def _resolve_game(token: str) -> type[GameBase] | None:
    """把 '1' / 'turtle_soup' 解析成游戏类。"""
    t = token.strip().lower()
    if not t:
        return None
    games = game_base.list_games()
    # ID 完全匹配
    for g in games:
        if g.id.lower() == t:
            return g
    # 编号
    try:
        idx = int(t)
        if 1 <= idx <= len(games):
            return games[idx - 1]
    except ValueError:
        pass
    return None
