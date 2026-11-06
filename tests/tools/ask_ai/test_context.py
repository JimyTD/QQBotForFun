"""短期会话上下文。"""

from __future__ import annotations

import time

from src.plugins.tools.ask_ai import context


def setup_function() -> None:
    context.clear(1, 10)
    context.clear(2, 10)
    context.clear(1, 11)


def test_context_is_isolated_by_group_and_user() -> None:
    context.remember(1, 10, question="q1", answer="a1")
    context.remember(2, 10, question="q2", answer="a2")
    assert context.last(1, 10).answer == "a1"
    assert context.last(2, 10).answer == "a2"
    assert context.last(1, 11) is None


def test_context_keeps_recent_turns() -> None:
    for i in range(10):
        context.remember(1, 10, question=f"q{i}", answer=f"a{i}")
    turns = context.history(1, 10)
    assert len(turns) == 6
    assert turns[0].question == "q4"


def test_context_clear() -> None:
    context.remember(1, 10, question="q", answer="a")
    context.clear(1, 10)
    assert context.history(1, 10) == []


def test_build_context_respects_char_limit() -> None:
    context.remember(1, 10, question="q", answer="a" * 100)
    text = context.build_context_text(context.history(1, 10), max_chars=30)
    assert len(text) <= 30


def test_expired_context_is_removed(monkeypatch) -> None:
    context.remember(1, 10, question="old", answer="old answer")
    monkeypatch.setattr(context, "IDLE_SECONDS", 1)
    turns = context._store[(1, 10)]
    turns[0].created_at = time.time() - 2
    assert context.history(1, 10) == []


def test_follow_up_uses_previous_turn(monkeypatch) -> None:
    context.remember(1, 10, question="第一轮问题", answer="第一轮回答")
    assert context.last(1, 10).question == "第一轮问题"
