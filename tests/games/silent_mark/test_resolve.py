"""结算与校验：夜晚 / 投票 / 胜负 / 标记 / 物品。

对应源项目 ``server/game/rules.ts``。
"""

from __future__ import annotations

import pytest

from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812
from src.plugins.games.silent_mark.engine.resolve import (
    assign_items,
    calculate_balance_badges,
    check_win_condition,
    get_available_eval_identities,
    get_available_identities,
    get_evaluation_mark_count,
    resolve_night,
    resolve_voting,
    validate_player_marks,
)

from .factories import make_item, make_night, make_player, make_state


class _FixedRng:
    """确定性随机源，避免测试依赖 Python 内部随机实现。"""

    def __init__(self, pick: str) -> None:
        self._pick = pick

    def choice(self, seq):
        return self._pick


# =====================================================================
# 夜晚结算
# =====================================================================
def test_wolf_kill():
    wolf = make_player("wolf", C.WEREWOLF)
    victim = make_player("v", C.VILLAGER)
    state = make_state([wolf, victim], night_actions=make_night(wolves_target="v"))

    deaths = resolve_night(state)

    assert [d["pid"] for d in deaths] == ["v"]
    assert deaths[0]["cause"] == C.DEATH_ATTACKED
    assert deaths[0]["round"] == 1
    assert victim["alive"] is False


def test_guard_blocks_the_kill():
    guard = make_player("guard", C.GUARD)
    victim = make_player("v", C.VILLAGER)
    state = make_state(
        [guard, victim], night_actions=make_night(wolves_target="v", guard_target="v")
    )

    assert resolve_night(state) == []
    assert victim["alive"] is True


def test_antidote_saves_the_victim():
    witch = make_player("witch", C.WITCH)
    victim = make_player("v", C.VILLAGER)
    state = make_state(
        [witch, victim],
        night_actions=make_night(wolves_target="v", witch_action="antidote", witch_target="v"),
    )

    assert resolve_night(state) == []
    assert victim["alive"] is True


def test_guard_witch_clash_kills_the_victim_exactly_once():
    """同守同救 → 同归于尽。

    ⚠️ 与源项目的**有意差异**：源项目会为同一玩家记两条死亡记录
    （guardWitchClash + attacked，第一个 if 漏写 else），导致重复公告、
    重复进入死亡触发链。这里按设计文档只记一条。
    本测试就是防止这个修正被回退。
    """
    guard = make_player("guard", C.GUARD)
    witch = make_player("witch", C.WITCH)
    victim = make_player("v", C.VILLAGER)
    state = make_state(
        [guard, witch, victim],
        night_actions=make_night(
            wolves_target="v", guard_target="v", witch_action="antidote", witch_target="v"
        ),
    )

    deaths = resolve_night(state)

    assert len(deaths) == 1
    assert deaths[0]["pid"] == "v"
    assert deaths[0]["cause"] == C.DEATH_GUARD_WITCH_CLASH
    assert victim["alive"] is False


def test_poison_ignores_guard_and_antidote_is_not_involved():
    witch = make_player("witch", C.WITCH)
    target = make_player("t", C.VILLAGER)
    state = make_state(
        [witch, target],
        night_actions=make_night(witch_action="poison", witch_target="t"),
    )

    deaths = resolve_night(state)

    assert [d["pid"] for d in deaths] == ["t"]
    assert deaths[0]["cause"] == C.DEATH_POISONED


def test_poison_does_not_duplicate_a_player_already_dying():
    wolf = make_player("wolf", C.WEREWOLF)
    witch = make_player("witch", C.WITCH)
    victim = make_player("v", C.VILLAGER)
    state = make_state(
        [wolf, witch, victim],
        night_actions=make_night(
            wolves_target="v", witch_action="poison", witch_target="v"
        ),
    )

    deaths = resolve_night(state)

    assert len(deaths) == 1
    assert deaths[0]["cause"] == C.DEATH_ATTACKED


