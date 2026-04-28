"""全局消息入站路由。

注册一个 rule=True 的低优先级 matcher，将每条群/私聊消息转给 `core.session.route_incoming_message`。
若消息被游戏/等待者消费，则阻断后续插件继续处理。
"""

from __future__ import annotations

from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, PrivateMessageEvent
from nonebot.rule import Rule

from core import session as csession

_matcher = on_message(
    rule=Rule(),
    priority=5,
    block=False,
)


@_matcher.handle()
async def _route(event: MessageEvent) -> None:
    text = event.get_plaintext().strip()
    if not text:
        return
    qq_id = int(event.user_id)
    group_id: int | None = None
    if isinstance(event, GroupMessageEvent):
        group_id = int(event.group_id)
    elif isinstance(event, PrivateMessageEvent):
        group_id = None

    consumed = await csession.route_incoming_message(qq_id, group_id, text)
    if consumed:
        # 阻断后续插件继续匹配
        _matcher.stop_propagation()
