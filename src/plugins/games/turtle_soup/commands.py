"""海龟汤游戏内指令（统一需要 @机器人）。

- @机器人 /状态    查看当前进度
- @机器人 /汤面    重新查看汤面（题面）
- @机器人 /回顾    查看已问过的关键线索
- @机器人 /提示    花金币购买一条方向性提示
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

from .config import get_config
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
    hints_used = len(ctx.state.get("hints_purchased", []))
    max_hints = get_config().max_hints_per_game
    await matcher.finish(
        render.text_card(
            "本局状态",
            [
                f"标题：《{puzzle.get('title', '未知')}》",
                f"局号：{ctx.session_id}",
                f"提问：{qcount} / {max_q}",
                f"提示：{hints_used} / {max_hints}",
            ],
            emoji="📊",
        )
    )


# -------------------- /汤面 --------------------
_surface = on_command("汤面", aliases={"surface", "题面"}, rule=to_me(), priority=3, block=True)


@_surface.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != "turtle_soup":
        return

    ctx = runner.ctx
    puzzle = ctx.state.get("puzzle", {})
    title = puzzle.get("title", "未知")
    surface = puzzle.get("surface", "（无汤面数据）")
    await matcher.finish(
        render.text_card(
            f"🐢 《{title}》",
            [surface],
            emoji="🐢",
            footer=["💡 提问以 ? 结尾；宣告以「汤底:」开头"],
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
    puzzle = ctx.state.get("puzzle", {})

    # 收集已发现的关键事实
    facts: list[str] = []

    # 来源 1：购买的渐进式提示（从 ctx.state 读取）
    hints_purchased: list[str] = ctx.state.get("hints_purchased", [])
    for i, h in enumerate(hints_purchased, 1):
        facts.append(f"{h}  [提示 #{i}]")

    # 来源 2：自然命中的 key（从 DB 读取，排除购买的提示）
    async with db_session() as sess:
        rows = (
            await sess.execute(
                select(SoupQuestion)
                .where(SoupQuestion.session_id == ctx.session_id)
                .where(SoupQuestion.verdict == "key")
                .order_by(SoupQuestion.asked_at)
            )
        ).scalars().all()

    for r in rows:
        # 跳过购买提示的记录
        if r.question.startswith("[提示 #"):
            continue
        # 自然命中的 key：显示 LLM 判官的引导 hint
        label = f"{r.hint}  [提问发现]" if r.hint else "（关键线索命中）"
        facts.append(label)

    if not facts:
        await matcher.finish("📋 暂无已确认的关键事实")

    total_clues = len(puzzle.get("key_clues", []))
    header = f"📖 已发现 {len(facts)} 个关键事实"
    if total_clues:
        header += f"（共 {total_clues} 条关键线索）"

    await matcher.finish(
        render.list_card(header, facts, emoji="📋")
    )


# -------------------- /提示 --------------------
_hint = on_command("提示", aliases={"hint"}, rule=to_me(), priority=3, block=True)


@_hint.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != "turtle_soup":
        await matcher.finish("⚠️ 当前没有海龟汤在进行，无法购买提示。")
        return

    ctx = runner.ctx
    player_id = int(event.user_id)
    cfg = get_config()

    # 调用 game 层的 handle_hint
    from .game import TurtleSoupGame

    game_instance = TurtleSoupGame()
    hint_text = await game_instance.handle_hint(ctx, player_id)
    if hint_text:
        hints_used = len(ctx.state.get("hints_purchased", []))
        max_hints = cfg.max_hints_per_game
        tier_label = f"第 {hints_used} 次"
        await matcher.finish(
            render.text_card(
                f"购买提示 · {tier_label}",
                [
                    f"💡 {hint_text}",
                    "",
                    f"💰 花费 {cfg.hint_cost_coin} 金币",
                ],
                emoji="🔮",
                footer=[f"已用 {hints_used}/{max_hints} 次提示机会"],
            )
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