def test_relics_are_revealed_on_death():
    victim = make_player("v", C.VILLAGER, items=[make_item(C.MOONSTONE, 0)])
    wolf = make_player("wolf", C.WEREWOLF)
    state = make_state([wolf, victim], night_actions=make_night(wolves_target="v"))

    deaths = resolve_night(state)

    assert victim["items"][0]["revealed"] is True
    assert deaths[0]["relics"][0]["type"] == C.MOONSTONE


def test_resolve_night_does_not_touch_history():
    """契约：resolve_night 只结算并就地执行死亡，历史由调用方（状态机）写入。"""
    victim = make_player("v", C.VILLAGER)
    wolf = make_player("wolf", C.WEREWOLF)
    state = make_state([wolf, victim], night_actions=make_night(wolves_target="v"))

    resolve_night(state)

    assert state["history"]["deaths"] == []
    assert state["history"]["rounds"] == []


# =====================================================================
# 月光石
# =====================================================================
def test_moonstone_counts_once_per_night_even_with_multiple_visits():
    """被刀 + 被查验 同一夜只 +1（源项目用集合去重，与设计文档措辞不同）。"""
    target = make_player("t", C.VILLAGER, items=[make_item(C.MOONSTONE, 0)])
    wolf = make_player("wolf", C.WEREWOLF)
    seer = make_player("seer", C.SEER)
    state = make_state(
        [wolf, seer, target],
        night_actions=make_night(wolves_target="t", seer_target="t"),
    )

    resolve_night(state)

    assert target["items"][0]["value"] == 1


def test_moonstone_is_updated_before_death_so_the_relic_has_this_nights_count():
    target = make_player("t", C.VILLAGER, items=[make_item(C.MOONSTONE, 0)])
    wolf = make_player("wolf", C.WEREWOLF)
    state = make_state([wolf, target], night_actions=make_night(wolves_target="t"))

    deaths = resolve_night(state)

    assert deaths[0]["relics"][0]["value"] == 1
    assert target["items"][0]["value"] == 1


def test_moonstone_untouched_when_not_visited():
    idle = make_player("idle", C.VILLAGER, items=[make_item(C.MOONSTONE, 0)])
    wolf = make_player("wolf", C.WEREWOLF)
    victim = make_player("v", C.VILLAGER)
    state = make_state([wolf, victim, idle], night_actions=make_night(wolves_target="v"))

    resolve_night(state)

    assert idle["items"][0]["value"] == 0


# =====================================================================
# 天平徽章
# =====================================================================
def test_balance_badge_compares_ring_neighbours_and_ignores_death():
    p1 = make_player("p1", C.VILLAGER, seat=1, items=[make_item(C.BALANCE)])
    p2 = make_player("p2", C.WEREWOLF, seat=2, items=[make_item(C.BALANCE)])
    p3 = make_player("p3", C.VILLAGER, seat=3, items=[make_item(C.BALANCE)])
    p4 = make_player("p4", C.VILLAGER, seat=4, items=[make_item(C.BALANCE)])
    players = [p1, p2, p3, p4]

    calculate_balance_badges(players)
    values = {p["pid"]: p["items"][0]["value"] for p in players}
    assert values == {
        "p1": "unbalanced",  # 左 p4(好) 右 p2(狼)
        "p2": "balanced",  # 左 p1(好) 右 p3(好)
        "p3": "unbalanced",  # 左 p2(狼) 右 p4(好)
        "p4": "balanced",  # 左 p3(好) 右 p1(好)
    }

    # 以原始座位计算，不随邻座死亡变化
    p4["alive"] = False
    p1["items"][0]["value"] = ""
    calculate_balance_badges(players)
    assert p1["items"][0]["value"] == "unbalanced"


