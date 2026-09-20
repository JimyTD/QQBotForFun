"""查资料检索与成文的纯函数测试。"""

from __future__ import annotations

from src.plugins.tools.ask_ai.service import condense_query, should_skip_search
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

    def test_self_questions_skip_search(self) -> None:
        """问机器人自身：答案在本地 prompt 里。

        回归用例：2026-09-18 生产日志里 `你是什么模型` / `介绍一下你自己` /
        `你能做什么` 三次全被拿去搜狗搜，搜回垃圾材料污染回答，
        用户只好反复追问「你是什么模型」。
        """
        assert should_skip_search("你是什么模型")
        assert should_skip_search("你使用了什么模型")
        assert should_skip_search("介绍一下你自己")
        assert should_skip_search("你能做什么")
        assert should_skip_search("你有哪些功能")
        assert should_skip_search("你怎么用")

    def test_third_party_questions_still_search(self) -> None:
        """别误伤：问别人（而不是机器人自己）仍要联网。"""
        assert not should_skip_search("deepseek 是什么模型")
        assert not should_skip_search("鸣潮什么版本")


class TestCondenseQuery:
    def test_drops_instruction_words(self) -> None:
        """回归：生产日志里整句 24 字原话直接丢给搜狗 → 群友吐槽「搜索有点蠢」。"""
        q = condense_query("介绍一下鸣潮当期卡池和下一期卡池，并列出抽卡推荐")
        assert "介绍" not in q
        assert "列出" not in q
        assert "推荐" not in q
        assert "鸣潮" in q
        assert "卡池" in q

    def test_keeps_time_and_entity(self) -> None:
        q = condense_query("2026年9月18日在steam有哪些热门游戏有优惠")
        assert "2026" in q
        assert "steam" in q
        assert "有哪些" not in q

    def test_short_entity_unchanged(self) -> None:
        assert condense_query("少女前线追放26年9月卡池信息") == "少女前线追放26年9月卡池信息"

    def test_all_filler_falls_back_to_original(self) -> None:
        """删光了就退回原句，绝不能返回空串。"""
        assert condense_query("介绍一下") == "介绍一下"
        assert condense_query("") == ""


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
