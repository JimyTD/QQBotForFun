"""Core · session

机器人与玩家的唯一 I/O 通道。

提供：
- broadcast / whisper / reply / send_forward
- ask / choose / wait_any （接收玩家输入）
- register_game_session / unregister_game_session  （会话路由）

路由机制：
    NoneBot 收到消息后，统一在 `route_incoming_message` 入口被调用。
    若该群当前有活跃游戏（通过 `register_game_session` 注册），
    且消息来自游戏玩家，则消息会被分发给：
      1. 正在等待的 future（ask/choose/wait_any）
      2. 游戏的 on_player_action（若设置 forward_to_on_action=True）
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import Awaitable, Callable
from typing import Any

from nonebot import get_bot, logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from core.errors import (
    GameError,
    PlayerQuitError,
    TimeoutError,
    WhisperFailedError,
)
from core.types import GameContext


# =====================================================================
# 活跃会话注册
# =====================================================================
@dataclasses.dataclass
class ActiveGameSession:
    session_id: str
    game_id: str
    group_id: int
    player_ids: set[int]
    on_player_action: Callable[[int, str], Awaitable[bool]] | None = None
    # 正在等待的 futures: key 为 (qq_id, group_id|None) 或 ("group", group_id)
    waiters: dict[tuple, asyncio.Future[tuple[int, str]]] = dataclasses.field(default_factory=dict)


_active_by_group: dict[int, ActiveGameSession] = {}
_active_by_sid: dict[str, ActiveGameSession] = {}


def is_in_game(group_id: int) -> str | None:
    s = _active_by_group.get(group_id)
    return s.game_id if s else None


def get_active(group_id: int) -> ActiveGameSession | None:
    return _active_by_group.get(group_id)


async def register_game_session(
    ctx: GameContext,
    on_player_action: Callable[[int, str], Awaitable[bool]] | None = None,
) -> None:
    """向 session 路由器注册活跃对局。"""
    if ctx.group_id in _active_by_group:
        existing = _active_by_group[ctx.group_id]
        if existing.session_id != ctx.session_id:
            raise GameError(
                f"group {ctx.group_id} already has active game "
                f"{existing.game_id} (session={existing.session_id})"
            )
    s = ActiveGameSession(
        session_id=ctx.session_id,
        game_id=ctx.game_id,
        group_id=ctx.group_id,
        player_ids=set(p.qq_id for p in ctx.players),
        on_player_action=on_player_action,
    )
    _active_by_group[ctx.group_id] = s
    _active_by_sid[ctx.session_id] = s
    logger.info(f"[session] registered game={ctx.game_id} sid={ctx.session_id} group={ctx.group_id}")


async def unregister_game_session(session_id: str) -> None:
    s = _active_by_sid.pop(session_id, None)
    if s is None:
        return
    _active_by_group.pop(s.group_id, None)
    # 取消所有 waiters
    for fut in list(s.waiters.values()):
        if not fut.done():
            fut.cancel()
    logger.info(f"[session] unregistered sid={session_id}")


# =====================================================================
# 发送消息
# =====================================================================
_send_semaphore = asyncio.Semaphore(1)
_last_send_ts = 0.0
_MIN_GAP = 0.5  # 秒，避免风控


async def _throttle() -> None:
    global _last_send_ts
    async with _send_semaphore:
        delta = time.monotonic() - _last_send_ts
        if delta < _MIN_GAP:
            await asyncio.sleep(_MIN_GAP - delta)
        _last_send_ts = time.monotonic()


def _coerce_message(message: str | Message) -> Message:
    if isinstance(message, Message):
        return message
    return Message(str(message))


async def broadcast(
    group_id: int,
    message: str | Message,
    *,
    at: int | list[int] | None = None,
) -> None:
    """向群发送消息（前面可选 @）。"""
    await _throttle()
    bot = get_bot()
    msg = Message()
    if at is not None:
        ats = [at] if isinstance(at, int) else list(at)
        for qq in ats:
            msg += MessageSegment.at(qq)
        msg += MessageSegment.text(" ")
    msg += _coerce_message(message)
    try:
        await bot.call_api("send_group_msg", group_id=group_id, message=msg)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        logger.error(f"[session] broadcast failed group={group_id}: {e}")
        raise


async def broadcast_rich(
    group_id: int,
    rich_message: str | Message,
    fallback_text: str,
    *,
    retries: int = 2,
) -> None:
    """发送富媒体消息，失败时重试，最终降级为纯文本。

    适用于含图片等富媒体内容的消息：NapCat 偶尔会 rich media transfer
    failed，重试通常能成功；实在不行再退回纯文本，保证消息一定能送达。
    """
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            await broadcast(group_id, rich_message)
            return
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt < retries:
                logger.debug(
                    "[session] rich broadcast attempt %d/%d failed, retrying: %s",
                    attempt, retries, e,
                )
                await asyncio.sleep(1)
    logger.warning(
        "[session] rich broadcast failed after %d attempts, falling back to text: %s",
        retries, last_exc,
    )
    await broadcast(group_id, fallback_text)


async def whisper(qq_id: int, message: str | Message) -> None:
    """私聊。"""
    await _throttle()
    bot = get_bot()
    try:
        await bot.call_api("send_private_msg", user_id=qq_id, message=_coerce_message(message))  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[session] whisper failed qq={qq_id}: {e}")
        raise WhisperFailedError(str(e)) from e


async def reply(event_ref: Any, message: str | Message) -> None:
    """引用回复（event_ref 是 NoneBot 的 MessageEvent 实例）。"""
    await _throttle()
    bot = get_bot()
    msg = Message()
    try:
        msg += MessageSegment.reply(event_ref.message_id)
    except Exception:  # noqa: BLE001
        pass
    msg += _coerce_message(message)
    try:
        if hasattr(event_ref, "group_id") and event_ref.group_id:
            await bot.call_api("send_group_msg", group_id=event_ref.group_id, message=msg)  # type: ignore[attr-defined]
        else:
            await bot.call_api("send_private_msg", user_id=event_ref.user_id, message=msg)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        logger.error(f"[session] reply failed: {e}")
        raise


async def send_forward(
    group_id: int,
    items: list[tuple[int, str, str | Message]],
    *,
    title: str | None = None,
) -> None:
    """发送合并转发消息。
    items: list of (uin, name, content)
    """
    await _throttle()
    bot = get_bot()
    nodes = []
    for uin, name, content in items:
        nodes.append(
            {
                "type": "node",
                "data": {
                    "uin": str(uin),
                    "name": name,
                    "content": str(_coerce_message(content)),
                },
            }
        )
    try:
        await bot.call_api("send_group_forward_msg", group_id=group_id, messages=nodes)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        logger.error(f"[session] send_forward failed group={group_id}: {e}")
        # 降级：拆为多条
        if title:
            await broadcast(group_id, title)
        for _uin, name, content in items:
            try:
                await broadcast(group_id, f"[{name}]\n{_coerce_message(content)}")
            except Exception:  # noqa: BLE001
                break


# =====================================================================
# 接收输入
# =====================================================================
_QUIT_TOKENS = {"/quit", "/q", "退出", "quit"}


async def ask(
    qq_id: int,
    prompt: str | None = None,
    *,
    group_id: int | None = None,
    timeout: float = 300,
    validator: Callable[[str], bool] | None = None,
    retry_prompt: str = "⚠️ 输入无效，请重试",
    max_retries: int = 3,
) -> str:
    """等待指定用户的下一条文本消息。
    - group_id 指定 → 等该群内此人的消息；否则等其私聊消息。
    - /quit → 抛 PlayerQuitError
    - 超时 → 抛 TimeoutError
    - validator 失败 → 自动重试，超出 max_retries 抛 ValueError
    """
    if prompt:
        if group_id is not None:
            await broadcast(group_id, prompt, at=qq_id)
        else:
            await whisper(qq_id, prompt)

    retries = 0
    while True:
        text = await _wait_message(qq_id, group_id, timeout)
        if text.strip().lower() in _QUIT_TOKENS:
            raise PlayerQuitError(f"player {qq_id} quit")
        if validator is None or validator(text):
            return text
        retries += 1
        if retries > max_retries:
            raise ValueError("max retries exceeded for input validation")
        if group_id is not None:
            await broadcast(group_id, retry_prompt, at=qq_id)
        else:
            await whisper(qq_id, retry_prompt)


async def choose(
    qq_id: int,
    options: list[str],
    *,
    group_id: int | None = None,
    timeout: float = 60,
    prompt: str | None = None,
) -> int:
    """从编号列表中选择。返回索引（0-based）。"""
    if not options:
        raise ValueError("options cannot be empty")
    listing = "\n".join(f"{i + 1}. {opt}" for i, opt in enumerate(options))
    full_prompt = (prompt + "\n" if prompt else "") + listing + "\n请回复编号"

    def _validate(s: str) -> bool:
        try:
            n = int(s.strip())
            return 1 <= n <= len(options)
        except ValueError:
            return False

    answer = await ask(
        qq_id,
        full_prompt,
        group_id=group_id,
        timeout=timeout,
        validator=_validate,
        retry_prompt=f"⚠️ 请回复 1~{len(options)} 的数字",
    )
    return int(answer.strip()) - 1


async def wait_any(
    group_id: int,
    *,
    from_players: list[int] | None = None,
    timeout: float = 300,
    predicate: Callable[[str, int], bool] | None = None,
) -> tuple[int, str]:
    """等待群内任一（指定）玩家发言。
    返回 (qq_id, text)。
    """
    active = _active_by_group.get(group_id)
    if active is None:
        raise GameError(f"no active game in group {group_id}")

    key = ("group_any", group_id, id(object()))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    try:
        while True:
            fut: asyncio.Future[tuple[int, str]] = loop.create_future()
            active.waiters[key] = fut
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"wait_any timeout in group {group_id}")
            try:
                qq_id, text = await asyncio.wait_for(fut, timeout=remaining)
            except asyncio.TimeoutError as e:
                raise TimeoutError(f"wait_any timeout in group {group_id}") from e
            if from_players and qq_id not in from_players:
                continue
            if predicate and not predicate(text, qq_id):
                continue
            return qq_id, text
    finally:
        active.waiters.pop(key, None)


async def _wait_message(qq_id: int, group_id: int | None, timeout: float) -> str:
    """底层：注册一个等待某个 user/group 的 future。"""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[tuple[int, str]] = loop.create_future()
    key = ("user", qq_id, group_id)

    # 注册到全局 pending（不依赖 active game；私聊场景也要支持）
    _pending_private_or_group[key] = fut
    try:
        _, text = await asyncio.wait_for(fut, timeout=timeout)
        return text
    except asyncio.TimeoutError as e:
        raise TimeoutError(f"ask timeout qq={qq_id}") from e
    finally:
        _pending_private_or_group.pop(key, None)


_pending_private_or_group: dict[tuple, asyncio.Future[tuple[int, str]]] = {}


# =====================================================================
# 消息路由入口（由 NoneBot 的全局消息处理器调用）
# =====================================================================
async def route_incoming_message(
    qq_id: int,
    group_id: int | None,
    text: str,
) -> bool:
    """将一条入站消息路由到：waiters → 游戏 on_player_action。

    Returns:
        True 如果消息被消费（游戏内 / 有 waiter），False 否则（让其他插件继续处理）。
    """
    consumed = False

    # 1. 私聊 / 指定群场景的 ask 在等待
    for key_variant in (("user", qq_id, group_id), ("user", qq_id, None)):
        fut = _pending_private_or_group.pop(key_variant, None)
        if fut and not fut.done():
            fut.set_result((qq_id, text))
            consumed = True
            break

    if group_id is None:
        return consumed

    # 2. 群内活跃游戏
    active = _active_by_group.get(group_id)
    if active is None:
        return consumed
    # 玩家校验
    if active.player_ids and qq_id not in active.player_ids:
        return consumed

    # 2a. wait_any waiters
    for key, fut in list(active.waiters.items()):
        if fut.done():
            active.waiters.pop(key, None)
            continue
        fut.set_result((qq_id, text))
        active.waiters.pop(key, None)
        consumed = True
        break

    # 2b. 游戏 on_player_action（事件驱动范式）
    if active.on_player_action is not None:
        try:
            handled = await active.on_player_action(qq_id, text)
            if handled:
                consumed = True
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[session] on_player_action error: {e}")

    return consumed
