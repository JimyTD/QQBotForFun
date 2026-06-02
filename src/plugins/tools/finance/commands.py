"""经济天气 · 指令处理器。

触发方式：
    @机器人 经济天气 开     → 开启每日播报
    @机器人 经济天气 关     → 关闭每日播报
    @机器人 经济天气        → 立即查看今日播报
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from .storage import set_group_enabled

_cmd = on_command(
    "经济天气",
    aliases={"finance", "财经"},
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
            "✅ 已开启每日经济天气播报\n"
            "工作日 15:30 自动推送（有异动时）\n"
            "也可随时发「经济天气」手动查看"
        )
    elif arg in ("关", "off", "关闭"):
        await set_group_enabled(group_id, False, operator_id)
        await matcher.finish("✅ 已关闭经济天气播报")
    elif arg == "":
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone(timedelta(hours=8)))
        hour = now.hour
        pre_market_note = ""
        if now.weekday() < 5 and hour < 15:
            pre_market_note = "\n⏰ A股尚未收盘，数据基于最近一个交易日"

        await matcher.send("⏳ 正在拉取数据，请稍候...")

        from .detector import run_detection
        from .reporter import generate_report

        try:
            anomalies, macros, top_mover = await run_detection()
            report = await generate_report(anomalies, macros, top_mover)
        except Exception as e:  # noqa: BLE001
            await matcher.finish(f"❌ 拉取数据失败: {e}")
            return  # unreachable, but makes intent clear

        if report is None:
            await matcher.finish("📊 今天市场风平浪静，没什么值得说的。" + pre_market_note)
        else:
            await matcher.finish(report + pre_market_note)
    else:
        await matcher.finish(
            "用法：\n"
            "  经济天气 开   → 开启每日播报\n"
            "  经济天气 关   → 关闭\n"
            "  经济天气      → 立即查看"
        )
