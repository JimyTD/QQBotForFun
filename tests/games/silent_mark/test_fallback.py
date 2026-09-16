"""玩家未行动时的服务端兜底。

包含 ``p0Rules.test.ts`` 中「必选夜晚行动的兜底……」一例的转写。
"""

from __future__ import annotations

from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812
from src.plugins.games.silent_mark.engine import fallback as fallback_engine
from src.plugins.games.silent_mark.engine.fallback import (
    fallback_marks,
    fallback_night_action,
    fallback_vote,
)
from src.plugins.games.silent_mark.engine.roles import create_role

from .factories import make_player, make_state


# =====================================================================
# 夜晚行动兜底
# =====================================================================
def test_fallback_picks_a_target_for_mandatory_actions():
    """转写自源项目 p0Rules.test.ts：必选行动会选目标。"""
    assert fallback_night_action(C.GUARD, ["player2"]) == {
        "action": "guard",
        "target": "player2",
    }
    assert fallback_night_action(C.GRAVEDIGGER, ["player2"]) == {
        "action": "autopsy",
        "target": "player2",
    }


def test_fallback_witch_never_uses_a_potion():
    """转写自源项目 p0Rules.test.ts：可选女巫行动默认不使用药物。"""
    assert fallback_night_action(C.WITCH, ["player2"]) == {
        "action": "usePotion",
        "potion": "none",
    }
    # 即使没有任何合法目标，也依然是不用药
    assert fallback_night_action(C.WITCH, []) == {"action": "usePotion", "potion": "none"}


def test_fallback_returns_none_when_a_mandatory_action_has_no_legal_target():
    """必选行动没有合法目标时返回 None，而不是造一个会被规则层拒绝的动作。

    源项目此处返回不带 target 的 ``{action:'guard'}``，被 ``Guard.performNightAction``
    拒绝 → 多一次无谓重试；兜底再被拒则只打日志、阶段永久卡住
    （源项目 502ef26 一轮修复已处理该问题）。本实现用"返回 None + 调用方直接推进"
    从根上消除这条路径。
    """
    assert fallback_night_action(C.GUARD, []) is None
    assert fallback_night_action(C.SEER, []) is None
    assert fallback_night_action(C.WEREWOLF, []) is None
    # 守墓人没有死者时规则层接受"不带 target 的自动跳过"，所以这里不是 None
    assert fallback_night_action(C.GRAVEDIGGER, []) == {"action": "autopsy"}


def test_fallback_wolf_and_seer_and_roles_without_night_action():
    assert fallback_night_action(C.WEREWOLF, ["a"]) == {"action": "attack", "target": "a"}
    assert fallback_night_action(C.WOLF_KING, ["a"]) == {"action": "attack", "target": "a"}
    assert fallback_night_action(C.SEER, ["a"]) == {"action": "investigate", "target": "a"}
    assert fallback_night_action(C.VILLAGER, ["a"]) == {"action": "skip"}
    assert fallback_night_action(C.HUNTER, []) == {"action": "skip"}


def test_fallback_action_is_always_accepted_by_the_rules_layer():
    """契约测试：兜底产物必须能被规则层受理。否则阶段会卡住（这是硬要求）。"""
    wolf = make_player("wolf", C.WEREWOLF)
    guard = make_player("guard", C.GUARD)
    seer = make_player("seer", C.SEER)
    digger = make_player("digger", C.GRAVEDIGGER)
    witch = make_player("witch", C.WITCH)
    villager = make_player("villager", C.VILLAGER)
    players = [wolf, guard, seer, digger, witch, villager]

    for role, player in (
        (C.WEREWOLF, wolf),
        (C.GUARD, guard),
        (C.SEER, seer),
        (C.GRAVEDIGGER, digger),
        (C.WITCH, witch),
    ):
        state = make_state(list(players))
        role_impl = create_role(role)
        targets = role_impl.get_available_targets(state, player)
        action = fallback_night_action(role, targets)

        assert action is not None, role
        accepted = role_impl.perform_night_action(
            state,
            player,
            target=action.get("target"),
            potion=action.get("potion"),
        )
        assert accepted is True, (role, action)


def test_fallback_night_action_target_is_always_legal(monkeypatch):
    monkeypatch.setattr(fallback_engine.random, "choice", lambda seq: seq[0])
    targets = ["a", "b"]
    assert fallback_night_action(C.GUARD, targets)["target"] in targets


# =====================================================================
# 标记兜底
# =====================================================================
def test_fallback_marks_claims_good_with_intuition():
    players = [
        make_player("p1", C.WEREWOLF),
        make_player("p2", C.WITCH),
        make_player("p3", C.VILLAGER),
        make_player("p4", C.VILLAGER),
    ]
    state = make_state(players)

    marks = fallback_marks(state, "p1")
    assert marks is not None
    assert marks["player"] == "p1"
    assert marks["round"] == 1
    assert marks["identity_mark"] == {
        "identity": C.IDENTITY_GOOD,
        "reason": C.REASON_INTUITION,
    }
    # 4 人存活 → 2 个评价标记，且不含自己
    assert len(marks["evaluation_marks"]) == 2
    assert {m["target"] for m in marks["evaluation_marks"]} == {"p2", "p3"}
    assert all(m["identity"] == C.IDENTITY_GOOD for m in marks["evaluation_marks"])
    assert all(m["reason"] == C.REASON_INTUITION for m in marks["evaluation_marks"])


def test_fallback_marks_uses_evaluation_count_by_alive_players():
    players = [make_player(f"p{i}", C.VILLAGER) for i in range(1, 8)]
    state = make_state(players)

    marks = fallback_marks(state, "p1")
    assert marks is not None
    # 7 人存活 → 3 个评价标记
    assert len(marks["evaluation_marks"]) == 3


def test_fallback_marks_returns_none_when_nobody_else_is_alive():
    state = make_state([make_player("p1", C.VILLAGER)])
    assert fallback_marks(state, "p1") is None


# =====================================================================
# 投票兜底
# =====================================================================
def test_fallback_vote_never_votes_for_self():
    assert fallback_vote(["p1", "p2", "p3"], "p1") == "p2"
    assert fallback_vote(["p2", "p3"], "p1") == "p2"
    assert fallback_vote(["p1"], "p1") is None
    assert fallback_vote([], "p1") is None
