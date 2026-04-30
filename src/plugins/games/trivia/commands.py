"""趣味问答游戏内特殊指令。

- /问答 状态    查看当前进度和本局榜
- /问答 结束    提前结束并结算已得分

（类型选择由 `/开始 trivia <type>` 处理，不在这里。）
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from core import game_base, render, session
from core.types import EndReason


_cmd = on_command("问答", aliases={"trivia"}, priority=8, block=True)


@_cmd.handle()
async def _(
    matcher: Matcher,
    event: GroupMessageEvent,
    args: Message = CommandArg(),
) -> None:
    group_id = int(event.group_id)
    sub = args.extract_plain_text().strip().lower() or "状态"

    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != "trivia":
        await matcher.finish("本群当前没有进行中的趣味问答")
        return

    ctx = runner.ctx

    if sub in ("状态", "status"):
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

    elif sub in ("结束", "退出", "quit", "exit", "end"):
        await session.broadcast(group_id, "🏳 已提前结束本局，开始结算~")
        await runner.end(EndReason.ABORTED)

    else:
        await matcher.finish(
            "/问答 状态   查看进度 / 本局榜\n"
            "/问答 结束   提前结算本局"
        )


def _nickname(ctx, qq_id: int) -> str:
    p = ctx.get_player(qq_id)
    return p.nickname if p else str(qq_id)
