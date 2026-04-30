"""趣味问答 · 答案宽松匹配 测试。"""

from __future__ import annotations

from src.plugins.games.trivia.answer_matcher import (
    looks_like_answer,
    match,
    normalize,
)


class TestNormalize:
    def test_empty(self) -> None:
        assert normalize("") == ""
        assert normalize("   ") == ""

    def test_lowercase(self) -> None:
        assert normalize("Canada") == "canada"
        assert normalize("USA") == "usa"

    def test_strip_whitespace_and_punct(self) -> None:
        assert normalize("加 拿 大!") == "加拿大"
        assert normalize("  加拿大 ？ ") == "加拿大"
        assert normalize("那是，加拿大！") == "那是加拿大"

    def test_fullwidth_to_halfwidth(self) -> None:
        # NFKC 规范化会把全角字符转半角
        assert normalize("ＵＳＡ") == "usa"
        assert normalize("Ａ１") == "a1"

    def test_traditional_to_simplified(self) -> None:
        assert normalize("國家") == "国家"
        assert normalize("愛") == "爱"


class TestMatch:
    def test_exact(self) -> None:
        assert match("加拿大", "加拿大") is True

    def test_with_trailing_punct(self) -> None:
        assert match("加拿大！", "加拿大") is True
        assert match("加拿大？", "加拿大") is True
        assert match("加拿大.", "加拿大") is True

    def test_substring_contains_answer(self) -> None:
        assert match("那是加拿大吧", "加拿大") is True
        assert match("我觉得是加拿大", "加拿大") is True

    def test_english_alias(self) -> None:
        assert match("Canada", "加拿大", ["Canada", "枫叶国"]) is True
        assert match("canada!", "加拿大", ["Canada", "枫叶国"]) is True
        assert match("那是 USA 吧", "美国", ["USA", "United States"]) is True

    def test_alias_nickname(self) -> None:
        assert match("枫叶国", "加拿大", ["Canada", "枫叶国"]) is True

    def test_miss(self) -> None:
        assert match("日本", "加拿大", ["Canada"]) is False
        assert match("法国", "加拿大", ["Canada"]) is False

    def test_empty_inputs(self) -> None:
        assert match("", "加拿大") is False
        assert match("加拿大", "") is False
        assert match("   ", "加拿大") is False

    def test_case_insensitive(self) -> None:
        assert match("canada", "加拿大", ["Canada"]) is True
        assert match("CANADA", "加拿大", ["Canada"]) is True

    def test_filler_stripping(self) -> None:
        # "我猜" 之类的废话词在兜底阶段会被剥掉
        assert match("我猜加拿大", "加拿大") is True
        assert match("应该是加拿大吧", "加拿大") is True

    def test_traditional_input(self) -> None:
        # 玩家打繁体也能认出来
        assert match("中國", "中国") is True

    def test_alias_with_spaces(self) -> None:
        # LLM 常给 "United States" 这种带空格的别名，去空格后也要能匹配
        assert match("unitedstates", "美国", ["United States"]) is True
        assert match("United  States", "美国", ["United States"]) is True


class TestLooksLikeAnswer:
    def test_short_is_answer(self) -> None:
        assert looks_like_answer("加拿大") is True
        assert looks_like_answer("那是加拿大吧") is True

    def test_empty_not_answer(self) -> None:
        assert looks_like_answer("") is False
        assert looks_like_answer("   ") is False

    def test_too_long_not_answer(self) -> None:
        # 默认上限 40 字，超过视为闲聊
        long_text = "哎呀这题好难啊我完全没有头绪不知道从哪里下手来一条线索嘛拜托拜托请再出一条线索看看"
        assert len(long_text) > 40
        assert looks_like_answer(long_text, max_len=40) is False

    def test_custom_max_len(self) -> None:
        assert looks_like_answer("abcdefgh", max_len=5) is False
        assert looks_like_answer("abc", max_len=5) is True
