"""/签到 命令处理器。

触发方式：
    @我 签到
    @我 打卡
    @我 checkin

行为：每日一次，发放 coin + score 奖励，连续签到有阶梯加成。
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import to_me

from core import render

from .service import MILESTONE_REWARDS, do_checkin

_cmd = on_command(
    "签到",
    aliases={"打卡", "checkin"},
    rule=to_me(),
    priority=3,
    block=True,
)


def _streak_fire(streak: int) -> str:
    """连续天数的火焰 emoji。"""
    if streak >= 21:
        return "🔥🔥🔥"
    if streak >= 7:
        return "🔥🔥"
    if streak >= 3:
        return "🔥"
    return ""


@_cmd.handle()
async def _(matcher: Matcher, event: MessageEvent) -> None:
    qq_id = int(event.user_id)
    result = await do_checkin(qq_id)

    fire = _streak_fire(result.streak)
    streak_text = f"连续签到：第 {result.streak} 天 {fire}".strip()

    if result.already_done:
        # 今天已签过
        card = render.text_card(
            "今天已经签过啦～",
            [
                streak_text,
                "",
                "明天记得再来哦！",
            ],
            emoji="📅",
        )
        await matcher.finish(card)
        return

    # 签到成功
    lines = [
        streak_text,
        f"💰 金币 +{result.coin}（余额 {result.coin_balance}）",
        f"🏆 积分 +{result.score}（余额 {result.score_balance}）",
    ]

    if result.is_milestone:
        lines.append(f"🎁 连续 {result.streak} 天里程碑奖励！")

    # 预告下一个里程碑
    next_milestone = _next_milestone(result.streak)
    if next_milestone is not None:
        days_left = next_milestone - result.streak
        lines.append(f"📌 再签 {days_left} 天达成 {next_milestone} 天里程碑")

    footer = f"累计签到 {result.total_checkins} 天"

    card = render.text_card(
        "签到成功！",
        lines,
        emoji="📅",
        footer=footer,
    )
    await matcher.finish(card)


def _next_milestone(current_streak: int) -> int | None:
    """找到下一个里程碑天数。"""
    for ms in sorted(MILESTONE_REWARDS):
        if ms > current_streak:
            return ms
    return None
