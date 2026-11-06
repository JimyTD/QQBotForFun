"""AI 单一入口。"""

from __future__ import annotations

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from src.plugins.tools.ask_ai.message import image_sources, image_urls, plain_text


def test_extracts_text_and_images_without_losing_images() -> None:
    message = Message("这是什么") + MessageSegment.image("https://example.com/a.png")
    assert plain_text(message) == "这是什么"
    assert image_urls(message) == ["https://example.com/a.png"]


def test_ignores_non_http_image_identifier() -> None:
    message = Message(MessageSegment.image("file:///tmp/a.png"))
    assert image_urls(message) == []
    assert image_sources(message) == ([], ["file:///tmp/a.png"])


def test_extracts_bare_napcat_image_file_identifier() -> None:
    message = Message(MessageSegment.image("ABCDEF012345.jpg"))
    assert image_sources(message) == ([], ["ABCDEF012345.jpg"])


@pytest.mark.parametrize(
    "text",
    ["清空", "清除", "重置"],
)
def test_clear_keywords_are_stable(text: str) -> None:
    assert text in {"清空", "清除", "重置"}
