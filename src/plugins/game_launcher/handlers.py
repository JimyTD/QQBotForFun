"""游戏大厅：/开始 / /结束。

与 CLI 对齐：
  /开始              → 选游戏 → 选模式 → 开局
  /开始 <ID或编号>    → 跳过选游戏
  /开始 <ID> <模式>   → 直接开局
  /结束              → 清掉当前群的选择态或游戏，回主菜单状态
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from core import game_base
from src.plugins.game_launcher import selection

# -------------------- /开始 --------------------
_play = on_command(
    "开始",
    aliases={"play", "开局", "玩"},
    priority=10,
    block=True,
)


@_play.handle()
async def _(
    matcher: Matcher,
    event: GroupMessageEvent,
    args: Message = CommandArg(),
) -> None:
    raw = args.extract_plain_text().strip()
    group_id = int(event.group_id)
    initiator_id = int(event.user_id)

    # 群里已有进行中游戏？
    runner = game_base.get_runner_by_group(group_id)
    if runner is not None:
        await matcher.finish(
            f"⚠️ 本群已有进行中的「{runner.ctx.game_id}」。"
            "先使用 /结束 终止当前游戏。"
        )
        return

    # 群里已有待选择？
    if selection.has_pending(group_id):
        await matcher.finish(
            "⚠️ 本群正在进行游戏选择。@机器人 并发送编号继续，或 /结束 取消。"
        )
        return

    # 解析参数：最多 2 个 token（game 和 mode）
    tokens = raw.split(maxsplit=1)
    game_preselect = tokens[0] if tokens else None
    mode_preselect = tokens[1] if len(tokens) > 1 else None

    await selection.begin(
        group_id,
        initiator_id,
        game_preselect=game_preselect,
        mode_preselect=mode_preselect,
    )


# -------------------- /结束 --------------------
_quit = on_command("结束", aliases={"quit", "终止"}, priority=10, block=True)


@_quit.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)

    # 先清选择态
    if selection.cancel(group_id):
        await matcher.finish("🏳 已取消当前的游戏选择。")
        return

    # 再终止进行中游戏
    ok = await game_base.abort_by_group(group_id)
    if ok:
        await matcher.finish("🏳 本局游戏已终止。")
    else:
        await matcher.finish("本群当前没有进行中的游戏或选择。")
