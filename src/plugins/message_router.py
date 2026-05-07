"""全局消息入站路由。

处理优先级（priority=5，低于命令的 priority=3）：
  1. 如果群里正在 [选择态]，且消息 @机器人，交给 selection 处理
  2. 否则 @机器人 的消息转 `core.session.route_incoming_message`（游戏内提问等）
  3. 若都未消费，回复帮助信息（兜底）
"""

from __future__ import annotations

from nonebot import on_message
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from core import session as csession
from src.plugins.game_launcher import selection

_matcher = on_message(
    rule=Rule(),
    priority=5,
    block=False,
)


def _is_at_bot(event: MessageEvent) -> bool:
    """检查消息是否 @了当前机器人。"""
    if hasattr(event, "is_tome"):
        return event.is_tome()
    return False


def _strip_at(event: MessageEvent) -> str:
    """从消息里剥离 @段，返回纯文本。"""
    parts: list[str] = []
    for seg in event.get_message():
        if seg.type == "text":
            parts.append(str(seg.data.get("text", "")))
    return "".join(parts).strip()


# 兜底帮助文案（当 @机器人 但无法识别指令时回复）
_FALLBACK_HELP = (
    "🤖 我没听懂，试试以下指令吧：\n"
    "\n"
    "🎮 @我 海龟汤\n"
    "🎮 @我 趣味问答\n"
    "🍱 @我 吃什么\n"
    "🔍 @我 查资料 你的问题\n"
    "⏰ @我 提醒 开/关\n"
    "📜 @我 帮助（查看完整指令）"
)


@_matcher.handle()
async def _route(event: MessageEvent, matcher: Matcher) -> None:
    qq_id = int(event.user_id)
    group_id: int | None = None
    if isinstance(event, GroupMessageEvent):
        group_id = int(event.group_id)
    elif isinstance(event, PrivateMessageEvent):
        group_id = None

    # 必须 @机器人 才处理
    at_bot = _is_at_bot(event)
    if not at_bot:
        return

    text = _strip_at(event)

    # 只 @了机器人但没说话 → 回复帮助
    if not text:
        await matcher.finish(_FALLBACK_HELP)
        return

    # 1) 选择态优先
    if group_id is not None and selection.has_pending(group_id):
        consumed = await selection.handle_selection_message(
            group_id, qq_id, text, at_bot=True
        )
        if consumed:
            matcher.stop_propagation()
            return

    # 2) 常规路由（游戏内提问 / ask 等待）
    consumed = await csession.route_incoming_message(qq_id, group_id, text)
    if consumed:
        matcher.stop_propagation()
        return

    # 3) 兜底：@机器人 但没被任何命令或游戏消费 → 回复帮助
    await matcher.finish(_FALLBACK_HELP)
