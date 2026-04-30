"""全局消息入站路由。

处理优先级：
  1. 如果群里正在 [选择态]，且消息 @机器人，交给 selection 处理
  2. 否则转 `core.session.route_incoming_message`（游戏内 / ask 等待）
  3. 若被消费，阻断后续插件匹配
"""

from __future__ import annotations

from nonebot import get_bot, on_message
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)
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
    try:
        self_id = str(get_bot().self_id)
    except Exception:  # noqa: BLE001
        return False
    for seg in event.get_message():
        if isinstance(seg, MessageSegment) and seg.type == "at":
            if str(seg.data.get("qq", "")) == self_id:
                return True
    return False


def _strip_at(event: MessageEvent) -> str:
    """从消息里剥离 @段，返回纯文本。"""
    parts: list[str] = []
    for seg in event.get_message():
        if seg.type == "text":
            parts.append(str(seg.data.get("text", "")))
    return "".join(parts).strip()


@_matcher.handle()
async def _route(event: MessageEvent) -> None:
    qq_id = int(event.user_id)
    group_id: int | None = None
    if isinstance(event, GroupMessageEvent):
        group_id = int(event.group_id)
    elif isinstance(event, PrivateMessageEvent):
        group_id = None

    # 1) 选择态优先（必须群内且 @机器人）
    if group_id is not None and selection.has_pending(group_id):
        at_bot = _is_at_bot(event)
        text_no_at = _strip_at(event)
        consumed = await selection.handle_selection_message(
            group_id, qq_id, text_no_at, at_bot=at_bot
        )
        if consumed:
            _matcher.stop_propagation()
            return

    # 2) 常规路由（游戏内 / ask 等待）
    text = event.get_plaintext().strip()
    if not text:
        return
    consumed = await csession.route_incoming_message(qq_id, group_id, text)
    if consumed:
        _matcher.stop_propagation()
