"""查资料检索与成文的纯函数测试。"""

from __future__ import annotations

from src.plugins.tools.ask_ai.service import should_skip_search
from src.plugins.tools.web_search.searxng import (
    SearchResult,
    format_results_for_llm,
    format_sources_for_user,
    should_try_baike,
)


class TestShouldTryBaike:
    def test_encyclopedia_yes(self) -> None:
        assert should_try_baike("量子力学是什么")
        assert should_try_baike("陈默")

    def test_fresh_no(self) -> None:
        assert not should_try_baike("今天有什么新闻")
        assert not should_try_baike("最新比分")
        assert not should_try_baike("鸣潮最近开了什么活动")

    def test_howto_no(self) -> None:
        assert not should_try_baike("Python怎么读文件")
        assert not should_try_baike("如何安装 docker")

    def test_compare_no(self) -> None:
        assert not should_try_baike("豆包和元宝的区别")


class TestSkipSearch:
    def test_math_and_hi(self) -> None:
        assert should_skip_search("1+1")
        assert should_skip_search("你好")
        assert should_skip_search("hi")

    def test_real_question_searches(self) -> None:
        assert not should_skip_search("量子力学是什么")
        assert not should_skip_search("今天有什么新闻")


class TestFormatResults:
    def test_prefers_body_over_snippet(self) -> None:
        results = [
            SearchResult(
                title="词条",
                url="https://baike.baidu.com/item/x",
                snippet="短摘要",
                body="这是足够长的正文，用来生成完整回答。",
                source="baike",
            )
        ]
        text = format_results_for_llm(results)
        assert "足够长的正文" in text
        assert "短摘要" not in text
        assert "baike.baidu.com" in text

    def test_extracts_data_url_not_sogou_wrapper(self) -> None:
        from src.plugins.tools.web_search.searxng import _extract_real_url

        block = (
            '<a href="/link?url=abc">t</a>'
            '<div data-url="https://www.zhihu.com/question/376942784"></div>'
        )
        url = _extract_real_url("/link?url=abc", block)
        assert url == "https://www.zhihu.com/question/376942784"

    def test_sources_hide_sogou_redirector(self) -> None:
        results = [
            SearchResult(
                title="某新闻",
                url="https://www.sogou.com/link?url=abc",
                snippet="...",
                source="sogou",
            ),
            SearchResult(
                title="百科",
                url="https://baike.baidu.com/item/x",
                snippet="...",
                source="baike",
            ),
        ]
        lines = format_sources_for_user(results)
        assert lines[0] == "1. 某新闻"
        assert "baike.baidu.com" in lines[1]
