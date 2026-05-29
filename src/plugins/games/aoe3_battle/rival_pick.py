"""王中王 · 选主题阶段（pending + 表情回应 + 数字兜底）。

不占 GameRunner；选定后调用 create_and_start。
选主题不设倒计时（与押注阶段一致），@结束 可取消 pending。
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from nonebot import get_bot, logger, on_message, on_notice
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, NoticeEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from core import game_base, session
from core.errors import GameAlreadyRunningError

from .rival_themes import (
    PICK_SLOT_EMOJIS,
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
    age: int | None = None
    resolved: bool = False
    picks_enabled: bool = False
    like_counts: dict[str, int] = dataclasses.field(default_factory=dict)


def resolve_pick_index_from_likes(
    *,
    emoji_to_index: dict[str, int],
    like_counts: dict[str, int],
    likes: list[object],
    picks_enabled: bool,
) -> tuple[int | None, dict[str, int]]:
    """根据 likes 相对上次 count 的增量确定选项；挂载阶段只记数不选题。"""
    updated = dict(like_counts)
    deltas: list[tuple[int, int]] = []
    for like in likes:
        if not isinstance(like, dict):
            continue
        eid = str(like.get("emoji_id", ""))
        idx = emoji_to_index.get(eid)
        if idx is None:
            continue
        count = int(like.get("count", 0))
        prev = updated.get(eid, 0)
        if picks_enabled and count > prev:
            deltas.append((count - prev, idx))
        updated[eid] = max(prev, count)
    if len(deltas) == 1:
        return deltas[0][1], updated
    if len(deltas) > 1:
        logger.warning(
            "[rival_pick] ambiguous emoji deltas=%s counts=%s likes=%s",
            deltas, updated, likes,
        )
    return None, updated


def has_pending(group_id: int) -> bool:
    p = _pending.get(group_id)
    return p is not None and not p.resolved


def get_pending(group_id: int) -> _PendingPick | None:
    p = _pending.get(group_id)
    if p is None or p.resolved:
        return None
    return p


def _clear_pending(group_id: int) -> None:
    _pending.pop(group_id, None)


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
    age: int | None = None,
) -> str | None:
    """发起选主题。成功返回 None；失败返回错误提示文本。"""
    async with _pick_lock:
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
    slots = PICK_SLOT_EMOJIS[: len(rng_options)]
    for idx, slot in enumerate(slots):
        emoji_to_index[slot.id] = idx

    pending = _PendingPick(
        group_id=group_id,
        initiator_id=initiator_id,
        message_id=message_id,
        options=rng_options,
        emoji_to_index=emoji_to_index,
        budget=budget,
        age=age,
        picks_enabled=False,
    )
    _pending[group_id] = pending

    mounted = 0
    for slot in slots:
        try:
            await bot.call_api(  # type: ignore[attr-defined]
                "set_msg_emoji_like",
                message_id=pending.message_id,
                emoji_id=slot.id,
                emoji_type=slot.emoji_type,
            )
            mounted += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[rival_pick] set_msg_emoji_like failed gid=%s msg=%s emoji=%s type=%s: %s",
                group_id, pending.message_id, slot.id, slot.emoji_type, e,
            )
    if mounted == 0:
        logger.warning(
            "[rival_pick] no emoji slots mounted gid=%s msg=%s — use reply 1/2/3",
            group_id, pending.message_id,
        )

    # 给 bot 挂载 notice 一点时间，在 picks_enabled=False 时写入 like_counts
    await asyncio.sleep(0.25)

    async with _pick_lock:
        p = _pending.get(group_id)
        if p is pending:
            p.picks_enabled = True
    return None


async def launch_rival_direct(
    *,
    group_id: int,
    initiator_id: int,
    theme_token: str,
    budget: int | None = None,
    age: int | None = None,
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
        age=age,
    )


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
        age = p.age
        _pending.pop(group_id, None)

    err = await _launch_with_theme(
        group_id=group_id,
        initiator_id=picker_id,
        theme=theme,
        budget=budget,
        age=age,
    )
    if err:
        await session.broadcast(group_id, err)


async def _launch_with_theme(
    *,
    group_id: int,
    initiator_id: int,
    theme: RivalTheme,
    budget: int | None,
    age: int | None = None,
) -> str | None:
    if game_base.get_runner_by_group(group_id) is not None:
        return "⚠️ 本群已有进行中的斗蛐蛐"
    config: dict[str, Any] = {"mode": "rival", "rival_theme_id": theme.id}
    if budget is not None:
        config["budget"] = budget
    if age is not None:
        config["age"] = age
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
    if getattr(event, "is_add", True) is False:
        return
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return
    gid = int(group_id)
    msg_id = getattr(event, "message_id", None)
    if msg_id is None:
        return

    likes = getattr(event, "likes", None) or []
    user_id = getattr(event, "user_id", None)
    self_id = getattr(event, "self_id", None)
    if self_id is None:
        self_id = getattr(bot, "self_id", None)
    from_bot = (
        user_id is not None
        and self_id is not None
        and int(user_id) == int(self_id)
    )

    chosen_idx: int | None = None
    picker_id: int | None = None
    async with _pick_lock:
        p = _pending.get(gid)
        if p is None or p.resolved:
            return
        if int(msg_id) != p.message_id:
            return
        chosen_idx, p.like_counts = resolve_pick_index_from_likes(
            emoji_to_index=p.emoji_to_index,
            like_counts=p.like_counts,
            likes=likes,
            picks_enabled=p.picks_enabled and not from_bot,
        )
        if chosen_idx is not None:
            picker_id = int(user_id) if user_id is not None else p.initiator_id

    if chosen_idx is not None and picker_id is not None:
        await _consume_choice(gid, chosen_idx, picker_id)
