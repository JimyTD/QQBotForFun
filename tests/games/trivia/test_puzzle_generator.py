"""趣味问答 · 题目生成器校验逻辑 测试。

只测纯函数 _validate，不调真实 LLM。
"""

from __future__ import annotations

import pytest

from src.plugins.games.trivia.puzzle_generator import _validate


def _good_puzzle() -> dict:
    """一个会通过所有校验的"标准答卷"。

    注意：所有线索都不能出现 answer 或任何 alias 的字符
    （归一化后的子串命中也算泄露）。
    """
    return {
        "answer": "加拿大",
        "aliases": ["Canada", "枫叶国"],
        "clues": [
            "它曾是英法殖民地，独立史与两大宗主国相关",
            "它的官方体育运动之一是冰球",
            "国土有大量北极圈内的寒带森林",
            "是世界上面积第二大的国家",
            "首都是渥太华，官方语言英语和法语",
        ],
        "explanation": "面积约 998 万平方公里，仅次于俄罗斯。",
    }


class TestValidateHappyPath:
    def test_good_puzzle_passes(self) -> None:
        ok, reason = _validate(_good_puzzle(), "country")
        assert ok, f"expected pass, got reason: {reason}"


class TestValidateMissingFields:
    def test_missing_answer(self) -> None:
        data = _good_puzzle()
        del data["answer"]
        ok, reason = _validate(data, "country")
        assert not ok
        assert "answer" in reason

    def test_missing_aliases(self) -> None:
        data = _good_puzzle()
        del data["aliases"]
        ok, reason = _validate(data, "country")
        assert not ok
        assert "aliases" in reason

    def test_missing_clues(self) -> None:
        data = _good_puzzle()
        del data["clues"]
        ok, reason = _validate(data, "country")
        assert not ok
        assert "clues" in reason

    def test_missing_explanation(self) -> None:
        data = _good_puzzle()
        del data["explanation"]
        ok, reason = _validate(data, "country")
        assert not ok
        assert "explanation" in reason


class TestValidateAnswer:
    def test_empty_answer(self) -> None:
        data = _good_puzzle()
        data["answer"] = ""
        ok, reason = _validate(data, "country")
        assert not ok

    def test_whitespace_answer(self) -> None:
        data = _good_puzzle()
        data["answer"] = "   "
        ok, reason = _validate(data, "country")
        assert not ok

    def test_too_long_answer(self) -> None:
        data = _good_puzzle()
        # answer 超过 20 字会被拒绝
        data["answer"] = "这是一个特别特别特别特别特别长的答案不止二十字呢呢"
        ok, reason = _validate(data, "country")
        assert not ok
        assert "too long" in reason

    def test_answer_not_string(self) -> None:
        data = _good_puzzle()
        data["answer"] = 123
        ok, _ = _validate(data, "country")
        assert not ok


class TestValidateAliases:
    def test_empty_aliases_list(self) -> None:
        data = _good_puzzle()
        data["aliases"] = []
        ok, reason = _validate(data, "country")
        assert not ok
        assert "aliases" in reason

    def test_aliases_same_as_answer_only(self) -> None:
        # 唯一的别名就是答案本身 → 去重后空，应失败
        data = _good_puzzle()
        data["aliases"] = ["加拿大"]
        ok, reason = _validate(data, "country")
        assert not ok
        assert "aliases" in reason

    def test_aliases_dedup_works(self) -> None:
        # 混合了有效和无效别名，去重后仍有有效项 → 通过
        data = _good_puzzle()
        data["aliases"] = ["加拿大", "Canada", "  加拿大  "]
        ok, reason = _validate(data, "country")
        assert ok
        # 去重后 aliases 只剩 Canada
        assert data["aliases"] == ["Canada"]

    def test_aliases_not_list(self) -> None:
        data = _good_puzzle()
        data["aliases"] = "Canada"  # 不是列表
        ok, _ = _validate(data, "country")
        assert not ok


