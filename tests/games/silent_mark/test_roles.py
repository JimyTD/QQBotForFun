"""角色处理器规则。

对应源项目 ``server/game/roles/*``。包含 ``p0Rules.test.ts`` 中
「P0 角色行动规则」两例的转写。
"""

from __future__ import annotations

import pytest

from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812
from src.plugins.games.silent_mark.engine import roles as roles_engine
from src.plugins.games.silent_mark.engine.roles import (
    create_role,
    has_voting_right,
    new_role_state,
)

from .factories import make_night, make_player, make_state


# =====================================================================
# 守卫
# =====================================================================
def test_guard_cannot_guard_nobody():
    """转写自源项目 p0Rules.test.ts：守卫没有目标时不能空守。"""
    guard = make_player("p1", C.GUARD)
    state = make_state([guard])

    assert create_role(C.GUARD).perform_night_action(state, guard) is False
    assert state["night_actions"]["guard"] is None


def test_guard_cannot_guard_the_same_target_two_nights_in_a_row():
    guard = make_player("g", C.GUARD, role_state={"last_guard_target": "v"})
    villager = make_player("v", C.VILLAGER)
    state = make_state([guard, villager], round=2)

    assert create_role(C.GUARD).perform_night_action(state, guard, target="v") is False
    assert state["night_actions"]["guard"] is None
    # 换一个目标就合法
    assert create_role(C.GUARD).perform_night_action(state, guard, target="g") is True
    assert state["night_actions"]["guard"] == {"target": "g"}
    assert guard["role_state"]["last_guard_target"] == "g"


def test_guard_may_guard_self_and_last_target_is_excluded():
    guard = make_player("g", C.GUARD, role_state={"last_guard_target": "v"})
    villager = make_player("v", C.VILLAGER)
    state = make_state([guard, villager], round=2)

    targets = create_role(C.GUARD).get_available_targets(state, guard)
    assert "g" in targets  # 可以守自己
    assert "v" not in targets  # 不可连守


def test_guard_cannot_guard_dead_player_via_targets():
    guard = make_player("g", C.GUARD)
    dead = make_player("d", C.VILLAGER, alive=False)
    state = make_state([guard, dead])

    assert "d" not in create_role(C.GUARD).get_available_targets(state, guard)


# =====================================================================
# 守墓人
# =====================================================================
def test_gravedigger_auto_skips_when_nobody_is_dead():
    """转写自源项目 p0Rules.test.ts：没有死者时自动跳过。"""
    digger = make_player("p1", C.GRAVEDIGGER)
    state = make_state([digger])

    assert create_role(C.GRAVEDIGGER).perform_night_action(state, digger) is True
    assert state["night_actions"]["gravedigger"] == {"target": None}


def test_gravedigger_must_pick_a_dead_player_when_someone_is_dead():
    """转写自源项目 p0Rules.test.ts：有死者时必须选择死者。"""
    digger = make_player("p1", C.GRAVEDIGGER)
    dead = make_player("p2", C.VILLAGER, alive=False)
    state = make_state([digger, dead])

    assert create_role(C.GRAVEDIGGER).perform_night_action(state, digger) is False
    assert state["night_actions"]["gravedigger"] is None


def test_gravedigger_rejects_living_target():
    digger = make_player("d", C.GRAVEDIGGER)
    alive = make_player("a", C.VILLAGER)
    state = make_state([digger, alive])

    assert create_role(C.GRAVEDIGGER).perform_night_action(state, digger, target="a") is False


# =====================================================================
# 预言家
# =====================================================================
def test_seer_targets_exclude_self_and_dead():
    seer = make_player("s", C.SEER)
    other = make_player("o", C.VILLAGER)
    dead = make_player("d", C.VILLAGER, alive=False)
    state = make_state([seer, other, dead])

    targets = create_role(C.SEER).get_available_targets(state, seer)
    assert targets == ["o"]
    assert create_role(C.SEER).perform_night_action(state, seer) is False
    assert create_role(C.SEER).perform_night_action(state, seer, target="o") is True
    assert state["night_actions"]["seer"] == {"target": "o"}


# =====================================================================
# 女巫
# =====================================================================
def test_witch_can_self_save_on_first_night_only():
    witch = make_player("w", C.WITCH)
    wolf = make_player("wolf", C.WEREWOLF)
    state = make_state([witch, wolf], round=1, night_actions=make_night(wolves_target="w"))

    role = create_role(C.WITCH)
    assert role.perform_night_action(state, witch, potion="antidote") is True
    assert state["night_actions"]["witch"] == {"action": "antidote", "target": "w"}
    assert witch["role_state"]["antidote_used"] is True


