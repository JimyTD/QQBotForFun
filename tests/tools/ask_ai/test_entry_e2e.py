"""查资料入口到搜索和回复的完整链路。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import nonebot
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.adapters.onebot.v11.bot import _check_at_me
from nonebot.rule import TrieRule
from nonebot.typing import T_State

nonebot.init(command_start={""}, command_sep={" "})

from core.llm import LLMResponse  # noqa: E402
from src.plugins.tools.ask_ai import commands, context  # noqa: E402
from src.plugins.tools.web_search.models import SearchResult  # noqa: E402


async def test_group_command_reaches_search_and_reply() -> None:
    context.clear(20, 10)
    bot = Bot(nonebot.get_driver().config, "1")
    event = GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=10,
        message_type="group",
        message_id=1,
        group_id=20,
        raw_message="@bot 查资料 今天有什么科技新闻",
        font=0,
        sender={"user_id": 10},
        message=Message(
            [
                MessageSegment.at(1),
                MessageSegment.text(" 查资料 今天有什么科技新闻"),
            ]
        ),
    )
    _check_at_me(bot, event)
    assert event.is_tome()
    state = T_State()
    TrieRule.get_value(bot, event, state)
    assert await commands._cmd.rule(bot, event, state)

    legacy = [
        SearchResult(
            title="科技新闻",
            url="https://example.com/news",
            snippet="今天有一条科技新闻",
            source="page",
        )
    ]
    sent: list[str] = []

    class FakeMatcher:
        async def send(self, message):
            sent.append(str(message))

        async def finish(self, message):
            sent.append(str(message))

    with patch(
        "src.plugins.tools.web_search.service._legacy_search",
        AsyncMock(return_value=legacy),
    ) as search_call, patch(
        "src.plugins.tools.ask_ai.orchestrator.llm.chat",
        AsyncMock(return_value=LLMResponse(content="今天有一条测试科技新闻。", model="mock")),
    ) as chat_call:
        await commands._handle(
            FakeMatcher(),
            bot,
            event,
            Message([MessageSegment.text("今天有什么科技新闻")]),
        )

    assert search_call.await_count == 1
    assert chat_call.await_count == 1
    assert any("测试科技新闻" in item for item in sent)
    assert any("来源" in item for item in sent)
