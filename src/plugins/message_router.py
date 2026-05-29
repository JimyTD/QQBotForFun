"""全局消息入站路由。

处理优先级（priority=5，在命令 priority=3 之后执行）：
  1. @机器人 的消息转 `core.session.route_incoming_message`（游戏内提问等）
  2. 有活跃游戏但未处理 → 游戏情境提示
  3. 否则 → 兜底「没听懂」
"""

from __future__ import annotations

from nonebot import on_message
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from core import game_base, session as csession

_matcher = on_message(
    rule=Rule(),
    priority=5,
    block=False,
)


def _is_at_bot(event: MessageEvent) -> bool:
    """检查消息是否 @了当前机器人。"""
    if hasattr(event, "is_tome"):
        return event.is_tome()
    return False


def _strip_at(event: MessageEvent) -> str:
    """从消息里剥离 @段，返回纯文本。"""
    parts: list[str] = []
    for seg in event.get_message():
        if seg.type == "text":
            parts.append(str(seg.data.get("text", "")))
    return "".join(parts).strip()


# 斗蛐蛐对局内口令（无对局时应明确提示，而非静默或泛泛兜底）
_BATTLE_INGAME_CMDS = frozenset({
    "开战", "start", "go",
    "1", "2", "押1", "押2", "押注1", "押注2",
})

_NO_BATTLE_HINT = (
    "⚠️ 当前没有进行中的斗蛐蛐对局\n"
    "💡 先 @我 斗蛐蛐 或 @我 红警斗蛐蛐 开局"
)

# 兜底帮助文案（当 @机器人 但无法识别指令时回复）
_FALLBACK_HELP = (
    "🤖 我没听懂，试试以下指令吧：\n"
    "\n"
    "🎮 @我 海龟汤\n"
    "🎮 @我 趣味问答\n"
    "⚔️ @我 斗蛐蛐\n"
    "⚔️ @我 斗蛐蛐 王中王\n"
    "⚔️ @我 斗蛐蛐 5时代\n"
    "⚔️ @我 红警斗蛐蛐\n"
    "🍱 @我 吃什么\n"
    "🃏 @我 查卡 卡名\n"
    "🏰 @我 aoe3 兵种名\n"
    "🔍 @我 查资料 你的问题\n"
    "⏰ @我 提醒 开/关\n"
    "📜 @我 帮助（查看完整指令）"
)


@_matcher.handle()
async def _route(event: MessageEvent, matcher: Matcher) -> None:
    qq_id = int(event.user_id)
    group_id: int | None = None
    if isinstance(event, GroupMessageEvent):
        group_id = int(event.group_id)
    elif isinstance(event, PrivateMessageEvent):
        group_id = None

    # 必须 @机器人 才处理
    at_bot = _is_at_bot(event)
    if not at_bot:
        return

    text = _strip_at(event)

    # 只 @了机器人但没说话 → 回复帮助
    if not text:
        await matcher.finish(_FALLBACK_HELP)
        return

    # 1) 游戏内提问 / ask 等待
    consumed = await csession.route_incoming_message(qq_id, group_id, text)
    if consumed:
        matcher.stop_propagation()
        return

    # 2) 王中王选主题中
    if group_id is not None:
        from src.plugins.games.aoe3_battle.rival_pick import has_pending
        if has_pending(group_id):
            await matcher.finish(
                "⚔️ 王中王选主题中\n"
                "💡 点选单消息上的表情，或回复 1 / 2 / 3\n"
                "💡 @我 结束 可取消"
            )
            return

    # 3) 有活跃游戏但未识别 → 情境提示
    if group_id is not None and csession.is_in_game(group_id):
        hint = game_base.in_game_hint_for_group(group_id)
        if hint:
            await matcher.finish(hint)
            return

    # 4) 斗蛐蛐对局内口令，但当前无斗蛐蛐对局
    if text in _BATTLE_INGAME_CMDS:
        await matcher.finish(_NO_BATTLE_HINT)
        return

    # 4) 兜底：无对局且无法识别 → 通用帮助
    await matcher.finish(_FALLBACK_HELP)
