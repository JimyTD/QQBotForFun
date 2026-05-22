"""红警2斗蛐蛐 —— 对局内指令（与帝国斗蛐蛐口令一致，仅绑定 ra2_battle）。"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import to_me

from core import game_base


def _get_runner(group_id: int):
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != "ra2_battle":
        return None
    return runner


_bet_red = on_command(
    "1",
    aliases={"押1", "押注1"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_bet_red.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    runner = _get_runner(int(event.group_id))
    if runner is None:
        return
    if runner.ctx.state.get("phase") != "betting":
        await matcher.finish("⚠️ 当前不在押注阶段")
        return
    await runner.game.on_player_action(runner.ctx, int(event.user_id), "押注1")


_bet_blue = on_command(
    "2",
    aliases={"押2", "押注2"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_bet_blue.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    runner = _get_runner(int(event.group_id))
    if runner is None:
        return
    if runner.ctx.state.get("phase") != "betting":
        await matcher.finish("⚠️ 当前不在押注阶段")
        return
    await runner.game.on_player_action(runner.ctx, int(event.user_id), "押注2")


_start_fight = on_command(
    "开战",
    aliases={"start", "go"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_start_fight.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    runner = _get_runner(int(event.group_id))
    if runner is None:
        return
    if runner.ctx.state.get("phase") != "betting":
        await matcher.finish("⚠️ 当前不在押注阶段（可能已经开打了）")
        return
    await runner.game.on_player_action(runner.ctx, int(event.user_id), "开战")
