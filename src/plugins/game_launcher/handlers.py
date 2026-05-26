"""游戏大厅：快捷开局 / 结束。

快捷开局：
  @机器人 海龟汤     → 默认模式（题库随机）直接开局
  @机器人 趣味问答   → 随机类型直接开局
  @机器人 结束       → 终止当前群的游戏
"""

from __future__ import annotations

import random

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
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
    extra_config: dict | None = None,
) -> None:
    """通用开局辅助：检查冲突 → 调 create_and_start。"""
    runner = game_base.get_runner_by_group(group_id)
    if runner is not None:
        await matcher.finish(
            f"⚠️ 本群已有进行中的「{runner.ctx.game_id}」。"
            "先 @我 结束 终止当前游戏。"
        )
        return

    config = {"mode": mode_id} if mode_id else {}
    if extra_config:
        config.update(extra_config)

    try:
        await game_base.create_and_start(
            game_id,
            group_id=group_id,
            host_id=initiator_id,
            players=[],
            config=config,
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


# -------------------- 快捷开局：斗蛐蛐 --------------------
_quick_battle = on_command(
    "斗蛐蛐",
    aliases={"aoe3_battle"},
    rule=to_me(),
    priority=3,
    block=True,
)

@_quick_battle.handle()
async def _(matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()) -> None:
    # 获取指令后的参数文本
    arg_text = args.extract_plain_text().strip()

    # ---- 播报模式切换（不开局，与红警斗蛐蛐共用）----
    if arg_text in ("详细", "detailed"):
        from core.group_config import set_group_config
        await set_group_config(int(event.group_id), "aoe3_battle.broadcast_mode", "detailed")
        await matcher.finish("✅ 已切换为【详细播报】模式（战斗过程会分段播报，帝国/红警通用）")
    if arg_text in ("极简", "简洁", "brief"):
        from core.group_config import set_group_config
        await set_group_config(int(event.group_id), "aoe3_battle.broadcast_mode", "brief")
        await matcher.finish("✅ 已切换为【极简播报】模式（只显示开战和战报，帝国/红警通用）")

    # ---- 自选模式："斗蛐蛐 自选 火枪手 散兵 15000" ----
    parts = arg_text.split()
    if parts and parts[0] == "自选":
        await _handle_custom_battle(matcher, event, " ".join(parts[1:]))
        return

    mode_id = "bet"  # 默认押注模式
    budget = None     # None = 使用默认值

    # 解析参数：可以是模式（单挑/黑名单乱斗）或资源数字
    for part in parts:
        if part in ("单挑", "1v1", "duel"):
            mode_id = "duel"
        elif part in ("黑名单", "乱斗", "黑名单乱斗", "blacklist"):
            mode_id = "blacklist"
        elif part.isdigit():
            budget = int(part)

    config = {"mode": mode_id}
    if budget is not None:
        config["budget"] = budget

    await _launch_game(
        matcher,
        group_id=int(event.group_id),
        initiator_id=int(event.user_id),
        game_id="aoe3_battle",
        mode_id=mode_id,
        extra_config=config,
    )


# -------------------- 快捷开局：斗蛐蛐自选 --------------------
_quick_battle_custom = on_command(
    "斗蛐蛐自选",
    rule=to_me(),
    priority=2,       # 比普通"斗蛐蛐"优先级高，避免被吃掉
    block=True,
)

@_quick_battle_custom.handle()
async def _(matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()) -> None:
    """自选兵种对决：@bot 斗蛐蛐自选 火枪手 散兵 15000"""
    arg_text = args.extract_plain_text().strip()
    await _handle_custom_battle(matcher, event, arg_text)


async def _handle_custom_battle(
    matcher: Matcher, event: GroupMessageEvent, arg_text: str
) -> None:
    """自选兵种对决的公共处理逻辑（供 '斗蛐蛐自选' 和 '斗蛐蛐 自选' 共用）。"""
    if not arg_text:
        await matcher.finish(
            "🎯 斗蛐蛐自选用法：\n"
            "  @我 斗蛐蛐自选 兵种名\n"
            "  @我 斗蛐蛐自选 兵种A 兵种B\n"
            "  @我 斗蛐蛐自选 兵种A 兵种B 15000\n"
            "（末尾数字为自定义预算，默认 10000）"
        )
        return

    parts = arg_text.split()
    unit_names: list[str] = []
    budget = None

    for part in parts:
        if part.isdigit():
            budget = int(part)
        else:
            unit_names.append(part)

    if not unit_names:
        await matcher.finish("⚠️ 请至少指定一个兵种名")
        return

    if len(unit_names) > 2:
        await matcher.finish("⚠️ 最多选 2 个兵种")
        return

    # 预验证兵种名（避免无效请求进入 game 流程）
    from src.plugins.games.aoe3_battle.lineup import resolve_unit_name
    from src.plugins.aoe3.repository import UnitRepo
    repo = UnitRepo.get()
    for name in unit_names:
        u = resolve_unit_name(repo, name)
        if u is None:
            await matcher.finish(f"⚠️ 找不到兵种「{name}」（需要有攻击力的战斗单位）")
            return

    config: dict = {"mode": "custom", "unit_names": unit_names}
    if budget is not None:
        config["budget"] = budget

    await _launch_game(
        matcher,
        group_id=int(event.group_id),
        initiator_id=int(event.user_id),
        game_id="aoe3_battle",
        mode_id="custom",
        extra_config=config,
    )


# -------------------- 快捷开局：红警2斗蛐蛐（独立于帝国斗蛐蛐）--------------------
_quick_ra2_battle = on_command(
    "红警斗蛐蛐",
    aliases={"ra2_battle", "红警2斗蛐蛐", "ra2斗蛐蛐"},
    rule=to_me(),
    priority=3,
    block=True,
)

@_quick_ra2_battle.handle()
async def _ra2_battle_launch(
    matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    arg_text = args.extract_plain_text().strip()

    if arg_text in ("详细", "detailed"):
        from core.group_config import set_group_config
        await set_group_config(int(event.group_id), "aoe3_battle.broadcast_mode", "detailed")
        await matcher.finish("✅ 已切换为【详细播报】模式（战斗过程会分段播报，帝国/红警通用）")
    if arg_text in ("极简", "简洁", "brief"):
        from core.group_config import set_group_config
        await set_group_config(int(event.group_id), "aoe3_battle.broadcast_mode", "brief")
        await matcher.finish("✅ 已切换为【极简播报】模式（只显示开战和战报，帝国/红警通用）")

    mode_id = "bet"
    budget = None

    for part in arg_text.split():
        if part in ("单挑", "1v1", "duel", "红警单挑"):
            mode_id = "duel"
        elif part.isdigit():
            budget = int(part)

    config: dict = {"mode": mode_id}
    if budget is not None:
        config["budget"] = budget

    await _launch_game(
        matcher,
        group_id=int(event.group_id),
        initiator_id=int(event.user_id),
        game_id="ra2_battle",
        mode_id=mode_id,
        extra_config=config,
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
