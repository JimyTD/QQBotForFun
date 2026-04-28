"""海龟汤消息分类测试（纯函数）。"""

from __future__ import annotations

from src.plugins.games.turtle_soup.game import _classify_message, _strip_claim_prefix


def test_classify_question_latin() -> None:
    assert _classify_message("He is alive?") == "question"


def test_classify_question_cn() -> None:
    assert _classify_message("他还活着？") == "question"


def test_classify_question_prefix() -> None:
    assert _classify_message("问：他是谁") == "question"


def test_classify_claim() -> None:
    assert _classify_message("汤底: 他是个魔法师") == "claim"
    assert _classify_message("宣告：真相就是…") == "claim"


def test_classify_chat() -> None:
    assert _classify_message("嗯嗯嗯") == "chat"
    assert _classify_message("") == "chat"


def test_classify_command() -> None:
    assert _classify_message("/soup status") == "command"


def test_strip_claim_prefix() -> None:
    assert _strip_claim_prefix("汤底: 他是魔法师") == "他是魔法师"
    assert _strip_claim_prefix("宣告：真相如下") == "真相如下"
    assert _strip_claim_prefix("没有前缀") == "没有前缀"
