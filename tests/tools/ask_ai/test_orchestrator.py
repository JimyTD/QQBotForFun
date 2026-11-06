"""AI 助手编排路径。"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from core.llm import LLMResponse
from src.plugins.tools.ask_ai import context
from src.plugins.tools.ask_ai.models import AssistantInput, SearchState
from src.plugins.tools.ask_ai.orchestrator import answer
from src.plugins.tools.web_search.models import (
    ImageResult,
    SearchBundle,
    SearchError,
    SearchNotConfiguredError,
    SearchResult,
)


def setup_function() -> None:
    context.clear(1, 10)


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 64), (255, 0, 0)).save(out, format="PNG")
    return out.getvalue()


def _bundle(*, web: bool = True, images: bool = True) -> SearchBundle:
    return SearchBundle(
        query="测试",
        web_results=[
            SearchResult(
                title="测试网页",
                url="https://example.com/a",
                snippet="摘要",
                body="正文材料",
            )
        ]
        if web
        else [],
        images=[
            ImageResult(
                title="测试图片",
                content_url="https://example.com/a.jpg",
                width=800,
                height=600,
            )
        ]
        if images
        else [],
    )


@pytest.mark.asyncio
async def test_chat_does_not_search() -> None:
    with patch(
        "src.plugins.tools.ask_ai.orchestrator.search",
        AsyncMock(side_effect=AssertionError("chat 不应搜索")),
    ), patch(
        "src.plugins.tools.ask_ai.orchestrator.llm.chat",
        AsyncMock(return_value=LLMResponse(content="递归是函数调用自身。", model="mock")),
    ):
        result = await answer(
            AssistantInput(text="解释一下递归", group_id=1, user_id=10),
            classify_with_llm=False,
        )
    assert result.answer
    assert result.search_state == SearchState.NOT_USED


@pytest.mark.asyncio
async def test_web_question_searches_and_cites() -> None:
    with patch(
        "src.plugins.tools.ask_ai.orchestrator.search",
        AsyncMock(return_value=_bundle()),
    ) as search_mock, patch(
        "src.plugins.tools.ask_ai.orchestrator.llm.chat",
        AsyncMock(return_value=LLMResponse(content="今天有一条测试新闻。", model="mock")),
    ):
        result = await answer(
            AssistantInput(text="今天有什么新闻", group_id=1, user_id=10),
            classify_with_llm=False,
        )
    search_mock.assert_awaited_once()
    assert result.used_search
    assert result.sources
    assert result.search_state == SearchState.USED


@pytest.mark.asyncio
async def test_search_failure_falls_back_with_accurate_state() -> None:
    with patch(
        "src.plugins.tools.ask_ai.orchestrator.search",
        AsyncMock(side_effect=SearchError("down")),
    ), patch(
        "src.plugins.tools.ask_ai.orchestrator.llm.chat",
        AsyncMock(return_value=LLMResponse(content="先给一个通用回答。", model="mock")),
    ):
        result = await answer(
            AssistantInput(text="今天有什么新闻", group_id=1, user_id=10),
            classify_with_llm=False,
        )
    assert result.search_state == SearchState.FAILED
    assert "通用回答" in result.answer
    assert "联网检索失败" in result.answer


@pytest.mark.asyncio
async def test_unconfigured_search_does_not_fake_realtime_answer() -> None:
    with patch(
        "src.plugins.tools.ask_ai.orchestrator.search",
        AsyncMock(side_effect=SearchNotConfiguredError("missing")),
    ), patch(
        "src.plugins.tools.ask_ai.orchestrator.llm.chat",
        AsyncMock(side_effect=AssertionError("时效题不能静默改成模型直答")),
    ):
        result = await answer(
            AssistantInput(text="今天有什么新闻", group_id=1, user_id=10),
            classify_with_llm=False,
        )
    assert result.search_state == SearchState.FAILED
    assert result.error == "search_not_configured"
    assert "无法确认" in result.answer


@pytest.mark.asyncio
async def test_image_understanding_uses_vision_scene() -> None:
    calls: list[str] = []

    async def fake_chat(*_a, **kwargs):
        calls.append(kwargs["scene"])
        return LLMResponse(content="图中是一个红色方块。", model="vision")

    with patch(
        "src.plugins.tools.ask_ai.orchestrator.resolve_image_source",
        AsyncMock(return_value=_png()),
    ), patch(
        "src.plugins.tools.ask_ai.orchestrator.llm.chat",
        AsyncMock(side_effect=fake_chat),
    ):
        result = await answer(
            AssistantInput(
                text="这是什么",
                image_sources=["https://example.com/a.png"],
                group_id=1,
                user_id=10,
            ),
            classify_with_llm=False,
        )
    assert calls == ["vision"]
    assert "红色" in result.answer


@pytest.mark.asyncio
async def test_image_search_returns_base64_image() -> None:
    with patch(
        "src.plugins.tools.ask_ai.orchestrator.search_images",
        AsyncMock(return_value=_bundle(web=False).images),
    ), patch(
        "src.plugins.tools.ask_ai.orchestrator.download_valid_image",
        AsyncMock(return_value=(_png(), "image/png", _bundle().images[0])),
    ):
        result = await answer(
            AssistantInput(text="找一张测试图", group_id=1, user_id=10),
            classify_with_llm=False,
        )
    assert result.images
    assert result.images[0].startswith("base64://")
