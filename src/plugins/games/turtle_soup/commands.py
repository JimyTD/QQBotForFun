"""海龟汤游戏内指令（统一需要 @机器人）。

- @机器人 /状态    查看当前进度
- @机器人 /回顾    查看已问过的关键线索
- @机器人 /烂题    烂题淘汰（本局结束后短窗口内可用）

投降/结束 已合并到 game_launcher 的 /结束 命令。
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import to_me
from sqlalchemy import select

from core import game_base, render
from core.storage import get_session as db_session

from .models import SoupQuestion
from .puzzle_service import mark_bad_by_group


# -------------------- /状态 --------------------
_status = on_command("状态", aliases={"status"}, rule=to_me(), priority=3, block=True)


@_status.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != "turtle_soup":
        # 不是海龟汤，不处理（让其他插件/趣味问答的 /状态 接手）
        return

    ctx = runner.ctx
    puzzle = ctx.state.get("puzzle", {})
    qcount = int(ctx.state.get("question_count", 0))
    max_q = int(ctx.state.get("max_questions", 50))
    await matcher.finish(
        render.text_card(
            "本局状态",
            [
                f"标题：《{puzzle.get('title', '未知')}》",
                f"局号：{ctx.session_id}",
                f"提问：{qcount} / {max_q}",
            ],
            emoji="📊",
        )
    )


# -------------------- /回顾 --------------------
_recap = on_command("回顾", aliases={"recap"}, rule=to_me(), priority=3, block=True)


@_recap.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != "turtle_soup":
        return

    ctx = runner.ctx
    async with db_session() as sess:
        rows = (
            await sess.execute(
                select(SoupQuestion)
                .where(SoupQuestion.session_id == ctx.session_id)
                .order_by(SoupQuestion.asked_at)
            )
        ).scalars().all()
    key_lines = [
        f"💡 {r.question} → {r.hint or '（提示已过）'}"
        for r in rows
        if r.verdict == "key"
    ]
    if not key_lines:
        await matcher.finish("📜 暂无关键线索被发掘")
    else:
        await matcher.finish(
            render.list_card("关键线索回顾", key_lines, emoji="📜")
        )


# -------------------- /烂题 --------------------
_bad = on_command("烂题", aliases={"bad", "差评"}, rule=to_me(), priority=3, block=True)


@_bad.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)

    # 正在玩时拒绝
    runner = game_base.get_runner_by_group(group_id)
    if runner is not None and runner.ctx.game_id == "turtle_soup":
        await matcher.finish("⚠️ 对局进行中，请先结束本局再评价。")
        return

    ok, msg = await mark_bad_by_group(group_id)
    icon = "🗑" if ok else "ℹ️"
    await matcher.finish(f"{icon} {msg}")