def test_balance_badge_ignores_players_without_the_item():
    p1 = make_player("p1", C.VILLAGER, seat=1, items=[make_item(C.MOONSTONE, 0)])
    p2 = make_player("p2", C.WEREWOLF, seat=2, items=[make_item(C.BALANCE)])
    calculate_balance_badges([p1, p2])

    assert p1["items"][0]["value"] == 0
    assert p2["items"][0]["value"] == "balanced"


# =====================================================================
# 物品分配
# =====================================================================
def test_assign_items_disabled_returns_nothing():
    settings = {"items": {"enabled": False, "pool": [C.MOONSTONE]}}
    assert assign_items(settings) == []


def test_assign_items_moonstone_starts_at_zero_and_hidden():
    settings = {"items": {"enabled": True, "pool": [C.MOONSTONE]}}
    items = assign_items(settings, _FixedRng(C.MOONSTONE))

    assert items == [{"type": C.MOONSTONE, "value": 0, "revealed": False}]


def test_assign_items_balance_has_no_numeric_value_yet():
    settings = {"items": {"enabled": True, "pool": [C.BALANCE]}}
    items = assign_items(settings, _FixedRng(C.BALANCE))

    assert items == [{"type": C.BALANCE, "value": "", "revealed": False}]


def test_assign_items_defaults_to_basic_pool():
    items = assign_items({"items": {"enabled": True}})
    assert len(items) == 1
    assert items[0]["type"] in C.BASIC_ITEM_POOL


def test_assign_items_empty_pool_returns_nothing():
    assert assign_items({"items": {"enabled": True, "pool": []}}) == []


# =====================================================================
# 投票结算
# =====================================================================
def _votes(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"voter": voter, "target": target} for voter, target in pairs]


def test_voting_exiles_the_top_candidate():
    result = resolve_voting(_votes(("a", "x"), ("b", "x"), ("c", "y")))
    assert result == {"exiled": "x", "tie": False}


def test_voting_tie_exiles_nobody():
    result = resolve_voting(_votes(("a", "x"), ("b", "y")))
    assert result == {"exiled": None, "tie": True}


def test_voting_without_votes():
    assert resolve_voting([]) == {"exiled": None, "tie": False}


# =====================================================================
# 胜负判定
# =====================================================================
def _win_state(*players):
    return make_state(list(players))


def test_good_wins_when_all_wolves_are_gone():
    state = _win_state(make_player("v", C.VILLAGER), make_player("s", C.SEER))
    assert check_win_condition(state) == {
        "winner": C.GOOD,
        "reason": "wolves_eliminated",
    }


def test_evil_wins_by_eliminating_all_specials():
    state = _win_state(
        make_player("wolf", C.WEREWOLF),
        make_player("v", C.VILLAGER),
        make_player("s", C.SEER, alive=False),
    )
    assert check_win_condition(state) == {
        "winner": C.EVIL,
        "reason": "specials_eliminated",
    }


def test_evil_wins_by_eliminating_all_villagers():
    state = _win_state(
        make_player("wolf", C.WEREWOLF),
        make_player("s", C.SEER),
        make_player("v", C.VILLAGER, alive=False),
    )
    assert check_win_condition(state) == {
        "winner": C.EVIL,
        "reason": "villagers_eliminated",
    }


def test_game_continues_when_both_sides_still_have_players():
    state = _win_state(
        make_player("wolf", C.WEREWOLF),
        make_player("s", C.SEER),
        make_player("v", C.VILLAGER),
    )
    assert check_win_condition(state) is None


def test_city_mode_requires_every_good_player_dead():
    players = [make_player("wolf", C.WEREWOLF), make_player("v", C.VILLAGER, alive=False)]
    state = make_state(players, win_condition=C.WIN_CITY)
    assert check_win_condition(state, C.WIN_CITY) == {
        "winner": C.EVIL,
        "reason": "good_eliminated",
    }


