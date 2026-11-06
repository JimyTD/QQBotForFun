"""时间锚点与旧材料过滤。"""

from __future__ import annotations

from datetime import date

from src.plugins.tools.ask_ai.recency import (
    drop_stale_results,
    is_recency_question,
    rewrite_search_query,
)
from src.plugins.tools.web_search.models import SearchResult

_TODAY = date(2026, 11, 6)


def test_recency_query_gets_anchor() -> None:
    assert "2026年11月" in rewrite_search_query("鸣潮最近开了什么活动", today=_TODAY)
    assert "2026年11月6日" in rewrite_search_query("今天有什么新闻", today=_TODAY)


def test_drop_old_results() -> None:
    results = [
        SearchResult("旧闻", "https://example.com/old", "2025年3月活动"),
        SearchResult("新消息", "https://example.com/new", "2026年11月6日 更新"),
    ]
    kept = drop_stale_results(results, today=_TODAY)
    assert [r.title for r in kept] == ["新消息"]


def test_flags() -> None:
    assert is_recency_question("最新比分")
    assert is_recency_question("原神卡池")
    assert not is_recency_question("Python 怎么读文件")
