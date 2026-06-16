"""AoE3 斗蛐蛐 —— 游戏内指令（统一需要 @机器人）。

- @机器人 1       押红方（普通模式） / 押1号兵夺冠（锦标赛模式）
- @机器人 2       押蓝方（普通模式） / 押2号兵夺冠（锦标赛模式）
- @机器人 开战    跳过等待直接开打

锦标赛模式下还支持无需 @ 的序号 1-8 押注。
投降/结束 已合并到 game_launcher 的 /结束 命令。
"""

from __future__ import annotations

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule, to_me

from core import game_base


async def _is_aoe3_battle(event: GroupMessageEvent) -> bool:
    runner = game_base.get_runner_by_group(int(event.group_id))
    return runner is not None and runner.ctx.game_id == "aoe3_battle"


_AOE3_BATTLE = Rule(_is_aoe3_battle)


def _get_battle_runner(group_id: int):
    """获取当前群的 aoe3_battle runner（不存在或非本游戏返回 None）。"""
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != "aoe3_battle":
        return None
    return runner


# -------------------- @机器人 1 / 押1 / 押注1 → 押红方 / 锦标赛押注 --------------------
_bet_red = on_command(
    "1",
    aliases={"押1", "押注1"},
    rule=to_me() & _AOE3_BATTLE,
    priority=3,
    block=True,
)


@_bet_red.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    runner = _get_battle_runner(int(event.group_id))
    if runner is None:
        return
    phase = runner.ctx.state.get("phase", "")
    if phase == "tournament_betting":
        # 锦标赛模式：@机器人 1 = 押 1 号兵
        await runner.game.on_player_action(
            runner.ctx, int(event.user_id), "1"
        )
        return
    if phase != "betting":
        await matcher.finish("⚠️ 当前不在押注阶段")
        return
    await runner.game.on_player_action(
        runner.ctx, int(event.user_id), "押注1"
    )


# -------------------- @机器人 2 / 押2 / 押注2 → 押蓝方 / 锦标赛押注 --------------------
_bet_blue = on_command(
    "2",
    aliases={"押2", "押注2"},
    rule=to_me() & _AOE3_BATTLE,
    priority=3,
    block=True,
)


@_bet_blue.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    runner = _get_battle_runner(int(event.group_id))
    if runner is None:
        return
    phase = runner.ctx.state.get("phase", "")
    if phase == "tournament_betting":
        await runner.game.on_player_action(
            runner.ctx, int(event.user_id), "2"
        )
        return
    if phase != "betting":
        await matcher.finish("⚠️ 当前不在押注阶段")
        return
    await runner.game.on_player_action(
        runner.ctx, int(event.user_id), "押注2"
    )


# -------------------- @机器人 开战 --------------------
_start_fight = on_command(
    "开战",
    aliases={"start", "go"},
    rule=to_me() & _AOE3_BATTLE,
    priority=3,
    block=True,
)


@_start_fight.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    runner = _get_battle_runner(int(event.group_id))
    if runner is None:
        return
    phase = runner.ctx.state.get("phase", "")
    if phase in ("betting", "tournament_betting", "tournament_waiting"):
        await runner.game.on_player_action(
            runner.ctx, int(event.user_id), "开战"
        )
        return
    await matcher.finish("⚠️ 当前不在押注/等待阶段（可能已经开打了）")


# ---- 锦标赛序号押注（无需 @，仅锦标赛押注阶段拦截 3-8）----
async def _is_tournament_betting(event: GroupMessageEvent) -> bool:
    runner = game_base.get_runner_by_group(int(event.group_id))
    if runner is None or runner.ctx.game_id != "aoe3_battle":
        return False
    return runner.ctx.state.get("phase") == "tournament_betting"


_tournament_bet = on_message(
    rule=Rule(_is_tournament_betting),
    priority=4,
    block=True,
)


@_tournament_bet.handle()
async def _on_tournament_bet_number(
    event: GroupMessageEvent, matcher: Matcher,
) -> None:
    text = event.get_plaintext().strip()
    if text not in ("1", "2", "3", "4", "5", "6", "7", "8"):
        return
    runner = _get_battle_runner(int(event.group_id))
    if runner is None:
        return
    await runner.game.on_player_action(
        runner.ctx, int(event.user_id), text
    )
    matcher.stop_propagation()
