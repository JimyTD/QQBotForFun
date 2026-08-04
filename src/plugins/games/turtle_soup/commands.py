"""海龟汤游戏内指令（统一需要 @机器人）。

- @机器人 /状态    查看当前进度
- @机器人 /汤面    重新查看汤面（题面）
- @机器人 /回顾    查看已问过的关键线索
- @机器人 /提示    花金币揭示一条未发现的关键线索
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

    from .game import clue_progress

    found, total = clue_progress(ctx)
    lines = [
        f"标题：《{puzzle.get('title', '未知')}》",
        f"局号：{ctx.session_id}",
        f"提问：{qcount} / {max_q}",
        f"提示：{hints_used} / {max_hints}",
    ]
    if total:
        bar = "●" * found + "○" * max(0, total - found)
        lines.append(f"线索：{bar} {found} / {total}")
    await matcher.finish(
        render.text_card(
            "本局状态",
            lines,
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

    from .game import clue_progress


    def _clip(s: str, n: int = 22) -> str:
        s = s.strip().replace("\n", " ")
        return s if len(s) <= n else s[: n - 1] + "…"

    # ---- 已确认栏 ----
    confirmed: list[str] = []
    puzzle = ctx.state.get("puzzle", {}) or {}
    all_clues: list[str] = puzzle.get("key_clues", []) or []

    # 来源 1：购买揭示的关键线索（从 ctx.state 读取；兼容旧局的渐进式字符串）
    hints_purchased: list = ctx.state.get("hints_purchased", [])
    for i, h in enumerate(hints_purchased, 1):
        if isinstance(h, int) and 0 <= h < len(all_clues):
            text = all_clues[h]
        else:
            text = str(h)
        confirmed.append(f"💡 {text}  [提示 #{i}]")

    # 来源 2 / 3：自然命中的 key（带 hint）与 yes（原始问题），从 DB 读取
    async with db_session() as sess:
        rows = (
            await sess.execute(
                select(SoupQuestion)
                .where(SoupQuestion.session_id == ctx.session_id)
                .where(SoupQuestion.verdict.in_(("key", "yes")))
                .order_by(SoupQuestion.asked_at)
            )
        ).scalars().all()

    yes_items: list[str] = []
    for r in rows:
        # 跳过购买提示的记录（已在来源 1 展示）
        if r.question.startswith("[提示 #") or r.question.startswith("[购买提示"):
            continue
        if r.verdict == "key":
            label = r.hint or _clip(r.question)
            confirmed.append(f"🔑 {label}")
        else:
            yes_items.append(f"✅ {_clip(r.question)}")

    # yes 只保留最近 8 条，避免面板过长
    if len(yes_items) > 8:
        omitted = len(yes_items) - 8
        yes_items = yes_items[-8:]
        yes_items.insert(0, f"（另有 {omitted} 条较早的确认已省略）")
    confirmed.extend(yes_items)

    # ---- 已排除栏 ----
    ruled_out_raw: list[str] = ctx.state.get("ruled_out", []) or []
    ruled_out = [f"❌ {_clip(q)}" for q in ruled_out_raw[-10:]]

    if not confirmed and not ruled_out:
        await matcher.finish("📋 暂无已确认或已排除的信息，先多问几个问题吧")

    found, total = clue_progress(ctx)
    lines: list[str] = []
    if total:
        bar = "●" * found + "○" * max(0, total - found)
        lines.append(f"关键线索进度：{bar} {found} / {total}")
        lines.append("")

    lines.append(f"【已确认】{len(confirmed)} 条")
    if confirmed:
        lines.extend(f"  {c}" for c in confirmed)
    else:
        lines.append("  （暂无）")


    if ruled_out:
        lines.append("")
        lines.append(f"【已排除】最近 {len(ruled_out)} 条")
        lines.extend(f"  {r}" for r in ruled_out)

    await matcher.finish(
        render.text_card("已知面板", lines, emoji="📋", footer=["💡 排除法也是解法"])
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
    clue_text = await game_instance.handle_hint(ctx, player_id)
    if clue_text:
        from .game import clue_progress

        hints_used = len(ctx.state.get("hints_purchased", []))
        max_hints = cfg.max_hints_per_game
        found, total = clue_progress(ctx)
        body = [
            f"💡 关键线索：{clue_text}",
            "",
            f"💰 花费 {cfg.hint_cost_coin} 金币",
        ]
        if total:
            bar = "●" * found + "○" * max(0, total - found)
            body.append(f"线索进度：{bar} {found}/{total}")
        await matcher.finish(
            render.text_card(
                "购买提示",
                body,
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
