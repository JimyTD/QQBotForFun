"""玩家输入语法（解析 / 渲染）。

这是 CLI 与 Bot 共用的唯一输入层，测试要覆盖：全部合法写法、常见错写、
以及"语法层产物一定能过语义校验"的跨层契约。
"""

from __future__ import annotations

import pytest

from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812
from src.plugins.games.silent_mark.engine.resolve import validate_player_marks
from src.plugins.games.silent_mark.syntax import (
    normalize_identity,
    normalize_reason,
    parse_marks,
    parse_seat,
    parse_target,
    parse_witch_action,
    player_label,
    render_mark_prompt,
    render_marks_line,
    render_target_prompt,
    render_witch_prompt,
    tokenize,
)

from .factories import make_player, make_state


def _board() -> dict:
    """4 人局：平民 / 预言家 / 狼人 / 守卫（覆盖"动态身份选项"）。"""
    players = [
        make_player("p1", C.VILLAGER),
        make_player("p2", C.SEER),
        make_player("p3", C.WEREWOLF),
        make_player("p4", C.GUARD),
    ]
    return make_state(players, phase=C.PHASE_DAY_MARKING, marking_order=["p1", "p2", "p3", "p4"])


# =====================================================================
# 归一化与分词
# =====================================================================
@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("好人", "好人"),
        ("神职", "神职"),
        ("神", "神职"),
        ("预言家", "预言家"),
        ("民", "平民"),
        ("狼", "狼人"),
        ("狼人", "狼人"),
        ("不存在", None),
        ("", None),
    ],
)
def test_normalize_identity(token, expected):
    assert normalize_identity(token) == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("直觉判断", C.REASON_INTUITION),
        ("直觉", C.REASON_INTUITION),
        ("intuition", C.REASON_INTUITION),
        ("标记分析", C.REASON_MARK_ANALYSIS),
        ("查验结论", C.REASON_INVESTIGATION),
        ("investigation", C.REASON_INVESTIGATION),
        ("INTUITION", C.REASON_INTUITION),
        ("瞎猜", None),
    ],
)
def test_normalize_reason(token, expected):
    assert normalize_reason(token) == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [("3", 3), ("3号", 3), ("@3", 3), ("＠3号", 3), ("P3", 3), ("#3位", 3), ("三", None), ("x", None)],
)
def test_parse_seat(token, expected):
    assert parse_seat(token) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3", ["3"]),
        ("3号", ["3号"]),
        ("毒3", ["毒", "3"]),  # 玩家很自然会这么打
        ("查 3号", ["查", "3号"]),
        ("好人, 直觉判断", ["好人", "直觉判断"]),
        ("好人、直觉判断", ["好人", "直觉判断"]),
    ],
)
def test_tokenize(text, expected):
    assert tokenize(text) == expected


# =====================================================================
# 单目标解析（夜间行动 / 投票）
# =====================================================================
def test_parse_target_accepts_common_writings():
    state = _board()
    for text in ("2", "2号", "@2", "查 2", "查验2号"):
        result = parse_target(text, state)
        assert result.ok, text
        assert result.pid == "p2"


def test_parse_target_maps_seat_to_pid_not_pid_text():
    """座位 3 是 p3——确认映射用的是座位号而不是下标。"""
    state = _board()
    assert parse_target("3", state).pid == "p3"
    assert parse_target("1", state).pid == "p1"


def test_parse_target_skip_tokens():
    state = _board()
    for text in ("跳过", "过", "pass", "skip", "不用"):
        result = parse_target(text, state)
        assert result.ok, text
        assert result.skipped is True
        assert result.pid is None


def test_parse_target_rejects_unknown_seat_and_garbage():
    state = _board()
    assert "没有 9 号座位" in parse_target("9", state).problems[0]
    assert "看不懂目标" in parse_target("小红", state).problems[0]
    assert "没有识别到内容" in parse_target("", state).problems[0]


def test_parse_target_rejects_multiple_targets():
    state = _board()
    result = parse_target("2 3", state)
    assert not result.ok
    assert "只能指定一个目标" in result.problems[0]


def test_parse_target_respects_allowed_pids():
    state = _board()
    assert parse_target("3", state, allowed_pids=["p1", "p2"]).ok is False
    assert "不在本次可选范围" in parse_target("3", state, allowed_pids=["p1", "p2"]).problems[0]
    assert parse_target("2", state, allowed_pids=["p1", "p2"]).pid == "p2"


# =====================================================================
# 女巫用药解析
# =====================================================================
def test_parse_witch_antidote():
    state = _board()
    for text in ("救", "解药", "救药", "antidote"):
        result = parse_witch_action(text, state)
        assert result.ok, text
        assert result.potion == "antidote"
        assert result.target is None


