"""AoE3 斗蛐蛐 —— 游戏内指令（统一需要 @机器人）。

- @机器人 押注1    押红方
- @机器人 押注2    押蓝方
- @机器人 开战     跳过等待直接开打

投降/结束 已合并到 game_launcher 的 /结束 命令。
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import to_me

from core import game_base, session


# -------------------- @机器人 押注1 --------------------
_bet_red = on_command(
    "押注1",
    rule=to_me(),
    priority=3,
    block=True,
)


@_bet_red.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != "aoe3_battle":
        return
    if runner.ctx.state.get("phase") != "betting":
        await matcher.finish("⚠️ 当前不在押注阶段")
        return
    # 转发给 game 的 on_player_action
    await runner.game.on_player_action(
        runner.ctx, int(event.user_id), "押注1"
    )


# -------------------- @机器人 押注2 --------------------
_bet_blue = on_command(
    "押注2",
    rule=to_me(),
    priority=3,
    block=True,
)


@_bet_blue.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != "aoe3_battle":
        return
    if runner.ctx.state.get("phase") != "betting":
        await matcher.finish("⚠️ 当前不在押注阶段")
        return
    await runner.game.on_player_action(
        runner.ctx, int(event.user_id), "押注2"
    )


# -------------------- @机器人 开战 --------------------
_start_fight = on_command(
    "开战",
    aliases={"start", "go"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_start_fight.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != "aoe3_battle":
        return
    if runner.ctx.state.get("phase") != "betting":
        await matcher.finish("⚠️ 当前不在押注阶段（可能已经开打了）")
        return
    await runner.game.on_player_action(
        runner.ctx, int(event.user_id), "开战"
    )