def test_city_mode_still_lets_good_win_by_killing_all_wolves():
    state = make_state([make_player("v", C.VILLAGER)], win_condition=C.WIN_CITY)
    assert check_win_condition(state, C.WIN_CITY) == {
        "winner": C.GOOD,
        "reason": "wolves_eliminated",
    }


def test_edge_board_without_specials_does_not_hand_evil_an_instant_win():
    """屠边 + 板子里没有神职 → 「神职全灭」不成立，不能开局即判狼胜。

    源项目 502ef26 同步修正：修正前 `1 狼 + 3 平民 + 屠边` 会在首夜结算后
    立刻判狼人胜（甚至无人死亡），文案还是"神职被淘汰"。
    """
    state = _win_state(
        make_player("wolf", C.WEREWOLF),
        *(make_player(f"v{i}", C.VILLAGER) for i in range(3)),
    )
    assert check_win_condition(state) is None


def test_edge_mode_all_good_dead_still_ends_the_game():
    """防死局：屠边模式下「好人全灭」也必须结束对局。

    若不把"所有好人出局"从屠城分支里提出来，这种情况会两个屠边条件都不满足
    而返回 None —— 场上只剩狼却不结束，是真正的死局。
    这一步是源项目 502ef26 新补的，两边一致。
    """
    state = _win_state(
        make_player("wolf", C.WEREWOLF),
        make_player("s", C.SEER, alive=False),
        make_player("v", C.VILLAGER, alive=False),
    )
    assert check_win_condition(state) == {
        "winner": C.EVIL,
        "reason": "good_eliminated",
    }


def test_good_wins_when_both_sides_are_wiped_in_the_same_resolution():
    """同轮双方全灭 → **好人优先**（判定顺序：狼全灭 → 好人全灭）。

    这个顺序与源项目 502ef26 的最终形态一致（两边都把"狼全灭"放在最前）。
    顺序若反过来，同轮全灭的结论会从好人胜变成狼人胜——这是一条会被用户直接看到的差异。
    """
    players = [
        make_player("wolf", C.WEREWOLF, alive=False),
        make_player("s", C.SEER, alive=False),
        make_player("v", C.VILLAGER, alive=False),
    ]
    state = _win_state(*players)
    assert check_win_condition(state) == {
        "winner": C.GOOD,
        "reason": "wolves_eliminated",
    }
    # 屠城模式同样好人优先
    assert check_win_condition(state, C.WIN_CITY) == {
        "winner": C.GOOD,
        "reason": "wolves_eliminated",
    }


def test_win_reason_strings_are_stable():
    """reason 是**跨实现标识符**（源项目已按这四个字符串对齐），改名等于破坏对齐。"""
    assert (
        check_win_condition(_win_state(make_player("v", C.VILLAGER)))["reason"]
        == "wolves_eliminated"
    )
    assert (
        check_win_condition(
            _win_state(
                make_player("wolf", C.WEREWOLF),
                make_player("s", C.SEER, alive=False),
                make_player("v", C.VILLAGER, alive=False),
            )
        )["reason"]
        == "good_eliminated"
    )
    assert (
        check_win_condition(
            _win_state(
                make_player("wolf", C.WEREWOLF),
                make_player("v", C.VILLAGER),
                make_player("s", C.SEER, alive=False),
            )
        )["reason"]
        == "specials_eliminated"
    )
    assert (
        check_win_condition(
            _win_state(
                make_player("wolf", C.WEREWOLF),
                make_player("s", C.SEER),
                make_player("v", C.VILLAGER, alive=False),
            )
        )["reason"]
        == "villagers_eliminated"
    )


# =====================================================================
# 标记：数量 / 选项 / 合法性
# =====================================================================
@pytest.mark.parametrize(
    ("alive", "expected"),
    [(4, 2), (6, 2), (7, 3), (9, 3), (10, 4), (12, 4)],
)
def test_evaluation_mark_count_by_alive_players(alive, expected):
    assert get_evaluation_mark_count(alive) == expected


