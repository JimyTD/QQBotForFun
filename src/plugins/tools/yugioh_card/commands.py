"""游戏王查卡命令处理器。

触发方式：
    @机器人 查卡 <卡名>
    @机器人 查卡 #<密码>
    @机器人 ygo <卡名>
    @机器人 随机卡

行为：调用 YGOProDeck API 查询，返回文字卡片 + 卡图。
单次命令，无状态，不涉及经济/对局/排行。
"""

from __future__ import annotations

import time

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from core import render

from .api import random_card, search_by_id, search_by_name
from .render import format_card_text, format_not_found

# -------- Cooldown（per-user 5 秒）--------
_cooldowns: dict[int, float] = {}
_COOLDOWN_SECONDS = 5.0


def _check_cooldown(user_id: int) -> bool:
    """检查用户是否在冷却中。返回 True 表示可以继续。"""
    now = time.time()
    last = _cooldowns.get(user_id, 0)
    if now - last < _COOLDOWN_SECONDS:
        return False
    _cooldowns[user_id] = now
    return True


# -------- /查卡 --------
_cmd_search = on_command(
    "查卡",
    aliases={"ygo"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_cmd_search.handle()
async def _handle_search(
    matcher: Matcher, event: MessageEvent, args: Message = CommandArg()
) -> None:
    query = args.extract_plain_text().strip()
    if not query:
        await matcher.finish(
            render.text_card(
                "🃏 查卡",
                [
                    "用法：@我 查卡 卡名",
                    "",
                    "示例：",
                    "  @我 查卡 青眼白龙",
                    "  @我 查卡 #89631139",
                    "  @我 随机卡",
                ],
                emoji="🃏",
            )
        )
        return

    # cooldown
    user_id = int(event.user_id)
    if not _check_cooldown(user_id):
        await matcher.finish("🃏 查卡太频繁了，请稍等几秒再试~")
        return

    # 按密码查询
    if query.startswith("#") or query.startswith("＃"):
        passcode_str = query[1:].strip()
        try:
            passcode = int(passcode_str)
        except ValueError:
            await matcher.finish("⚠️ 密码格式不对，应为纯数字。例如：@我 查卡 #89631139")
            return

        try:
            card = await search_by_id(passcode)
        except Exception:  # noqa: BLE001
            await matcher.finish("⚠️ 查询超时或网络异常，请稍后再试。")
            return

        if card is None:
            await matcher.finish(
                render.text_card("🃏 查卡", format_not_found(query), emoji="🃏")
            )
            return

        msg = Message(
            render.text_card(f"🃏 {card.name}", format_card_text(card), emoji="🃏")
        )
        if card.image_url_small:
            msg += MessageSegment.image(card.image_url_small)
        await matcher.finish(msg)
        return

    # 按卡名模糊搜索
    try:
        cards = await search_by_name(query)
    except Exception:  # noqa: BLE001
        await matcher.finish("⚠️ 查询超时或网络异常，请稍后再试。")
        return

    if not cards:
        await matcher.finish(
            render.text_card("🃏 查卡", format_not_found(query), emoji="🃏")
        )
        return

    # 展示第一张
    card = cards[0]
    lines = format_card_text(card)
    if len(cards) > 1:
        lines.append("")
        lines.append(f"共找到 {len(cards)} 张相关卡片，已展示第 1 张。")
        lines.append("若要精确查询，请使用完整卡名或密码。")

    msg = Message(render.text_card(f"🃏 {card.name}", lines, emoji="🃏"))
    if card.image_url_small:
        msg += MessageSegment.image(card.image_url_small)
    await matcher.finish(msg)


# -------- /随机卡 --------
_cmd_random = on_command(
    "随机卡",
    aliases={"random card", "随机游戏王卡"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_cmd_random.handle()
async def _handle_random(matcher: Matcher, event: MessageEvent) -> None:
    user_id = int(event.user_id)
    if not _check_cooldown(user_id):
        await matcher.finish("🃏 查卡太频繁了，请稍等几秒再试~")
        return

    try:
        card = await random_card()
    except Exception:  # noqa: BLE001
        await matcher.finish("⚠️ 查询超时或网络异常，请稍后再试。")
        return

    if card is None:
        await matcher.finish("⚠️ 随机卡片获取失败，请稍后再试。")
        return

    msg = Message(
        render.text_card(f"🃏 {card.name}", format_card_text(card), emoji="🃏")
    )
    if card.image_url_small:
        msg += MessageSegment.image(card.image_url_small)
    await matcher.finish(msg)