class TestValidateClues:
    def test_wrong_clue_count_too_few(self) -> None:
        data = _good_puzzle()
        data["clues"] = data["clues"][:3]  # 只有 3 条
        ok, reason = _validate(data, "country")
        assert not ok
        assert "clues" in reason

    def test_wrong_clue_count_too_many(self) -> None:
        data = _good_puzzle()
        data["clues"] = data["clues"] + ["多余的第六条"]
        ok, reason = _validate(data, "country")
        assert not ok

    def test_empty_clue(self) -> None:
        data = _good_puzzle()
        data["clues"][2] = ""
        ok, reason = _validate(data, "country")
        assert not ok
        assert "clue" in reason

    def test_clues_not_list(self) -> None:
        data = _good_puzzle()
        data["clues"] = "一条线索"
        ok, _ = _validate(data, "country")
        assert not ok


class TestValidateAnswerLeakage:
    def test_answer_in_clue_fails(self) -> None:
        data = _good_puzzle()
        data["clues"][0] = "这是一道关于加拿大的题"  # 直接泄露答案
        ok, reason = _validate(data, "country")
        assert not ok
        assert "leaked" in reason

    def test_normalized_answer_in_clue_fails(self) -> None:
        # 带空格/标点的答案也要被检测出
        data = _good_puzzle()
        data["clues"][2] = "这是关于 加-拿-大 的题"
        ok, reason = _validate(data, "country")
        assert not ok

    def test_alias_in_clue_fails(self) -> None:
        # 别名也不能出现在线索里
        data = _good_puzzle()
        data["clues"][1] = "它被称为枫叶国"  # "枫叶国" 是别名，泄露
        ok, reason = _validate(data, "country")
        assert not ok
        assert "leaked" in reason or "alias" in reason

    def test_short_alias_not_false_positive(self) -> None:
        # 单字别名（长度<2）不做泄露检查，避免"A"误伤
        data = _good_puzzle()
        data["aliases"] = ["Canada", "C"]
        # 线索里本身不含 "加拿大"/"Canada"，只是字面有个 C 字母（但 C 是单字别名不做泄露检查）
        data["clues"][2] = "这是一道关于某国国土面积的线索，它位置大致在北半球 C 区域"
        ok, _reason = _validate(data, "country")
        # 单字别名被跳过泄露检查 → 通过
        assert ok


class TestValidateCaseInsensitive:
    def test_uppercase_answer_in_lowercase_clue(self) -> None:
        # 用归一化后子串匹配，大小写不影响泄露检测
        data = _good_puzzle()
        data["answer"] = "USA"
        data["aliases"] = ["美国", "美利坚"]
        data["clues"] = [
            "它 19 世纪经历了一场南北分裂的内战",
            "NBA 的发源地",
            "它由 50 个州组成",
            "华盛顿·哥伦比亚特区是它的首都",
            "位于北美洲大陆中部",
        ]
        ok, _reason = _validate(data, "country")
        assert ok

        # 如果 clue 里冒出 "usa"（小写），也应被发现
        data["clues"][1] = "这是关于 usa 联邦的题"
        ok, reason = _validate(data, "country")
        assert not ok
        assert "leaked" in reason


class TestValidateAvoidDuplicates:
    """v1.1 新增：本局去重 —— avoid_norms 命中答案/别名时判失败。"""

    def test_no_avoid_passes(self) -> None:
        # 没有 avoid 时，正常通过
        ok, _ = _validate(_good_puzzle(), "country", avoid_norms=frozenset())
        assert ok

    def test_answer_in_avoid_fails(self) -> None:
        from src.plugins.games.trivia.answer_matcher import normalize

        avoid = frozenset([normalize("加拿大")])
        ok, reason = _validate(_good_puzzle(), "country", avoid_norms=avoid)
        assert not ok
        assert "duplicate" in reason.lower()

    def test_alias_in_avoid_fails(self) -> None:
        # 答案没重，但其中一个别名（Canada）命中历史禁用集合，仍算重复
        from src.plugins.games.trivia.answer_matcher import normalize

        avoid = frozenset([normalize("Canada")])
        ok, reason = _validate(_good_puzzle(), "country", avoid_norms=avoid)
        assert not ok
        assert "duplicate" in reason.lower()

    def test_normalized_match(self) -> None:
        # 归一化后才能匹配（大小写/空格/标点都不影响）
        from src.plugins.games.trivia.answer_matcher import normalize

        avoid = frozenset([normalize("加-拿-大")])  # 加了横线
        ok, _ = _validate(_good_puzzle(), "country", avoid_norms=avoid)
        assert not ok

    def test_unrelated_avoid_passes(self) -> None:
        # 禁用集合里都是不相关的东西 → 通过
        from src.plugins.games.trivia.answer_matcher import normalize

        avoid = frozenset([normalize("美国"), normalize("日本"), normalize("法国")])
        ok, _ = _validate(_good_puzzle(), "country", avoid_norms=avoid)
        assert ok


