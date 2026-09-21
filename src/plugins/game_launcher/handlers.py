"""游戏大厅：快捷开局 / 结束。

快捷开局：
  @机器人 海龟汤     → 默认模式（题库随机）直接开局
  @机器人 趣味问答   → 随机类型直接开局
  @机器人 结束       → 终止当前群的游戏
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from nonebot import logger, on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from core import game_base
from core.errors import GameAlreadyRunningError
from plugins.aoe3_battle_args import (
    extract_age,
    parse_default_budget,
    parse_civ_war_args,
    parse_custom_battle_args,
)

# 北京时间（服务器容器是 UTC，展示给群里的时刻要换算）
_CST = timezone(timedelta(hours=8))


def _game_label(game_id: str) -> str:
    """game_id → 中文名（找不到就退回 id），让提示里出现「海龟汤」而不是 turtle_soup。"""
    try:
        return game_base.get_game_class(game_id).name
    except Exception:  # noqa: BLE001
        return game_id


def _fmt_started(started: datetime) -> str:
    """UTC 的 started_at → 北京时间的 MM-DD HH:MM。"""
    return started.replace(tzinfo=timezone.utc).astimezone(_CST).strftime("%m-%d %H:%M")


def _fmt_elapsed(started: datetime) -> str:
    """已经跑了多久（人话）。"""
    secs = int((datetime.utcnow() - started).total_seconds())
    if secs < 60:
        return "不到 1 分钟"
    mins = secs // 60
    if mins < 60:
        return f"{mins} 分钟"
    hours = mins // 60
    if hours < 24:
        return f"{hours} 小时 {mins % 60} 分钟"
    return f"{hours // 24} 天 {hours % 24} 小时"


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
        ctx = runner.ctx
        # 这条提示以前**一行日志都没有**：线上报"本群已有进行中的 xxx"时，
        # 事后完全看不出那是哪一局、什么时候开的、是不是已经结束却没清干净的死局
        # （`ended=True` = 已经走过 end()，正常不该还挂在注册表里）。
        # 有了这两个字段，看日志一眼就能判定是"真在玩"还是"僵尸占群"。
        logger.warning(
            f"[launcher] 拒绝开局 game={game_id} group={group_id} "
            f"initiator={initiator_id}：本群被占用 "
            f"occupied_game={ctx.game_id} sid={ctx.session_id} "
            f"started={ctx.started_at.isoformat()} ended={runner._ended}"
        )
        await matcher.finish(
            f"⚠️ 本群已有进行中的「{_game_label(ctx.game_id)}」。\n"
            f"   局号 {ctx.session_id} · 开始于 {_fmt_started(ctx.started_at)}"
            f"（已 {_fmt_elapsed(ctx.started_at)}）\n"
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
        logger.warning(f"[launcher] create_and_start 拒绝 game={game_id} group={group_id}: {e}")
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


# 时代参数：「3时代」/「时代3」/「age3」（N=2~5），见 aoe3-battle §3.10.6
def _extract_age(parts: list[str]) -> tuple[int | None, list[str]]:
    """从分词里抽出时代参数，返回 (age, 去掉时代词后的分词)。"""
    return extract_age(parts)


_AGE_CONFIG_KEY = "aoe3_battle.default_age"
_BUDGET_CONFIG_KEY = "aoe3_battle.default_budget"
_AGE_NAMES = {2: "商业时代", 3: "要塞时代", 4: "工业时代", 5: "帝王时代"}
_BATTLE_BUDGET_MIN = 1000
_BATTLE_BUDGET_MAX = 50000


async def _get_default_age(group_id: int) -> int | None:
    """读取本群持久默认时代（未设置过则返回 None，由 game.py AGE_DEFAULT 兜底）。"""
    from core.group_config import get_group_config
    val = await get_group_config(group_id, _AGE_CONFIG_KEY)
    if val and val.isdigit() and 2 <= int(val) <= 5:
        return int(val)
    return None


async def _set_default_age(matcher: Matcher, group_id: int, age: int) -> None:
    """设置本群持久默认时代。"""
    from core.group_config import set_group_config
    await set_group_config(group_id, _AGE_CONFIG_KEY, str(age))
    name = _AGE_NAMES.get(age, f"{age}时代")
    await matcher.finish(f"✅ 本群斗蛐蛐默认时代已设为【{name}（{age}）】")


async def _get_default_budget(group_id: int) -> int | None:
    """读取本群持久默认预算（未设置或异常时返回 None，由 game.py 兜底）。"""
    from core.group_config import get_group_config

    value = await get_group_config(group_id, _BUDGET_CONFIG_KEY)
    if value.isdigit() and _BATTLE_BUDGET_MIN <= int(value) <= _BATTLE_BUDGET_MAX:
        return int(value)
    return None


async def _set_default_budget(
    matcher: Matcher,
    group_id: int,
    budget: int,
) -> None:
    """设置本群持久默认预算，不开启对局。"""
    from core.group_config import set_group_config

    await set_group_config(group_id, _BUDGET_CONFIG_KEY, str(budget))
    await matcher.finish(f"✅ 本群斗蛐蛐默认预算已设为【{budget}】")


async def _handle_default_budget(
    matcher: Matcher,
    group_id: int,
    parts: list[str],
) -> bool:
    """Handle the persistent-budget branch. Return True when it consumed input."""
    budget, error = parse_default_budget(parts)
    if error:
        await matcher.finish(error)
        return True
    if budget is None:
        return False
    await _set_default_budget(matcher, group_id, budget)
    return True


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

    # ---- 播报模式切换（不开局）----
    if arg_text in ("详细", "detailed"):
        from core.group_config import set_group_config
        await set_group_config(int(event.group_id), "aoe3_battle.broadcast_mode", "detailed")
        await matcher.finish("✅ 已切换为【详细播报】模式（战斗过程会分段播报）")
    if arg_text in ("极简", "简洁", "brief"):
        from core.group_config import set_group_config
        await set_group_config(int(event.group_id), "aoe3_battle.broadcast_mode", "brief")
        await matcher.finish("✅ 已切换为【极简播报】模式（只显示开战和战报）")

    # ---- 永久默认预算（只设置，不开局）----
    raw_parts = arg_text.split()
    if await _handle_default_budget(matcher, int(event.group_id), raw_parts):
        return

    # ---- 时代参数（所有模式通用）："斗蛐蛐 5时代" / "斗蛐蛐 火枪 3时代" ----
    age, parts = _extract_age(raw_parts)
    explicit_age = age is not None

    # ---- 只写时代、没有其他词 → 设置本群默认时代，不开局 ----
    if age is not None and not parts:
        await _set_default_age(matcher, int(event.group_id), age)
        return

    # 没有显式指定时代 → 读本群持久默认
    if age is None:
        age = await _get_default_age(int(event.group_id))
    group_budget = await _get_default_budget(int(event.group_id))

    # ---- 国战：随机文明 / 明确两个文明 ----
    if parts and parts[0] == "国战":
        await _handle_civ_war_battle(
            matcher,
            event,
            parts[1:],
            age=age,
            explicit_age=explicit_age,
            group_budget=group_budget,
        )
        return

    # ---- 锦标赛："斗蛐蛐 锦标赛" ----
    if parts and parts[0] == "锦标赛":
        await _handle_tournament_battle(
            matcher, event, age=age, budget=group_budget
        )
        return

    # ---- 王中王："斗蛐蛐 王中王" / "斗蛐蛐 王中王 散兵 15000" ----
    if parts and parts[0] == "王中王":
        await _handle_rival_battle(
            matcher,
            event,
            " ".join(parts[1:]),
            age=age,
            group_budget=group_budget,
        )
        return

    # ---- 指定兵种：参数中有非模式关键词且非纯数字 → 当作兵种名 ----
    _MODE_KEYWORDS = {
        "单挑", "乱斗", "国战", "王中王", "锦标赛",
    }
    unknown_words = [p for p in parts if p not in _MODE_KEYWORDS and not p.isdigit()]
    if unknown_words:
        # 有无法识别为模式的词 → 视为兵种名，走指定兵种对决。
        await _handle_custom_battle(
            matcher,
            event,
            " ".join(parts),
            age=age,
            group_budget=group_budget,
        )
        return

    mode_id = "bet"  # 默认押注模式
    budget = None     # None = 使用默认值

    # 解析参数：可以是模式（单挑/乱斗）或资源数字
    for part in parts:
        if part == "单挑":
            mode_id = "duel"
        elif part == "乱斗":
            mode_id = "blacklist"
        elif part.isdigit():
            budget = int(part)

    config = {"mode": mode_id}
    if budget is not None:
        config["budget"] = budget
    elif group_budget is not None:
        config["budget"] = group_budget
    if age is not None:
        config["age"] = age
    await _launch_game(
        matcher,
        group_id=int(event.group_id),
        initiator_id=int(event.user_id),
        game_id="aoe3_battle",
        mode_id=mode_id,
        extra_config=config,
    )


async def _handle_civ_war_battle(
    matcher: Matcher,
    event: GroupMessageEvent,
    parts: list[str],
    *,
    age: int | None,
    explicit_age: bool,
    group_budget: int | None,
) -> None:
    """Handle ``斗蛐蛐 国战 [文明A 文明B] [预算]``."""
    civ_tokens, budget, error = parse_civ_war_args(parts)
    if error:
        await matcher.finish(error)
        return
    if explicit_age and age == 2:
        await matcher.finish("⚠️ 国战第一期支持 3~5 时代，不支持 2 时代")
        return
    if age is None or age < 3:
        age = 3
    if budget is not None and not _BATTLE_BUDGET_MIN <= budget <= _BATTLE_BUDGET_MAX:
        await matcher.finish(
            f"⚠️ 资源预算需在 {_BATTLE_BUDGET_MIN}~{_BATTLE_BUDGET_MAX} 之间"
        )
        return

    civ_ids: list[str] = []
    if civ_tokens is not None:
        from src.plugins.games.aoe3_battle.civ_war_civs import resolve_civ

        profiles = []
        for token in civ_tokens:
            profile = resolve_civ(token)
            if profile is None:
                await matcher.finish(f"⚠️ 找不到可玩主文明「{token}」")
                return
            profiles.append(profile)
        if profiles[0].id == profiles[1].id:
            await matcher.finish("⚠️ 国战双方必须是两个不同文明")
            return
        civ_ids = [profile.id for profile in profiles]

    config: dict = {"mode": "civ_war", "age": age, "civ_ids": civ_ids}
    if budget is not None:
        config["budget"] = budget
    elif group_budget is not None:
        config["budget"] = group_budget
    await _launch_game(
        matcher,
        group_id=int(event.group_id),
        initiator_id=int(event.user_id),
        game_id="aoe3_battle",
        mode_id="civ_war",
        extra_config=config,
    )


async def _handle_custom_battle(
    matcher: Matcher, event: GroupMessageEvent, arg_text: str,
    age: int | None = None,
    group_budget: int | None = None,
) -> None:
    """处理 ``斗蛐蛐 <兵种A> [兵种B] [预算]`` 的指定兵种对决。"""
    if not arg_text:
        await matcher.finish(
            "🎯 指定兵种对决用法：\n"
            "  @我 斗蛐蛐 兵种A 兵种B\n"
            "  @我 斗蛐蛐 兵种A 兵种B 15000（预算模式）\n"
            "  @我 斗蛐蛐 兵种A 100 兵种B 50（固定数量，1~1000）\n"
            "（可加「N时代」N=2~5）"
        )
        return

    # 时代词已在主入口处理；这里防御性地再抽一次，便于直接调用此函数的测试。
    age_inline, parts = _extract_age(arg_text.split())
    if age is None:
        age = age_inline
    unit_names, unit_counts, budget, error = parse_custom_battle_args(parts)
    if error:
        await matcher.finish(error)
        return

    # 预验证兵种名（避免无效请求进入 game 流程）
    from src.plugins.aoe3.repository import UnitRepo
    from src.plugins.games.aoe3_battle.lineup import resolve_unit_name
    repo = UnitRepo.get()
    for name in unit_names:
        u = resolve_unit_name(repo, name)
        if u is None:
            await matcher.finish(f"⚠️ 找不到兵种「{name}」（需要有攻击力的战斗单位）")
            return

    config: dict = {"mode": "custom", "unit_names": unit_names}
    if unit_counts is not None:
        config["unit_counts"] = unit_counts
    if budget is not None:
        config["budget"] = budget
    elif group_budget is not None:
        config["budget"] = group_budget
    if age is not None:
        config["age"] = age
    await _launch_game(
        matcher,
        group_id=int(event.group_id),
        initiator_id=int(event.user_id),
        game_id="aoe3_battle",
        mode_id="custom",
        extra_config=config,
    )


async def _handle_tournament_battle(
    matcher: Matcher, event: GroupMessageEvent,
    age: int | None = None,
    budget: int | None = None,
) -> None:
    """王中王锦标赛：随机 3 主题 + 表情选（同王中王流程）。"""
    from src.plugins.games.aoe3_battle.rival_pick import start_tournament_pick

    group_id = int(event.group_id)
    initiator_id = int(event.user_id)

    err = await start_tournament_pick(
        group_id=group_id,
        initiator_id=initiator_id,
        budget=budget,
        age=age,
    )
    if err:
        await matcher.finish(err)


async def _handle_rival_battle(
    matcher: Matcher, event: GroupMessageEvent, arg_text: str,
    age: int | None = None,
    group_budget: int | None = None,
) -> None:
    """王中王：无参数 → 随机 3 主题 + 表情选；有主题名 → 直接开局。"""
    from src.plugins.games.aoe3_battle.rival_pick import (
        launch_rival_direct,
        start_theme_pick,
    )

    group_id = int(event.group_id)
    initiator_id = int(event.user_id)
    age_inline, parts = _extract_age(arg_text.split())
    if age is None:
        age = age_inline

    theme_token: str | None = None
    budget = group_budget
    for part in parts:
        if part.isdigit():
            budget = int(part)
        elif theme_token is None:
            theme_token = part
        else:
            await matcher.finish("⚠️ 王中王快捷开局只能指定一个主题")
            return

    if theme_token:
        err = await launch_rival_direct(
            group_id=group_id,
            initiator_id=initiator_id,
            theme_token=theme_token,
            budget=budget,
            age=age,
        )
        if err:
            await matcher.finish(err)
        return

    err = await start_theme_pick(
        group_id=group_id,
        initiator_id=initiator_id,
        budget=budget,
        age=age,
    )
    if err:
        await matcher.finish(err)


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

    from src.plugins.games.aoe3_battle.rival_pick import cancel_pending

    if cancel_pending(group_id):
        await matcher.finish("🏳 已取消王中王选主题。")
        return

    # 报名房间（还没开局）也要能收掉，否则房主挂机就没人能清场了
    from src.plugins.games.deep_sea_mission.commands import cancel_room as cancel_deep_sea_room
    from src.plugins.games.silent_mark.commands import cancel_room as cancel_silent_mark_room

    if cancel_deep_sea_room(group_id) or cancel_silent_mark_room(group_id):
        await matcher.finish("🏳 已取消报名房间。")
        return

    ok = await game_base.abort_by_group(group_id)
    # 「我明明结束过，怎么还被占着」这类问题，以前日志里查不到任何痕迹
    logger.info(
        f"[launcher] 结束 group={group_id} by={event.user_id} -> "
        f"{'已终止' if ok else '本群无对局'}"
    )
    if ok:
        await matcher.finish("🏳 本局游戏已终止。")
    else:
        await matcher.finish("本群当前没有进行中的游戏。")