def test_parse_witch_poison_with_target():
    state = _board()
    for text in ("毒 3", "毒3", "毒药 3号", "poison 3"):
        result = parse_witch_action(text, state)
        assert result.ok, text
        assert result.potion == "poison"
        assert result.target == "p3"


def test_parse_witch_none():
    state = _board()
    for text in ("不用", "不用药", "不救", "跳过", "none"):
        result = parse_witch_action(text, state)
        assert result.ok, text
        assert result.potion == "none"


def test_parse_witch_poison_without_target_is_rejected():
    state = _board()
    result = parse_witch_action("毒", state)
    assert not result.ok
    assert "毒谁" in result.problems[0]


def test_parse_witch_garbage_is_rejected():
    state = _board()
    result = parse_witch_action("随便", state)
    assert not result.ok
    assert "看不懂" in result.problems[0]


# =====================================================================
# 标记解析
# =====================================================================
def test_parse_full_marks():
    state = _board()
    result = parse_marks("好人 直觉判断 | 2号 狼人 标记分析 | 3号 好人 直觉判断", state, "p1")

    assert result.ok
    assert result.marks is not None
    assert result.marks["player"] == "p1"
    assert result.marks["round"] == 1
    assert result.marks["identity_mark"] == {
        "identity": "好人",
        "reason": C.REASON_INTUITION,
    }
    assert result.marks["evaluation_marks"] == [
        {"target": "p2", "identity": "狼人", "reason": C.REASON_MARK_ANALYSIS},
        {"target": "p3", "identity": "好人", "reason": C.REASON_INTUITION},
    ]


def test_parse_marks_tolerates_command_word_and_fullwidth_separator():
    state = _board()
    result = parse_marks("标记 好人 直觉判断｜2号 狼人｜3号 好人", state, "p1")

    assert result.ok
    assert len(result.marks["evaluation_marks"]) == 2  # type: ignore[index]


def test_parse_marks_reason_can_be_omitted():
    """理由可省略，默认「直觉判断」——降低输入门槛。"""
    state = _board()
    result = parse_marks("好人 | 2号 狼人 | 3号", state, "p1")

    assert result.ok
    assert result.marks["identity_mark"]["reason"] == C.REASON_INTUITION  # type: ignore[index]
    marks = result.marks["evaluation_marks"]  # type: ignore[index]
    assert [m["reason"] for m in marks] == [C.REASON_INTUITION, C.REASON_INTUITION]
    assert [m["identity"] for m in marks] == ["狼人", "好人"]


def test_parse_marks_uses_english_reason_key():
    state = _board()
    result = parse_marks("好人 intuition | 2号 狼人 vote_analysis", state, "p1")

    assert result.ok
    assert result.marks["evaluation_marks"][0]["reason"] == C.REASON_VOTE_ANALYSIS  # type: ignore[index]


@pytest.mark.parametrize("text", ["", "标记", "发言", "help", "?"])
def test_parse_marks_asks_for_guidance_when_bare(text):
    state = _board()
    result = parse_marks(text, state, "p1")
    assert result.needs_guide is True
    assert result.marks is None


def test_parse_marks_requires_at_least_one_evaluation():
    state = _board()
    result = parse_marks("好人 直觉判断", state, "p1")
    assert not result.ok
    assert "至少要评价 1 名其他玩家" in result.problems[0]


def test_parse_marks_hints_about_missing_separator():
    """最常见的错写：忘了「|」。提示必须直接告诉他怎么改。"""
    state = _board()
    result = parse_marks("标记 好人 直觉判断 2号 狼人", state, "p1")
    assert not result.ok
    assert any("要用「|」分隔" in p for p in result.problems)


def test_parse_marks_rejects_unknown_identity_and_reason():
    state = _board()
    bad_identity = parse_marks("龙人 | 2号 狼人", state, "p1")
    assert not bad_identity.ok
    assert "看不懂身份「龙人」" in bad_identity.problems[0]

    bad_reason = parse_marks("好人 瞎猜 | 2号 狼人", state, "p1")
    assert not bad_reason.ok
    assert "看不懂理由「瞎猜」" in bad_reason.problems[0]


def test_parse_marks_rejects_bad_targets():
    state = _board()
    assert "没有 9 号座位" in parse_marks("好人 | 9号 狼人", state, "p1").problems[0]
    assert "不能评价自己" in parse_marks("好人 | 1号 狼人", state, "p1").problems[0]
    assert "被评价了两次" in parse_marks("好人 | 2号 狼人 | 2号 好人", state, "p1").problems[0]
    assert "看不懂评价目标" in parse_marks("好人 | 小红 狼人", state, "p1").problems[0]