class TestBuildHostUserPromptWithAvoid:
    """v1.1 新增：prompt 层把 avoid 展开成禁词列表。"""

    def test_no_avoid_no_extra_text(self) -> None:
        from src.plugins.games.trivia.prompts import build_host_user_prompt

        p = build_host_user_prompt("country", avoid=None)
        assert "严禁" not in p
        # 原样保留
        assert build_host_user_prompt("country") == p

    def test_empty_avoid_no_extra_text(self) -> None:
        from src.plugins.games.trivia.prompts import build_host_user_prompt

        p = build_host_user_prompt("country", avoid=[])
        assert "严禁" not in p

    def test_avoid_list_injected(self) -> None:
        from src.plugins.games.trivia.prompts import build_host_user_prompt

        p = build_host_user_prompt("person", avoid=["孙悟空", "悟空", "齐天大圣"])
        assert "严禁" in p
        assert "孙悟空" in p
        assert "齐天大圣" in p

    def test_avoid_dedup(self) -> None:
        from src.plugins.games.trivia.prompts import build_host_user_prompt

        p = build_host_user_prompt("person", avoid=["孙悟空", "孙悟空", "  孙悟空  "])
        # 只应出现一次（加引号后）
        assert p.count("「孙悟空」") == 1

    def test_avoid_truncated_to_30(self) -> None:
        from src.plugins.games.trivia.prompts import build_host_user_prompt

        avoid = [f"人物{i}" for i in range(50)]
        p = build_host_user_prompt("person", avoid=avoid)
        # 前 30 条在里面
        assert "「人物0」" in p
        assert "「人物29」" in p
        # 第 31 条应被截掉
        assert "「人物30」" not in p


class TestGeneratePuzzleRollingAvoid:
    """v1.3 新增：重试时失败答案自动进 avoid，防止连续挑同款易自泄露答案。

    不调真实 LLM，用 monkeypatch 注入可控响应。
    """

    @pytest.mark.asyncio
    async def test_failed_answer_added_to_avoid_on_retry(self, monkeypatch) -> None:
        from src.plugins.games.trivia import puzzle_generator as pg

        # 记录每次调用时 user prompt 里的内容
        calls: list[str] = []

        class _FakeResp:
            def __init__(self, payload: dict) -> None:
                self._payload = payload

            def json(self) -> dict:
                return self._payload

        # 第 1 次：哈利·波特，线索自泄露 → fail
        # 第 2 次：爱因斯坦，干净 → pass
        responses = [
            {
                "answer": "哈利·波特",
                "aliases": ["Harry Potter"],
                "clues": [
                    "他是《哈利·波特》系列主角",  # 自泄露
                    "他有一道闪电疤痕",
                    "他在霍格沃茨学习魔法",
                    "他的朋友是赫敏和罗恩",
                    "他和伏地魔对抗",
                ],
                "explanation": "J.K. 罗琳笔下的男孩巫师。",
            },
            {
                "answer": "爱因斯坦",
                "aliases": ["Einstein", "阿尔伯特"],
                "clues": [
                    "他提出了改变物理学的理论",
                    "他在瑞士专利局工作过",
                    "他的相对论让时空变得可变",
                    "他因光电效应获诺贝尔奖",
                    "他的头发和吐舌头照片很有名",
                ],
                "explanation": "20 世纪最伟大的物理学家之一。",
            },
        ]
        idx = {"i": 0}

        async def fake_chat(*, messages, scene, json_mode):
            user_msg = next((m.content for m in messages if m.role == "user"), "")
            calls.append(user_msg)
            resp = _FakeResp(responses[idx["i"]])
            idx["i"] += 1
            return resp

        monkeypatch.setattr(pg.llm, "chat", fake_chat)

        puzzle = await pg.generate_puzzle("person", retries=5, avoid=[])

        assert puzzle.answer == "爱因斯坦"
        # 两次调用，第 2 次的 user prompt 已经注入了失败答案
        assert len(calls) == 2
        assert "哈利·波特" in calls[1]
        # 第 1 次还不知道要避
        assert "哈利·波特" not in calls[0]