def test_identity_options_are_dynamic_to_the_board():
    state = make_state(
        [
            make_player("wolf", C.WEREWOLF),
            make_player("guard", C.GUARD),
            make_player("witch", C.WITCH),
            make_player("v", C.VILLAGER),
        ]
    )
    # 固定两项 + 当局实际存在的职业（顺序与源项目一致）
    assert get_available_identities(state) == ["神职", "好人", "女巫", "守卫", "平民"]
    assert get_available_eval_identities(state) == [
        "神职",
        "好人",
        "女巫",
        "守卫",
        "平民",
        "狼人",
    ]


def test_identity_options_exclude_roles_not_in_the_board():
    state = make_state([make_player("v", C.VILLAGER), make_player("w", C.WEREWOLF)])
    identities = get_available_identities(state)
    assert "守卫" not in identities
    assert "预言家" not in identities


def test_ambiguous_god_claim_is_always_available():
    """「神职」「好人」是固定选项，**始终**可选（源项目确认的设计）。

    所以板子里没有神职时，玩家仍可声称"神职"这种模糊说法；
    被限制的只是"预言家"这类**具体且当局不存在**的职业。
    这条细节容易在重构中被误删，锁住它。
    """
    state = make_state([make_player("w", C.WEREWOLF), make_player("v", C.VILLAGER)])
    identities = get_available_identities(state)

    assert "神职" in identities
    assert "好人" in identities
    assert identities[:2] == ["神职", "好人"]  # 固定项永远排在最前


def _marking_state(*, alive_count: int = 4, current: int = 0):
    roles = [C.VILLAGER] * alive_count
    players = [make_player(f"p{i}", role) for i, role in enumerate(roles, start=1)]
    return make_state(
        players,
        phase=C.PHASE_DAY_MARKING,
        marking_order=[p["pid"] for p in players],
        marking_current=current,
    )


def _marks(identity: str, reason: str, evaluations: list[tuple[str, str, str]], pid: str = "p1"):
    return {
        "player": pid,
        "round": 1,
        "identity_mark": {"identity": identity, "reason": reason},
        "evaluation_marks": [
            {"target": target, "identity": mark_identity, "reason": mark_reason}
            for target, mark_identity, mark_reason in evaluations
        ],
    }


def test_valid_marks_pass():
    state = _marking_state(alive_count=4)
    problems = validate_player_marks(
        state,
        "p1",
        _marks(
            "好人",
            C.REASON_INTUITION,
            [("p2", "狼人", C.REASON_MARK_ANALYSIS), ("p3", "好人", C.REASON_INTUITION)],
        ),
    )
    assert problems == []


def test_fewer_than_max_evaluation_marks_is_allowed():
    """源项目只禁止"超过"上限（AI/兜底可能产生更少的评价）。"""
    state = _marking_state(alive_count=4)
    problems = validate_player_marks(
        state, "p1", _marks("好人", C.REASON_INTUITION, [("p2", "好人", C.REASON_INTUITION)])
    )
    assert problems == []


def test_marks_rejected_outside_marking_phase():
    state = _marking_state()
    state["phase"] = C.PHASE_NIGHT
    problems = validate_player_marks(state, "p1", _marks("好人", C.REASON_INTUITION, []))
    assert problems and "不是标记阶段" in problems[0]


def test_marks_rejected_when_it_is_not_your_turn():
    state = _marking_state(current=1)
    problems = validate_player_marks(state, "p1", _marks("好人", C.REASON_INTUITION, []))
    assert problems and "还没轮到你" in problems[0]


def test_marks_rejected_when_identity_is_not_available():
    state = _marking_state(alive_count=4)
    problems = validate_player_marks(
        state, "p1", _marks("女巫", C.REASON_INTUITION, [])  # 局里没有女巫
    )
    assert any("不在可选范围" in p for p in problems)


