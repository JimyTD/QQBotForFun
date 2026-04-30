"""海龟汤游戏内特殊指令。

- /soup status  查看当前进度
- /soup giveup  投降，公布汤底
- /soup recap   查看已问过的关键线索
- /soup bad     烂题淘汰（本局结束后短窗口内可用，硬删 llm_generated 题目）
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
from .puzzle_service import mark_bad_by_group


_cmd = on_command("汤", aliases={"soup"}, priority=8, block=True)


# "烂题" 指令可在无进行中对局时使用（窗口期淘汰上局）
_BAD_KEYWORDS = ("烂题", "差评", "bad", "删除", "kick")


@_cmd.handle()
async def _(
    matcher: Matcher,
    event: GroupMessageEvent,
    args: Message = CommandArg(),
) -> None:
    group_id = int(event.group_id)
    sub = args.extract_plain_text().strip().lower() or "状态"

    # --- 特殊：烂题指令不要求必须有进行中的对局 ---
    if sub in _BAD_KEYWORDS:
        # 正在玩时拒绝，避免误触中断对局
        runner = game_base.get_runner_by_group(group_id)
        if runner is not None and runner.ctx.game_id == "turtle_soup":
            await matcher.finish("⚠️ 对局进行中，请先结束本局再评价。")
            return
        ok, msg = await mark_bad_by_group(group_id)
        icon = "🗑" if ok else "ℹ️"
        await matcher.finish(f"{icon} {msg}")
        return

    # --- 其余所有指令：必须有进行中的对局 ---
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != "turtle_soup":
        await matcher.finish("本群当前没有进行中的海龟汤")
        return

    ctx = runner.ctx

    if sub in ("状态", "status"):
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

    elif sub in ("投降", "认输", "giveup"):
        # 标记为非胜利结束
        await session.broadcast(
            group_id, "🏳 已投降。汤底即将揭晓。"
        )
        await runner.end(EndReason.ABORTED)

    elif sub in ("回顾", "recap"):
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
            "/汤 状态    查看进度\n"
            "/汤 投降    投降\n"
            "/汤 回顾    关键线索回顾\n"
            "/汤 烂题    （本局结束后）淘汰上一题"
        )
