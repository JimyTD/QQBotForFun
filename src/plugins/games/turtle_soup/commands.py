"""海龟汤游戏内特殊指令。

- /soup status  查看当前进度
- /soup giveup  投降，公布汤底
- /soup recap   查看已问过的关键线索
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from sqlalchemy import select

from core import game_base, render, session
from core.storage import get_session as db_session
from core.types import EndReason

from .models import SoupQuestion


_cmd = on_command("soup", priority=8, block=True)


@_cmd.handle()
async def _(
    matcher: Matcher,
    event: GroupMessageEvent,
    args: Message = CommandArg(),
) -> None:
    group_id = int(event.group_id)
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != "turtle_soup":
        await matcher.finish("本群当前没有进行中的海龟汤")
        return

    sub = args.extract_plain_text().strip().lower() or "status"
    ctx = runner.ctx

    if sub == "status":
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

    elif sub in ("giveup", "投降", "认输"):
        # 标记为非胜利结束
        await session.broadcast(
            group_id, "🏳 已投降。汤底即将揭晓。"
        )
        await runner.end(EndReason.ABORTED)

    elif sub in ("recap", "回顾"):
        # 拉取本局所有判定为 key 的提问
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

    else:
        await matcher.finish(
            "/soup status  查看进度\n"
            "/soup giveup  投降\n"
            "/soup recap   关键线索回顾"
        )
