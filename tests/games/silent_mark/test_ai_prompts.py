"""AI 提示词（`ai/prompts.py`）。

这些文案是从源项目**逐字移植**的资产，测试主要锁两件容易出事的事：

1. **提示里绝不能出现规则层会拒绝的选项** —— 源项目踩过这个坑（给守卫提供了"跳过"，
   而规则层要求守卫必选；守墓人反之只在无死者时才允许跳过）。
2. 模板占位符不能有漏（``$`` 残留 = 提示里会出现莫名其妙的符号）。
"""

from __future__ import annotations

from src.plugins.games.silent_mark.ai import prompts
from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812

WIN = C.WIN_EDGE


def test_system_prompt_carries_seat_role_and_faction() -> None:
    text = prompts.system_prompt(seat=3, role=C.SEER, faction=C.GOOD, win_condition=WIN)

    assert "你是3号玩家。" in text
    assert '你的身份是"预言家"，属于好人阵营。' in text
    assert "【预言家策略指导】" in text
    assert "屠边" in text
    assert "$" not in text


def test_wolf_system_prompt_gets_wolf_strategy_and_never_sees_wolf_win_mixup() -> None:
    text = prompts.system_prompt(
        seat=1, role=C.WOLF_KING, faction=C.EVIL, win_condition=C.WIN_CITY
    )

    assert "【狼人阵营策略指导】" in text
    assert "【白狼王特殊策略】" in text
    assert "屠城" in text
    # 狼人提示里绝不能出现"所有好人被淘汰"以外的屠边口径
    assert "屠边" not in text
    assert "$" not in text


def test_guard_prompt_never_offers_a_skip() -> None:
    """守卫是**必选**：提示里不能出现"跳过/返回 null"这类选项（源项目踩过）。"""
    text = prompts.night_action_prompt(role=C.GUARD, targets=[2, 3])

    assert "必须选择一名目标" in text
    assert "target" in text
    assert "skip" not in text
    assert "target\": null" not in text


def test_gravedigger_may_skip_only_when_there_is_no_corpse() -> None:
    with_corpse = prompts.night_action_prompt(role=C.GRAVEDIGGER, targets=[5])
    without = prompts.night_action_prompt(role=C.GRAVEDIGGER, targets=[])

    assert "target\": null" not in with_corpse
    assert "target\": null" in without


def test_witch_prompt_without_potions_declares_auto_skip() -> None:
    text = prompts.night_action_prompt(
        role=C.WITCH,
        targets=[2, 3],
        witch_info={"has_antidote": False, "has_poison": False},
    )

    assert "你没有药可以使用，将自动跳过。" in text
    assert '"potion": "none"' in text


def test_witch_prompt_with_potions_describes_the_killed_and_choices() -> None:
    text = prompts.night_action_prompt(
        role=C.WITCH,
        targets=[2, 3],
        witch_info={
            "victim_seat": 4,
            "has_antidote": True,
            "has_poison": True,
            "can_self_save": False,
        },
    )

    assert "今夜被刀的是：4号玩家" in text
    assert "不能自救" in text
    assert '"potion": "antidote"' in text and '"potion": "poison"' in text


def test_wolf_night_prompt_lists_targets_as_seats() -> None:
    text = prompts.night_action_prompt(role=C.WEREWOLF, targets=[2, 4])

    assert "可选目标：2号玩家、4号玩家" in text
    assert "$" not in text


def test_marking_prompt_states_slots_reasons_and_identities() -> None:
    text = prompts.marking_prompt(
        evaluation_mark_count=2,
        available_identities=["预言家", "平民"],
        targets=[2, 3],
        available_reasons=["直觉判断", "查验结论"],
        analysis_preference="你更擅长从标记发言内容中找矛盾。",
    )

    assert "评价 2 名其他存活玩家" in text
    assert "可选身份：预言家、平民" in text
    assert "评价身份选项：预言家、平民、狼人" in text
    assert "你的分析偏好：你更擅长从标记发言内容中找矛盾。" in text
    # 狼人不得自曝：这条约束必须在标记提示里（狼人也拿这份提示）
    assert "绝对不能声称" in text
    assert "$" not in text


def test_voting_prompt_tells_the_ai_it_is_not_a_candidate() -> None:
    text = prompts.voting_prompt(candidates=[2, 3], self_seat=1)

    assert "候选人：2号玩家、3号玩家" in text
    assert "你是1号玩家，候选人列表中没有你自己" in text
    assert "$" not in text


def test_voting_prompt_falls_back_to_default_preference() -> None:
    text = prompts.voting_prompt(candidates=[2, 3])

    assert "综合考虑标记内容、投票行为与死亡线索" in text


def test_hunter_prompt_cannot_shoot_when_poisoned() -> None:
    assert "无法开枪" in prompts.hunter_prompt(can_shoot=False, targets=[2])
    assert "开枪" in prompts.hunter_prompt(can_shoot=True, targets=[2])


def test_trigger_prompts_carry_their_actions() -> None:
    knight = prompts.knight_prompt(targets=[2])
    king = prompts.wolf_king_prompt(targets=[2])

    assert '"action": "duel"' in knight
    assert '"action": "drag"' in king
    assert "$" not in knight and "$" not in king
