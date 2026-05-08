"""工作提醒 · 指令处理器。

触发方式：
    @机器人 提醒 开     → 100%每时段必触发（时间随机）
    @机器人 提醒 随机   → 每时段有概率触发
    @机器人 提醒 关     → 关闭
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
        await set_group_enabled(group_id, True, operator_id, mode="always")
        await matcher.finish(
            "✅ 已为本群开启工作提醒（必达模式）\n"
            "工作日每时段必定发送提醒，时间随机"
        )
    elif arg in ("随机", "random", "概率"):
        await set_group_enabled(group_id, True, operator_id, mode="random")
        await matcher.finish(
            "✅ 已为本群开启工作提醒（随机模式）\n"
            "工作日各时段随机概率触发提醒"
        )
    elif arg in ("关", "off", "关闭"):
        await set_group_enabled(group_id, False, operator_id)
        await matcher.finish("✅ 已为本群关闭工作提醒")
    else:
        await matcher.finish(
            "用法：\n"
            "  提醒 开   → 必达模式（每时段必发）\n"
            "  提醒 随机 → 随机模式（概率触发）\n"
            "  提醒 关   → 关闭提醒"
        )
