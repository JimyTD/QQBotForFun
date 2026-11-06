"""AI 助手意图路由。"""

from __future__ import annotations

from src.plugins.tools.ask_ai.intent import classify, image_query
from src.plugins.tools.ask_ai.models import TaskKind


def test_common_questions_are_chat() -> None:
    assert classify("解释一下递归") == TaskKind.CHAT
    assert classify("Python 怎么读文件") == TaskKind.CHAT
    assert classify("帮我写一段自我介绍") == TaskKind.CHAT


def test_timely_questions_use_web_search() -> None:
    assert classify("今天有什么科技新闻") == TaskKind.WEB_SEARCH
    assert classify("鸣潮最新版本活动") == TaskKind.WEB_SEARCH
    assert classify("帮我查一下显卡价格") == TaskKind.WEB_SEARCH


def test_image_search_phrases() -> None:
    assert classify("找一张少女前线2奇塔的图") == TaskKind.IMAGE_SEARCH
    assert classify("来几张星空壁纸") == TaskKind.IMAGE_SEARCH
    assert classify("换一张") == TaskKind.IMAGE_SEARCH


def test_incoming_image_uses_vision() -> None:
    assert classify("这是什么", has_image=True) == TaskKind.IMAGE_UNDERSTAND
    assert classify("图里写了什么", has_image=True) == TaskKind.IMAGE_UNDERSTAND
    assert classify("", has_image=True) == TaskKind.IMAGE_UNDERSTAND


def test_image_query_removes_instruction_words() -> None:
    assert "少女前线" in image_query("帮我找一张少女前线2奇塔的图")
    assert image_query("换一张") == "换一张"
