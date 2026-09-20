"""时效改写与旧材料过滤。"""

from __future__ import annotations

from datetime import date

from src.plugins.tools.ask_ai.recency import (
    drop_stale_results,
    is_recency_question,
    rewrite_search_query,
)
from src.plugins.tools.web_search.searxng import SearchResult, should_try_baike

_TODAY = date(2026, 8, 13)


class TestRewrite:
    def test_wuwa_recency_gets_year_month(self) -> None:
        q = rewrite_search_query("鸣潮最近开了什么活动", today=_TODAY)
        assert "2026年8月" in q
        assert "鸣潮" in q
        assert "活动" in q
        assert "最近" not in q

    def test_news_gets_full_date(self) -> None:
        q = rewrite_search_query("今天有什么新闻", today=_TODAY)
        assert "2026年8月13日" in q
        assert "新闻" in q

    def test_encyclopedia_unchanged(self) -> None:
        assert rewrite_search_query("量子力学是什么", today=_TODAY) == "量子力学是什么"

    def test_timely_topic_gets_anchor_without_recency_word(self) -> None:
        """回归：字面没有「最近」，但话题随时间变（版本 / 卡池）也要锚定当下。

        生产日志里「原神7.1版本卡池信息」原样去搜 → 命中几年前的旧攻略，
        而 prompt 的「旧年版本直接忽略」在材料不带年份时无从生效。
        """
        q = rewrite_search_query("原神7.1版本卡池信息", today=_TODAY)
        assert "2026年8月" in q
        assert "原神7.1版本卡池信息" in q

        q2 = rewrite_search_query("gta6各平台发售时间", today=_TODAY)
        assert "2026年8月" in q2

    def test_recency_flag(self) -> None:
        assert is_recency_question("鸣潮最近开了什么活动")
        assert not is_recency_question("量子力学是什么")

    def test_timely_topic_flag(self) -> None:
        assert is_recency_question("原神7.1版本卡池信息")
        assert is_recency_question("gta6各平台发售时间")
        assert is_recency_question("steam 秋季特惠")
        # 无关话题不能误伤
        assert not is_recency_question("Python怎么读文件")
        assert not is_recency_question("量子力学是什么")

    def test_rewritten_skips_baike(self) -> None:
        q = rewrite_search_query("鸣潮最近开了什么活动", today=_TODAY)
        assert not should_try_baike(q)


class TestDropStale:
    def test_drops_old_year_and_old_version(self) -> None:
        results = [
            SearchResult(
                title="鸣潮2.1近期活动有哪些-2025年3月活动汇总",
                url="https://example.com/2.1",
                snippet="2.1版本活动",
            ),
            SearchResult(
                title="《鸣潮》2.0版本近期活动汇总",
                url="https://example.com/2.0",
                snippet="2.0版本",
            ),
            SearchResult(
                title="鸣潮3.6版本8月20日即将更新",
                url="https://example.com/3.6",
                snippet="2026年8月20日 蜃云灯影",
            ),
        ]
        kept = drop_stale_results(results, today=_TODAY)
        titles = [r.title for r in kept]
        assert any("3.6" in t for t in titles)
        assert not any("2.1" in t for t in titles)
        assert not any("2.0" in t for t in titles)

    def test_drops_history_today(self) -> None:
        results = [
            SearchResult(
                title="今天是4月8日,历史上的今天有哪些大事发生",
                url="https://example.com/a",
                snippet="历史",
            ),
            SearchResult(
                title="今日国内新闻",
                url="https://example.com/b",
                snippet="2026年8月13日 王希季逝世",
            ),
        ]
        kept = drop_stale_results(results, today=_TODAY)
        assert len(kept) == 1
        assert "国内新闻" in kept[0].title
