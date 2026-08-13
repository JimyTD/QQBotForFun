"""answer_question 路径：有搜索材料时必须走总结，而不是纯模型瞎编。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.plugins.tools.ask_ai.service import answer_question
from src.plugins.tools.web_search.searxng import SearchResult


@pytest.mark.asyncio
async def test_answer_uses_search_materials() -> None:
    fake = [
        SearchResult(
            title="量子力学 - 百度百科",
            url="https://baike.baidu.com/item/量子力学",
            snippet="物理学分支",
            body="量子力学是描述微观粒子运动的物理学分支。",
            source="baike",
        )
    ]

    async def fake_chat(*_a, **_k):
        from core.llm import LLMResponse

        return LLMResponse(
            content="量子力学是描述微观世界的物理理论，核心是波函数与测量。",
            model="mock",
        )

    with patch(
        "src.plugins.tools.ask_ai.service.search",
        AsyncMock(return_value=fake),
    ), patch(
        "src.plugins.tools.ask_ai.service.llm.chat",
        AsyncMock(side_effect=fake_chat),
    ):
        result = await answer_question("量子力学是什么")

    assert result.used_search
    assert "量子力学" in result.answer
    assert result.sources
    assert "百度百科" in result.sources[0]


@pytest.mark.asyncio
async def test_skip_search_marks_offline() -> None:
    async def fake_chat(*_a, **_k):
        from core.llm import LLMResponse

        return LLMResponse(content="2", model="mock")

    with patch(
        "src.plugins.tools.ask_ai.service.search",
        AsyncMock(side_effect=AssertionError("不应搜索")),
    ), patch(
        "src.plugins.tools.ask_ai.service.llm.chat",
        AsyncMock(side_effect=fake_chat),
    ):
        result = await answer_question("1+1")

    assert not result.used_search
    assert result.answer == "2"