@pytest.mark.parametrize("round_no", [2, 3])
def test_witch_cannot_self_save_after_first_night(round_no):
    witch = make_player("w", C.WITCH)
    wolf = make_player("wolf", C.WEREWOLF)
    state = make_state(
        [witch, wolf], round=round_no, night_actions=make_night(wolves_target="w")
    )

    assert create_role(C.WITCH).perform_night_action(state, witch, potion="antidote") is False
    assert state["night_actions"]["witch"] is None
    assert witch["role_state"]["antidote_used"] is False


def test_witch_antidote_saves_the_wolf_victim():
    witch = make_player("w", C.WITCH)
    victim = make_player("v", C.VILLAGER)
    state = make_state([witch, victim], round=2, night_actions=make_night(wolves_target="v"))

    assert create_role(C.WITCH).perform_night_action(state, witch, potion="antidote") is True
    assert state["night_actions"]["witch"] == {"action": "antidote", "target": "v"}


def test_witch_each_potion_only_once():
    witch = make_player(
        "w", C.WITCH, role_state={"antidote_used": True, "poison_used": True}
    )
    victim = make_player("v", C.VILLAGER)
    state = make_state([witch, victim], round=2)

    role = create_role(C.WITCH)
    assert role.perform_night_action(state, witch, potion="antidote") is False
    assert role.perform_night_action(state, witch, potion="poison", target="v") is False
    assert state["night_actions"]["witch"] is None


def test_witch_poison_requires_target():
    witch = make_player("w", C.WITCH)
    victim = make_player("v", C.VILLAGER)
    state = make_state([witch, victim])

    role = create_role(C.WITCH)
    assert role.perform_night_action(state, witch, potion="poison") is False
    assert witch["role_state"]["poison_used"] is False
    assert role.perform_night_action(state, witch, potion="poison", target="v") is True
    assert state["night_actions"]["witch"] == {"action": "poison", "target": "v"}


def test_witch_doing_nothing_records_none():
    witch = make_player("w", C.WITCH)
    other = make_player("o", C.VILLAGER)
    state = make_state([witch, other])

    assert create_role(C.WITCH).perform_night_action(state, witch) is True
    assert state["night_actions"]["witch"] == {"action": "none", "target": None}
    assert witch["role_state"] == {"antidote_used": False, "poison_used": False}


def test_witch_poison_targets_exclude_self():
    witch = make_player("w", C.WITCH)
    other = make_player("o", C.VILLAGER)
    state = make_state([witch, other])

    assert create_role(C.WITCH).get_available_targets(state, witch) == ["o"]


# =====================================================================
# 狼人 / 白狼王
# =====================================================================
def test_wolves_target_is_decided_only_after_every_wolf_voted():
    w1 = make_player("w1", C.WEREWOLF)
    w2 = make_player("w2", C.WEREWOLF)
    villager = make_player("v", C.VILLAGER)
    state = make_state([w1, w2, villager])

    role = create_role(C.WEREWOLF)
    assert role.perform_night_action(state, w1, target="v") is True
    assert state["night_actions"]["wolves"]["target"] is None  # 还差一只狼

    assert role.perform_night_action(state, w2, target="v") is True
    assert state["night_actions"]["wolves"]["target"] == "v"


def test_wolves_tie_break_is_random_among_top_targets(monkeypatch):
    monkeypatch.setattr(roles_engine.random, "choice", lambda seq: sorted(seq)[0])
    w1 = make_player("w1", C.WEREWOLF)
    w2 = make_player("w2", C.WEREWOLF)
    v1 = make_player("v1", C.VILLAGER)
    v2 = make_player("v2", C.VILLAGER)
    state = make_state([w1, w2, v1, v2])

    role = create_role(C.WEREWOLF)
    role.perform_night_action(state, w1, target="v1")
    role.perform_night_action(state, w2, target="v2")

    target = state["night_actions"]["wolves"]["target"]
    assert target in {"v1", "v2"}
    assert target == "v1"  # 打了桩：取排序后第一个


def test_wolf_may_self_knife_but_not_teammate():
    w1 = make_player("w1", C.WEREWOLF)
    w2 = make_player("w2", C.WOLF_KING)
    villager = make_player("v", C.VILLAGER)
    state = make_state([w1, w2, villager])

    targets = create_role(C.WEREWOLF).get_available_targets(state, w1)
    assert "w1" in targets  # 自刀是合法策略
    assert "v" in targets
    assert "w2" not in targets  # 不能刀队友


