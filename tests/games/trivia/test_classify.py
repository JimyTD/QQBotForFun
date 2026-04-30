"""趣味问答 · 玩家消息分类 + 计分档位 测试（纯函数）。"""

from __future__ import annotations

from src.plugins.games.trivia.game import _classify_message, _coin_for_tier, _score_for_tier


class TestClassifyMessage:
    def test_empty(self) -> None:
        assert _classify_message("") == "chat"
        assert _classify_message("   ") == "chat"

    def test_command_goes_to_chat(self) -> None:
        # 以 / 开头的消息交给其他 matcher，游戏这里返回 chat 不处理
        assert _classify_message("/问答 状态") == "chat"
        assert _classify_message("/结束") == "chat"

    def test_more_clue_zh(self) -> None:
        assert _classify_message("线索") == "more_clue"
        assert _classify_message("再来一条") == "more_clue"
        assert _classify_message("更多线索") == "more_clue"
        assert _classify_message("提示") == "more_clue"

    def test_more_clue_en(self) -> None:
        assert _classify_message("hint") == "more_clue"
        assert _classify_message("clue") == "more_clue"
        assert _classify_message("HINT") == "more_clue"  # 大小写不敏感

    def test_skip(self) -> None:
        assert _classify_message("跳过") == "skip"
        assert _classify_message("不会") == "skip"
        assert _classify_message("pass") == "skip"
        assert _classify_message("下一题") == "skip"

    def test_answer_short(self) -> None:
        assert _classify_message("加拿大") == "answer"
        assert _classify_message("那是加拿大吧") == "answer"
        assert _classify_message("Canada") == "answer"

    def test_too_long_is_chat(self) -> None:
        long_text = "这题好难我完全没头绪根本不知道从何入手今天心情又不好"
        assert _classify_message(long_text * 3) == "chat"

    def test_empty_after_strip(self) -> None:
        assert _classify_message("   ") == "chat"


class TestScoreForTier:
    def test_first_clue(self) -> None:
        assert _score_for_tier(1) == 5

    def test_second_and_third(self) -> None:
        assert _score_for_tier(2) == 3
        assert _score_for_tier(3) == 3

    def test_fourth_and_fifth(self) -> None:
        assert _score_for_tier(4) == 1
        assert _score_for_tier(5) == 1

    def test_zero_clue_still_full_reward(self) -> None:
        # 理论上 clues_shown 最小是 1，但边界情况下 0 也要有结果
        assert _score_for_tier(0) == 5

    def test_overflow(self) -> None:
        # 不会出现 > 5，但即便出现也应走最低档
        assert _score_for_tier(100) == 1


class TestCoinForTier:
    def test_first_clue(self) -> None:
        assert _coin_for_tier(1) == 3

    def test_second_and_third(self) -> None:
        assert _coin_for_tier(2) == 2
        assert _coin_for_tier(3) == 2

    def test_fourth_and_fifth(self) -> None:
        assert _coin_for_tier(4) == 1
        assert _coin_for_tier(5) == 1

    def test_overflow_falls_to_lowest(self) -> None:
        assert _coin_for_tier(100) == 1


class TestMODES:
    def test_six_types_registered(self) -> None:
        from src.plugins.games.trivia.game import TriviaGame
        mode_ids = [m.id for m in TriviaGame.MODES]
        assert mode_ids == ["country", "city", "food", "person", "animal", "idiom"]

    def test_mode_has_chinese_alias(self) -> None:
        from src.plugins.games.trivia.game import TriviaGame
        country = next(m for m in TriviaGame.MODES if m.id == "country")
        assert "猜国家" in country.aliases
