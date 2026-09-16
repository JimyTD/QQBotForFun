"""信息防火墙（私有信息裁剪）。

逐例转写自源项目 ``server/game/__tests__/privateInfo.test.ts``。
字段名按本仓库约定改为 snake_case，语义一致。
"""

from __future__ import annotations

from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812
from src.plugins.games.silent_mark.engine.private_info import build_my_private_info

from .factories import make_night, make_player, make_state


def _roster() -> dict[str, dict]:
    return {
        "witch": make_player("witch", C.WITCH, seat=1, role_state={"antidote_used": True, "poison_used": False}),
        "seer": make_player("seer", C.SEER, seat=2),
        "wolf": make_player("wolf", C.WEREWOLF, seat=3),
        "villager": make_player("villager", C.VILLAGER, seat=4),
    }


def test_witch_merges_settled_and_in_progress_potion_history():
    roster = _roster()
    state = make_state(
        list(roster.values()),
        round=2,
        phase=C.PHASE_NIGHT,
        night_actions=make_night(witch_action="poison", witch_target="villager"),
        history={
            "rounds": [make_night(witch_action="antidote", witch_target="seer")],
            "marks": [],
            "votes": [],
            "deaths": [],
        },
    )

    info = build_my_private_info(state, roster["witch"])
    assert info["witch"]["antidote_used"] is True
    assert info["witch"]["poison_used"] is False
    assert info["witch"]["potion_history"] == [
        {"round": 1, "potion": "antidote", "target": "seer"},
        {"round": 2, "potion": "poison", "target": "villager"},
    ]


def test_daytime_does_not_double_count_the_previous_nights_actions():
    roster = _roster()
    state = make_state(
        list(roster.values()),
        round=2,
        phase=C.PHASE_DAY_MARKING,
        night_actions=make_night(witch_action="antidote", witch_target="seer"),
        history={
            "rounds": [make_night(witch_action="antidote", witch_target="seer")],
            "marks": [],
            "votes": [],
            "deaths": [],
        },
    )

    info = build_my_private_info(state, roster["witch"])
    assert info["witch"]["potion_history"] == [
        {"round": 1, "potion": "antidote", "target": "seer"}
    ]


def test_seer_only_sees_own_investigations_and_no_other_roles_private_info():
    roster = _roster()
    state = make_state(
        list(roster.values()),
        history={
            "rounds": [make_night(seer_target="wolf")],
            "marks": [],
            "votes": [],
            "deaths": [],
        },
    )

    info = build_my_private_info(state, roster["seer"])
    assert info["investigations"] == [
        {"round": 1, "kind": "seer", "target": "wolf", "faction": C.EVIL}
    ]
    assert "witch" not in info
    assert "guard" not in info
    assert "wolf_attacks" not in info


def test_gravedigger_investigations_are_marked_as_autopsy():
    digger = make_player("digger", C.GRAVEDIGGER, seat=1)
    dead = make_player("dead", C.WEREWOLF, seat=2, alive=False)
    state = make_state(
        [digger, dead],
        history={
            "rounds": [make_night(gravedigger_target="dead")],
            "marks": [],
            "votes": [],
            "deaths": [],
        },
    )

    info = build_my_private_info(state, digger)
    assert info["investigations"] == [
        {"round": 1, "kind": "gravedigger", "target": "dead", "faction": C.EVIL}
    ]


def test_guard_gets_last_target_and_history():
    roster = _roster()
    guard = make_player("guard", C.GUARD, seat=5, role_state={"last_guard_target": "villager"})
    state = make_state(
        [*roster.values(), guard],
        history={
            "rounds": [make_night(guard_target="seer")],
            "marks": [],
            "votes": [],
            "deaths": [],
        },
    )

    info = build_my_private_info(state, guard)
    assert info["guard"] == {
        "last_guard_target": "villager",
        "history": [{"round": 1, "target": "seer"}],
    }


def test_wolf_gets_attack_history():
    roster = _roster()
    state = make_state(
        list(roster.values()),
        history={
            "rounds": [
                make_night(wolves_target="seer", wolves_votes={"wolf": "seer"}),
                make_night(wolves_target="witch", wolves_votes={"wolf": "witch"}),
            ],
            "marks": [],
            "votes": [],
            "deaths": [],
        },
    )

    info = build_my_private_info(state, roster["wolf"])
    assert info["wolf_attacks"] == [
        {"round": 1, "target": "seer"},
        {"round": 2, "target": "witch"},
    ]
    # 预言家的查验记录不会泄露给狼人
    assert "investigations" not in info


def test_villager_has_no_private_records_at_all():
    roster = _roster()
    state = make_state(
        list(roster.values()),
        round=2,
        phase=C.PHASE_NIGHT,
        night_actions=make_night(wolves_target="seer"),
        history={
            "rounds": [make_night(wolves_target="seer")],
            "marks": [],
            "votes": [],
            "deaths": [],
        },
    )

    assert build_my_private_info(state, roster["villager"]) == {}


def test_hunter_knight_fool_get_ability_status():
    hunter = make_player("hunter", C.HUNTER, seat=6, role_state={"can_shoot": False})
    knight = make_player("knight", C.KNIGHT, seat=7, role_state={"duel_used": True})
    fool = make_player("fool", C.FOOL, seat=8, role_state={"immunity_used": True})
    state = make_state([hunter, knight, fool])

    assert build_my_private_info(state, hunter)["hunter_can_shoot"] is False
    assert build_my_private_info(state, knight)["knight_duel_used"] is True
    assert build_my_private_info(state, fool)["fool_immunity_used"] is True


def test_investigations_skip_targets_that_cannot_be_resolved():
    """查验目标若已不在玩家列表里（异常状态）则跳过，不产出半截记录。"""
    seer = make_player("seer", C.SEER, seat=1)
    state = make_state(
        [seer],
        history={
            "rounds": [make_night(seer_target="ghost")],
            "marks": [],
            "votes": [],
            "deaths": [],
        },
    )

    assert build_my_private_info(state, seer) == {"investigations": []}
