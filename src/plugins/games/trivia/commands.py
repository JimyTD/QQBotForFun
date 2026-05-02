"""趣味问答游戏内指令（统一需要 @机器人）。

- @机器人 /状态    查看当前进度和本局榜

投降/结束 已合并到 game_launcher 的 /结束 命令。
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import to_me

from core import game_base, render


# -------------------- /状态（趣味问答版） --------------------
# 注意：海龟汤也有 /状态，两者通过检查 game_id 区分
_trivia_status = on_command(
    "问答状态", aliases={"trivia_status"},
    rule=to_me(), priority=3, block=True,
)


@_trivia_status.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != "trivia":
        return

    ctx = runner.ctx
    idx = int(ctx.state.get("current_index", 0))
    total = int(ctx.state.get("total", 10))
    clues_shown = int(ctx.state.get("clues_shown", 0))
    scores: dict[int, int] = {
        int(k): int(v) for k, v in ctx.state.get("scores", {}).items()
    }

    lines = [
        f"进度：第 {idx + 1} / {total} 题",
        f"当前线索：{clues_shown} / 5 条",
        "",
    ]
    if scores:
        lines.append("本局得分：")
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        medals = ["🥇", "🥈", "🥉"]
        for i, (qq, s) in enumerate(ranked[:10]):
            nick = _nickname(ctx, qq)
            medal = medals[i] if i < 3 else f" {i + 1}."
            lines.append(f"{medal} @{nick}  {s} 分")
    else:
        lines.append("（尚无人得分）")

    await matcher.finish(
        render.text_card("趣味问答 · 本局状态", lines, emoji="📊")
    )


def _nickname(ctx, qq_id: int) -> str:
    p = ctx.get_player(qq_id)
    return p.nickname if p else str(qq_id)