def test_parse_marks_collects_all_problems_at_once():
    """一次把问题列全，而不是只报第一个——玩家少来回几轮。"""
    state = _board()
    result = parse_marks("好人 | 9号 狼人 | 1号 好人 | 龙人", state, "p1")
    assert len(result.problems) >= 3


def test_parse_marks_rejects_dead_target():
    state = _board()
    state["players"][1]["alive"] = False  # p2 出局
    result = parse_marks("好人 | 2号 狼人", state, "p1")
    assert not result.ok
    assert any("已出局" in p for p in result.problems)


def test_parse_marks_allows_zero_evaluations_when_nobody_else_is_alive():
    """残局（只剩自己）不应该被"至少评价 1 人"卡死。"""
    state = make_state(
        [make_player("p1", C.VILLAGER)],
        phase=C.PHASE_DAY_MARKING,
        marking_order=["p1"],
    )
    result = parse_marks("好人", state, "p1")
    assert result.ok
    assert result.marks["evaluation_marks"] == []  # type: ignore[index]


def test_parsed_marks_pass_semantic_validation():
    """跨层契约：语法层接受的产物，必须能过语义校验（否则玩家会陷入死循环）。

    注意语法层更严（要求至少 1 个评价），语义层更松（源项目口径）——
    这个方向是安全的：语法层放行的东西语义层一定也放行。
    """
    state = _board()
    for text in (
        "好人 直觉判断 | 2号 狼人 标记分析 | 3号 好人 直觉判断",
        "预言家 查验结论 | 2号 好人 查验结论",
        "标记 守卫 | 3号 狼人",
        "神职 | 2号 好人 | 4号 好人",
    ):
        result = parse_marks(text, state, "p1")
        assert result.ok, (text, result.problems)
        assert validate_player_marks(state, "p1", result.marks) == [], text


# =====================================================================
# 渲染
# =====================================================================
def test_render_mark_prompt_contains_everything_needed():
    """提示必须"短但够用"：词表、格式、例子、存活名单都要有。

    长度也是一条硬约束——这条提示每轮都要发一遍（虽然群里只留一条），
    冗长的说明会把群刷爆。
    """
    state = _board()
    text = render_mark_prompt(state, "p1")

    assert "1号 p1" in text
    assert "身份：" in text and "评价：" in text
    assert "直觉判断" in text and "查验结论" in text
    assert "格式：" in text
    assert "2号 p2" in text and "3号 p3" in text  # 存活玩家列表（不含自己）
    assert "1号 p1、" not in text  # 自己不在"存活玩家"列表里
    assert len(text.splitlines()) <= 7, f"标记提示太长了（{len(text.splitlines())} 行）"


def test_render_mark_prompt_hint_only_appears_first_time():
    """引导提示只在开局第一次出现，之后不再唠叨。"""
    state = _board()

    assert "私聊里带你" in render_mark_prompt(state, "p1", first_time=True)
    assert "私聊里带你" not in render_mark_prompt(state, "p1")


def test_render_target_prompt_lists_options_and_skip():
    state = _board()
    text = render_target_prompt(state, "p1", "guard", allowed_pids=["p2", "p3"], allow_skip=True)

    assert "守护目标" in text
    assert "2号 p2" in text and "3号 p3" in text
    assert "跳过" in text
    assert "4号 p4" not in text


def test_render_target_prompt_without_skip_does_not_mention_it():
    state = _board()
    text = render_target_prompt(state, "p1", "vote", allowed_pids=["p2"])
    assert "跳过" not in text


def test_render_witch_prompt_shows_victim_and_potion_state():
    state = _board()
    text = render_witch_prompt(state, "p1", victim_pid="p3")

    assert "3号 p3" in text
    assert "解药：未使用" in text and "毒药：未使用" in text
    assert "毒 3" in text


def test_render_witch_prompt_handles_no_victim_and_used_potions():
    state = _board()
    state["players"][0]["role_state"] = {"antidote_used": True, "poison_used": True}
    text = render_witch_prompt(state, "p1", victim_pid=None)

    assert "无人被袭击" in text
    assert "解药：已用完" in text and "毒药：已用完" in text
    assert "两瓶药都已用完" in text


def test_render_marks_line_is_public_and_uses_labels():
    state = _board()
    result = parse_marks("好人 直觉判断 | 3号 狼人 标记分析", state, "p1")
    text = render_marks_line(state, result.marks)  # type: ignore[arg-type]

    assert "1号 p1 声明身份：好人（直觉判断）" in text
    assert "认为 3号 p3 是 狼人（标记分析）" in text


def test_player_label_falls_back_to_pid():
    state = _board()
    assert player_label(state, "p1") == "1号 p1"
    assert player_label(state, "ghost") == "ghost"