def test_marks_rejected_when_reason_does_not_match_claimed_identity():
    state = _marking_state(alive_count=4)
    problems = validate_player_marks(
        state, "p1", _marks("好人", C.REASON_INVESTIGATION, [])
    )
    assert any("不能用于你声明的身份" in p for p in problems)


def test_marks_allow_investigation_reason_when_claiming_an_identity_on_the_board():
    """诈身份：板子里有预言家时，**平民也可以声称预言家**并用【查验结论】。

    校验只看申报身份，不看真实职业（游戏的核心机制之一）。
    """
    players = [
        make_player("p1", C.VILLAGER),
        make_player("p2", C.SEER),
        make_player("p3", C.WEREWOLF),
        make_player("p4", C.VILLAGER),
    ]
    state = make_state(
        players,
        phase=C.PHASE_DAY_MARKING,
        marking_order=["p1", "p2", "p3", "p4"],
        marking_current=0,
    )

    problems = validate_player_marks(
        state,
        "p1",
        _marks("预言家", C.REASON_INVESTIGATION, [("p2", "狼人", C.REASON_INVESTIGATION)]),
    )
    assert problems == []


def test_claim_identity_must_exist_on_the_board():
    """⚠️ 源项目既有行为：可选身份由**当局参与的职业**决定，
    因此板子里没有预言家时，任何人都不能声称预言家。

    这条在源项目里是刻意的（避免出现场上根本不存在的职业声明），
    但它也限制了诈身份的发挥空间。是否放宽留待 M3 决策——这里先锁住现状。
    """
    state = _marking_state(alive_count=4)  # 全平民板子
    problems = validate_player_marks(
        state, "p1", _marks("预言家", C.REASON_INVESTIGATION, [])
    )
    assert any("不在可选范围" in p for p in problems)


def test_marks_rejected_when_exceeding_max_evaluation_count():
    state = _marking_state(alive_count=4)  # 4 人局上限 2 个
    problems = validate_player_marks(
        state,
        "p1",
        _marks(
            "好人",
            C.REASON_INTUITION,
            [
                ("p2", "好人", C.REASON_INTUITION),
                ("p3", "好人", C.REASON_INTUITION),
                ("p4", "好人", C.REASON_INTUITION),
            ],
        ),
    )
    assert any("评价标记最多 2 个" in p for p in problems)


def test_marks_rejected_for_self_target_and_duplicates():
    state = _marking_state(alive_count=4)
    problems = validate_player_marks(
        state,
        "p1",
        _marks(
            "好人",
            C.REASON_INTUITION,
            [("p1", "好人", C.REASON_INTUITION), ("p2", "好人", C.REASON_INTUITION),
             ("p2", "狼人", C.REASON_INTUITION)],
        ),
    )
    assert any("不能评价自己" in p for p in problems)


def test_marks_rejected_for_dead_target():
    state = _marking_state(alive_count=4)
    state["players"][1]["alive"] = False
    problems = validate_player_marks(
        state, "p1", _marks("好人", C.REASON_INTUITION, [("p2", "好人", C.REASON_INTUITION)])
    )
    assert any("已出局" in p for p in problems)


def test_marks_rejected_for_invalid_evaluation_identity():
    state = _marking_state(alive_count=4)
    problems = validate_player_marks(
        state, "p1", _marks("好人", C.REASON_INTUITION, [("p2", "预言家", C.REASON_INTUITION)])
    )
    assert any("评价身份" in p for p in problems)


def test_marks_rejected_when_evaluation_reason_conflicts_with_claimed_identity():
    """评价理由同样要匹配**声明身份**（不是真实身份）。"""
    state = _marking_state(alive_count=4)
    problems = validate_player_marks(
        state,
        "p1",
        _marks("好人", C.REASON_INTUITION, [("p2", "狼人", C.REASON_INVESTIGATION)]),
    )
    assert any("与声明身份" in p for p in problems)
