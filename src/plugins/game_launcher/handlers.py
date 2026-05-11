"""游戏大厅：快捷开局 / 结束。

快捷开局：
  @机器人 海龟汤     → 默认模式（题库随机）直接开局
  @机器人 趣味问答   → 随机类型直接开局
  @机器人 结束       → 终止当前群的游戏
"""

from __future__ import annotations

import random

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import to_me

from core import game_base
from core.errors import GameAlreadyRunningError

from nonebot import logger


async def _launch_game(
    matcher: Matcher,
    group_id: int,
    initiator_id: int,
    game_id: str,
    mode_id: str,
) -> None:
    """通用开局辅助：检查冲突 → 调 create_and_start。"""
    runner = game_base.get_runner_by_group(group_id)
    if runner is not None:
        await matcher.finish(
            f"⚠️ 本群已有进行中的「{runner.ctx.game_id}」。"
            "先 @我 结束 终止当前游戏。"
        )
        return

    try:
        await game_base.create_and_start(
            game_id,
            group_id=group_id,
            host_id=initiator_id,
            players=[],
            config={"mode": mode_id} if mode_id else {},
        )
    except GameAlreadyRunningError as e:
        await matcher.finish(f"⚠️ {e}")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[launcher] launch failed game={game_id}: {e}")
        await matcher.finish(f"⚠️ 启动失败：{e}")


# -------------------- 快捷开局：海龟汤 --------------------
_quick_soup = on_command(
    "海龟汤",
    aliases={"turtle_soup"},
    rule=to_me(),
    priority=3,
    block=True,
)

@_quick_soup.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    await _launch_game(
        matcher,
        group_id=int(event.group_id),
        initiator_id=int(event.user_id),
        game_id="turtle_soup",
        mode_id="library",  # 默认题库随机模式
    )


# -------------------- 快捷开局：趣味问答 --------------------
_quick_trivia = on_command(
    "趣味问答",
    aliases={"trivia"},
    rule=to_me(),
    priority=3,
    block=True,
)

@_quick_trivia.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    # 随机选一个类型
    trivia_types = ["country", "city", "food", "person", "animal", "idiom"]
    mode_id = random.choice(trivia_types)
    await _launch_game(
        matcher,
        group_id=int(event.group_id),
        initiator_id=int(event.user_id),
        game_id="trivia",
        mode_id=mode_id,
    )


# -------------------- /结束 --------------------
_quit = on_command(
    "结束",
    aliases={"quit", "终止", "投降", "认输", "giveup"},
    rule=to_me(),
    priority=3,
    block=True,
)

@_quit.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)

    ok = await game_base.abort_by_group(group_id)
    if ok:
        await matcher.finish("🏳 本局游戏已终止。")
    else:
        await matcher.finish("本群当前没有进行中的游戏。")
