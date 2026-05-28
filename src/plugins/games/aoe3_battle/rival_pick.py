"""王中王 · 选主题阶段（pending + 表情回应 + 数字兜底）。

不占 GameRunner；选定后调用 create_and_start。
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from typing import Any

from nonebot import get_bot, logger, on_message, on_notice
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, NoticeEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from core import game_base, session
from core.errors import GameAlreadyRunningError

from .rival_themes import (
    PICK_SLOT_EMOJI_IDS,
    PICK_TIMEOUT_SECONDS,
    RivalTheme,
    format_pick_message,
    pick_random_themes,
    resolve_theme,
)

# group_id -> pending
_pending: dict[int, _PendingPick] = {}
_pick_lock = asyncio.Lock()


@dataclasses.dataclass
class _PendingPick:
    group_id: int
    initiator_id: int
    message_id: int
    options: list[RivalTheme]
    emoji_to_index: dict[str, int]
    budget: int | None
    expires_at: float
    resolved: bool = False
    timeout_task: asyncio.Task[Any] | None = None


def has_pending(group_id: int) -> bool:
    p = _pending.get(group_id)
    return p is not None and not p.resolved


def get_pending(group_id: int) -> _PendingPick | None:
    p = _pending.get(group_id)
    if p is None or p.resolved:
        return None
    return p


def _clear_pending(group_id: int) -> None:
    p = _pending.pop(group_id, None)
    if p and p.timeout_task and not p.timeout_task.done():
        p.timeout_task.cancel()


def cancel_pending(group_id: int) -> bool:
    """取消选主题（如群友 @结束）。返回是否曾有 pending。"""
    p = _pending.get(group_id)
    if p is None or p.resolved:
        return False
    p.resolved = True
    _clear_pending(group_id)
    return True


async def start_theme_pick(
    *,
    group_id: int,
    initiator_id: int,
    budget: int | None = None,
) -> str | None:
    """发起选主题。成功返回 None；失败返回错误提示文本。"""
    if game_base.get_runner_by_group(group_id) is not None:
        return "⚠️ 本群已有进行中的斗蛐蛐，先 @我 结束 再开王中王"
    if has_pending(group_id):
        return "⚠️ 本群已在选王中王主题，请点选单消息上的表情或回复 1/2/3"

    rng_options = pick_random_themes(count=3)
    text = format_pick_message(rng_options)

    bot = get_bot()
    resp = await bot.call_api(  # type: ignore[attr-defined]
        "send_group_msg",
        group_id=group_id,
        message=text,
    )
    message_id = int(resp["message_id"])

    emoji_to_index: dict[str, int] = {}
    for idx, emoji_id in enumerate(PICK_SLOT_EMOJI_IDS[: len(rng_options)]):
        emoji_to_index[emoji_id] = idx
        try:
            await bot.call_api(  # type: ignore[attr-defined]
                "set_msg_emoji_like",
                message_id=message_id,
                emoji_id=emoji_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[rival_pick] set_msg_emoji_like failed gid=%s msg=%s emoji=%s: %s",
                group_id, message_id, emoji_id, e,
            )

    pending = _PendingPick(
        group_id=group_id,
        initiator_id=initiator_id,
        message_id=message_id,
        options=rng_options,
        emoji_to_index=emoji_to_index,
        budget=budget,
        expires_at=time.monotonic() + PICK_TIMEOUT_SECONDS,
    )
    pending.timeout_task = asyncio.create_task(_timeout_worker(group_id))
    _pending[group_id] = pending
    return None


async def launch_rival_direct(
    *,
    group_id: int,
    initiator_id: int,
    theme_token: str,
    budget: int | None = None,
) -> str | None:
    """指定主题直接开局。失败返回错误文本。"""
    theme = resolve_theme(theme_token)
    if theme is None:
        return f"⚠️ 未识别的王中王主题「{theme_token}」"
    return await _launch_with_theme(
        group_id=group_id,
        initiator_id=initiator_id,
        theme=theme,
        budget=budget,
    )


async def _timeout_worker(group_id: int) -> None:
    try:
        await asyncio.sleep(PICK_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        return
    async with _pick_lock:
        p = _pending.get(group_id)
        if p is None or p.resolved:
            return
        p.resolved = True
        _pending.pop(group_id, None)
    try:
        await session.broadcast(group_id, "⏱ 王中王选主题超时，请重新 @我 斗蛐蛐 王中王")
    except Exception as e:  # noqa: BLE001
        logger.warning("[rival_pick] timeout broadcast failed gid=%s: %s", group_id, e)


async def _consume_choice(group_id: int, index: int, picker_id: int) -> None:
    """锁定某一选项并开局（index 0-based）。"""
    async with _pick_lock:
        p = _pending.get(group_id)
        if p is None or p.resolved:
            return
        if index < 0 or index >= len(p.options):
            return
        p.resolved = True
        theme = p.options[index]
        budget = p.budget
        if p.timeout_task and not p.timeout_task.done():
            p.timeout_task.cancel()
        _pending.pop(group_id, None)

    err = await _launch_with_theme(
        group_id=group_id,
        initiator_id=picker_id,
        theme=theme,
        budget=budget,
    )
    if err:
        await session.broadcast(group_id, err)


async def _launch_with_theme(
    *,
    group_id: int,
    initiator_id: int,
    theme: RivalTheme,
    budget: int | None,
) -> str | None:
    if game_base.get_runner_by_group(group_id) is not None:
        return "⚠️ 本群已有进行中的斗蛐蛐"
    config: dict[str, Any] = {"mode": "rival", "rival_theme_id": theme.id}
    if budget is not None:
        config["budget"] = budget
    try:
        await game_base.create_and_start(
            "aoe3_battle",
            group_id=group_id,
            host_id=initiator_id,
            players=[],
            config=config,
        )
    except GameAlreadyRunningError as e:
        return f"⚠️ {e}"
    except Exception as e:  # noqa: BLE001
        logger.exception("[rival_pick] launch failed gid=%s theme=%s: %s", group_id, theme.id, e)
        return f"⚠️ 启动失败：{e}"
    return None


# ---- 数字兜底（无需 @）----
async def _rule_pending_group(event: GroupMessageEvent) -> bool:
    return has_pending(int(event.group_id))


_pick_num = on_message(
    rule=Rule(_rule_pending_group),
    priority=4,
    block=True,
)


@_pick_num.handle()
async def _on_pick_number(event: GroupMessageEvent, matcher: Matcher) -> None:
    text = event.get_plaintext().strip()
    if text not in ("1", "2", "3"):
        return
    index = int(text) - 1
    gid = int(event.group_id)
    p = get_pending(gid)
    if p is None:
        return
    if index >= len(p.options):
        await matcher.finish(f"⚠️ 本局只有 {len(p.options)} 个选项")
        return
    await _consume_choice(gid, index, int(event.user_id))
    matcher.stop_propagation()


# ---- NapCat 表情回应 ----
_emoji_notice = on_notice(priority=5, block=False)


@_emoji_notice.handle()
async def _on_emoji_notice(bot: Bot, event: NoticeEvent) -> None:
    if getattr(event, "notice_type", None) != "group_msg_emoji_like":
        return
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return
    gid = int(group_id)
    p = get_pending(gid)
    if p is None:
        return
    msg_id = getattr(event, "message_id", None)
    if msg_id is None or int(msg_id) != p.message_id:
        return

    likes = getattr(event, "likes", None) or []
    user_id = getattr(event, "user_id", None)
    picker = int(user_id) if user_id is not None else p.initiator_id

    for like in likes:
        if isinstance(like, dict):
            emoji_id = str(like.get("emoji_id", ""))
        else:
            continue
        idx = p.emoji_to_index.get(emoji_id)
        if idx is not None:
            await _consume_choice(gid, idx, picker)
            break