def test_wolf_king_shares_wolf_vote_and_tally():
    """白狼王与普通狼人共同合议：两边都投完才定目标。"""
    w1 = make_player("w1", C.WEREWOLF)
    king = make_player("king", C.WOLF_KING)
    villager = make_player("v", C.VILLAGER)
    state = make_state([w1, king, villager])

    create_role(C.WEREWOLF).perform_night_action(state, w1, target="v")
    assert state["night_actions"]["wolves"]["target"] is None
    create_role(C.WOLF_KING).perform_night_action(state, king, target="v")
    assert state["night_actions"]["wolves"]["target"] == "v"


def test_wolf_king_drags_only_when_exiled():
    king = make_player("king", C.WOLF_KING)
    state = make_state([king])

    role = create_role(C.WOLF_KING)
    assert role.on_death(state, king, C.DEATH_EXILED) == {
        "type": "wolf_king_drag",
        "pid": "king",
    }
    for cause in (C.DEATH_POISONED, C.DEATH_ATTACKED, C.DEATH_DUEL, C.DEATH_SHOT):
        assert role.on_death(state, king, cause) is None


# =====================================================================
# 猎人
# =====================================================================
def test_hunter_can_shoot_when_attacked_or_exiled():
    hunter = make_player("h", C.HUNTER)
    state = make_state([hunter])

    role = create_role(C.HUNTER)
    for cause in (C.DEATH_ATTACKED, C.DEATH_EXILED, C.DEATH_SHOT, C.DEATH_DUEL,
                  C.DEATH_WOLF_KING_DRAG, C.DEATH_GUARD_WITCH_CLASH):
        assert role.on_death(state, hunter, cause) == {"type": "hunter_shoot", "pid": "h"}, cause


def test_hunter_cannot_shoot_when_poisoned_and_loses_the_ability_for_good():
    hunter = make_player("h", C.HUNTER, role_state={"can_shoot": True})
    state = make_state([hunter])

    role = create_role(C.HUNTER)
    assert role.on_death(state, hunter, C.DEATH_POISONED) is None
    assert hunter["role_state"]["can_shoot"] is False
    # 能力已永久失去：之后即使被放逐也不能开枪
    assert role.on_death(state, hunter, C.DEATH_EXILED) is None


def test_hunter_without_ability_never_triggers():
    hunter = make_player("h", C.HUNTER, role_state={"can_shoot": False})
    state = make_state([hunter])

    assert create_role(C.HUNTER).on_death(state, hunter, C.DEATH_EXILED) is None


# =====================================================================
# 白痴 / 骑士
# =====================================================================
def test_fool_immunity_works_only_once_and_only_on_exile():
    fool = make_player("f", C.FOOL)
    state = make_state([fool])

    role = create_role(C.FOOL)
    assert role.on_exile(state, fool) is True  # 首次放逐：免疫，不出局
    assert fool["role_state"]["immunity_used"] is True
    assert role.on_exile(state, fool) is False  # 第二次照常出局
    # 被刀/被毒不走 on_exile，白痴没有额外保护
    assert role.on_death(state, fool, C.DEATH_ATTACKED) is None


def test_fool_loses_voting_right_after_immunity():
    fool = make_player("f", C.FOOL)
    villager = make_player("v", C.VILLAGER)
    state = make_state([fool, villager])

    assert has_voting_right(fool) is True
    create_role(C.FOOL).on_exile(state, fool)
    assert has_voting_right(fool) is False
    assert has_voting_right(villager) is True


def test_knight_has_no_night_action_and_no_death_trigger():
    knight = make_player("k", C.KNIGHT)
    state = make_state([knight])

    role = create_role(C.KNIGHT)
    assert role.has_night_action is False
    assert role.perform_night_action(state, knight, target="k") is False
    assert role.on_death(state, knight, C.DEATH_DUEL) is None


# =====================================================================
# 工厂与初始资源状态
# =====================================================================
def test_unknown_role_degrades_to_villager():
    """源项目对未实现角色降级为平民。"""
    role = create_role("dragon")
    assert role.role == C.VILLAGER
    assert role.has_night_action is False


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (C.WITCH, {"antidote_used": False, "poison_used": False}),
        (C.GUARD, {"last_guard_target": None}),
        (C.FOOL, {"immunity_used": False}),
        (C.KNIGHT, {"duel_used": False}),
        (C.HUNTER, {"can_shoot": True}),
        (C.SEER, {}),
        (C.GRAVEDIGGER, {}),
        (C.WEREWOLF, {}),
        (C.WOLF_KING, {}),
        (C.VILLAGER, {}),
    ],
)
def test_new_role_state(role, expected):
    assert new_role_state(role) == expected


def test_every_role_has_a_handler_and_a_faction():
    for role in C.AVAILABLE_ROLES_FOR_CUSTOM:
        assert new_role_state(role) is not None
        assert role in C.ROLE_FACTION
