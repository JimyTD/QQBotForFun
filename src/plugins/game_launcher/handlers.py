"""游戏大厅：/play <game_id> 和 /quit"""

from __future__ import annotations

from nonebot import logger, on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from core import game_base, user
from core.errors import GameAlreadyRunningError, GameNotFoundError

# -------------------- /play --------------------
_play = on_command("play", aliases={"开始", "开局"}, priority=10, block=True)


@_play.handle()
async def _(
    matcher: Matcher,
    event: GroupMessageEvent,
    args: Message = CommandArg(),
) -> None:
    game_id = args.extract_plain_text().strip()
    if not game_id:
        await matcher.finish("用法：/play <game_id>\n查看游戏列表：/menu")
        return

    group_id = int(event.group_id)
    host_id = int(event.user_id)

    try:
        cls = game_base.get_game_class(game_id)
    except GameNotFoundError:
        await matcher.finish(f"⚠️ 未找到游戏 `{game_id}`。使用 /menu 查看可用游戏。")
        return

    host_user = await user.get(host_id, group_id)

    # v1 简化：开局者作为唯一玩家（允许中途有其他玩家加入由游戏自行处理）
    players = [host_user]

    # 游戏整局超时使用各游戏配置；这里可由 game class 暴露
    session_timeout = getattr(cls, "default_session_timeout_seconds", None)

    try:
        await game_base.create_and_start(
            game_id,
            group_id=group_id,
            host_id=host_id,
            players=players,
            config={},
            session_timeout_seconds=session_timeout,
        )
    except GameAlreadyRunningError as e:
        await matcher.finish(f"⚠️ {e}")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[launcher] start failed game={game_id}: {e}")
        await matcher.finish(f"⚠️ 启动失败：{e}")


# -------------------- /quit --------------------
_quit = on_command("quit", aliases={"结束", "终止"}, priority=10, block=True)


@_quit.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    ok = await game_base.abort_by_group(group_id)
    if ok:
        await matcher.finish("🏳 本局游戏已终止")
    else:
        await matcher.finish("本群当前没有进行中的游戏")


# -------------------- /games（别名，兼容）--------------------
# /games 的列表展示由 core_commands 的 /menu 承担，此处不重复
