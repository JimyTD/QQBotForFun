"""原版入口逐字兼容。"""

from __future__ import annotations

import nonebot
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageSegment,
)
from nonebot.adapters.onebot.v11.bot import _check_at_me
from nonebot.rule import TrieRule
from nonebot.typing import T_State

nonebot.init(command_start={""}, command_sep={" "})

from src.plugins.tools.ask_ai import commands  # noqa: E402


async def _event(command: str) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=10,
        message_type="group",
        message_id=1,
        group_id=20,
        raw_message=f"@bot {command} 测试问题",
        font=0,
        sender={"user_id": 10},
        message=Message(
            [MessageSegment.at(1), MessageSegment.text(f" {command} 测试问题")]
        ),
    )


async def test_all_original_entry_commands_match() -> None:
    bot = Bot(nonebot.get_driver().config, "1")
    for command in (
        "查资料",
        "问AI",
        "问ai",
        "ai",
        "AI",
        "搜索",
        "搜一下",
        "search",
    ):
        event = await _event(command)
        _check_at_me(bot, event)
        state = T_State()
        TrieRule.get_value(bot, event, state)
        assert await commands._cmd.rule(bot, event, state), command
