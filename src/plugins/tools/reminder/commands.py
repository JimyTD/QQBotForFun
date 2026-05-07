"""工作提醒 · 指令处理器。

触发方式：
    @机器人 提醒 开
    @机器人 提醒 关
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from .storage import set_group_enabled

_cmd = on_command(
    "提醒",
    aliases={"reminder"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_cmd.handle()
async def _(matcher: Matcher, event: GroupMessageEvent, args=CommandArg()) -> None:
    arg = args.extract_plain_text().strip()
    group_id = str(event.group_id)
    operator_id = str(event.user_id)

    if arg in ("开", "on", "开启"):
        await set_group_enabled(group_id, True, operator_id)
        await matcher.finish(
            "✅ 已为本群开启工作提醒\n"
            "工作日会在各时段随机发送提醒（活动/休息/下班等）"
        )
    elif arg in ("关", "off", "关闭"):
        await set_group_enabled(group_id, False, operator_id)
        await matcher.finish("✅ 已为本群关闭工作提醒")
    else:
        await matcher.finish(
            "用法：\n"
            "  提醒 开 → 开启本群工作提醒\n"
            "  提醒 关 → 关闭本群工作提醒"
        )
