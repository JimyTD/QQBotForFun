"""AI 决策守卫（`ai/guard.py`）—— 计划里点名"最容易写错、最该独立单测"的部分。

守卫的职责边界很重要，这里两头都锁：

- **该纠正的必须纠正**（违背 AI 自己已知信息的决策）；
- **不该动的绝不能动**（正常策略空间、诈身份的合法玩法、猎人/骑士那条不可实现的校验）。
"""

from __future__ import annotations

import random

from src.plugins.games.silent_mark.ai import guard
from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812

RNG = random.Random(20260916)


def _player(pid: str, seat: int, role: str, faction: str, *, alive: bool = True) -> dict:
    return {
        "pid": pid,
        "nickname": pid,
        "seat": seat,
        "role": role,
        "faction": faction,
        "alive": alive,
        "items": [],
        "role_state": {},
    }


def _state(players: list[dict], *, rounds: list[dict] | None = None, marks: list[dict] | None = None) -> dict:
    return {
        "players": players,
        "history": {
            "rounds": rounds or [],
            "marks": marks or [],
            "votes": [],
            "deaths": [],
        },
        "round": 2,
    }


def _seer_night(target: str) -> dict:
    return {"seer": {"target": target}, "guard": None, "wolves": None, "witch": None, "gravedigger": None}


def _gravedigger_night(target: str) -> dict:
    return {
        "seer": None,
        "guard": None,
        "wolves": None,
        "witch": None,
        "gravedigger": {"target": target},
    }


def _mark(player: str, evaluations: list[tuple[str, str]]) -> dict:
    return {
        "player": player,
        "round": 1,
        "identity_mark": {"identity": C.IDENTITY_GOOD, "reason": C.REASON_INTUITION},
        "evaluation_marks": [
            {"target": target, "identity": identity, "reason": C.REASON_INTUITION}
            for target, identity in evaluations
        ],
    }


# =====================================================================
# 夜间：狼人不刀队友 / 不重复查验 / 不重复验尸
# =====================================================================
def test_wolf_does_not_knife_a_teammate() -> None:
    wolf_a = _player("1", 1, C.WEREWOLF, C.EVIL)
    wolf_b = _player("2", 2, C.WOLF_KING, C.EVIL)
    villager = _player("3", 3, C.VILLAGER, C.GOOD)
    state = _state([wolf_a, wolf_b, villager])

    target, corrections = guard.guard_night_action(
        state, "1", C.WEREWOLF, "2", ["2", "3"], rng=RNG
    )

    assert target == "3"
    assert len(corrections) == 1
    assert corrections[0].field == "night_attack"
    assert corrections[0].before == "2号"
    assert corrections[0].after == "3号"


def test_wolf_may_knife_a_teammate_when_only_teammates_remain() -> None:
    """只剩队友可刀时保留原选择（规则允许，源项目同处理）。"""
    wolf_a = _player("1", 1, C.WEREWOLF, C.EVIL)
    wolf_b = _player("2", 2, C.WOLF_KING, C.EVIL)
    state = _state([wolf_a, wolf_b])

    target, corrections = guard.guard_night_action(
        state, "1", C.WEREWOLF, "2", ["2"], rng=RNG
    )

    assert target == "2"
    assert corrections == []


def test_seer_does_not_repeat_an_investigation() -> None:
    seer = _player("1", 1, C.SEER, C.GOOD)
    seen = _player("2", 2, C.VILLAGER, C.GOOD)
    fresh = _player("3", 3, C.WEREWOLF, C.EVIL)
    state = _state([seer, seen, fresh], rounds=[_seer_night("2")])

    target, corrections = guard.guard_night_action(
        state, "1", C.SEER, "2", ["2", "3"], rng=RNG
    )

    assert target == "3"
    assert corrections and corrections[0].field == "night_investigate"


def test_gravedigger_does_not_repeat_an_autopsy() -> None:
    digger = _player("1", 1, C.GRAVEDIGGER, C.GOOD)
    dead_a = _player("2", 2, C.VILLAGER, C.GOOD, alive=False)
    dead_b = _player("3", 3, C.WEREWOLF, C.EVIL, alive=False)
    state = _state([digger, dead_a, dead_b], rounds=[_gravedigger_night("2")])

    target, corrections = guard.guard_night_action(
        state, "1", C.GRAVEDIGGER, "2", ["2", "3"], rng=RNG
    )

    assert target == "3"
    assert corrections and corrections[0].field == "night_autopsy"


def test_non_seer_gets_no_private_results() -> None:
    """私有信息只属于本人：平民/猎人视角里"已查验"必须是空的。"""
    villager = _player("1", 1, C.VILLAGER, C.GOOD)
    seen = _player("2", 2, C.WEREWOLF, C.EVIL)
    state = _state([villager, seen], rounds=[_seer_night("2")])

    assert guard.collect_seer_results(state, "1") == {}
    assert guard.collect_gravedigger_results(state, "1") == {}


# =====================================================================
# 投票
# =====================================================================
def test_seer_never_votes_for_a_confirmed_good() -> None:
    seer = _player("1", 1, C.SEER, C.GOOD)
    known_good = _player("2", 2, C.VILLAGER, C.GOOD)
    suspect = _player("3", 3, C.WEREWOLF, C.EVIL)
    state = _state([seer, known_good, suspect], rounds=[_seer_night("2")])

    target, corrections = guard.guard_vote(state, "1", "2", ["2", "3"])

    assert target == "3"
    assert corrections and "查验确认的好人" in corrections[0].reason


def test_seer_prefers_a_confirmed_wolf_when_present() -> None:
    """软倾向：手上有确认的狼却没投他 → 改投（源项目同样是纠正而非忽略）。"""
    seer = _player("1", 1, C.SEER, C.GOOD)
    known_wolf = _player("2", 2, C.WEREWOLF, C.EVIL)
    other = _player("3", 3, C.VILLAGER, C.GOOD)
    state = _state([seer, known_wolf, other], rounds=[_seer_night("2")])

    target, corrections = guard.guard_vote(state, "1", "3", ["2", "3"])

    assert target == "2"
    assert corrections and "应优先投出" in corrections[0].reason


def test_wolf_does_not_vote_for_a_teammate_and_picks_the_most_accused_outsider() -> None:
    wolf = _player("1", 1, C.WEREWOLF, C.EVIL)
    teammate = _player("2", 2, C.WOLF_KING, C.EVIL)
    quiet = _player("3", 3, C.VILLAGER, C.GOOD)
    accused = _player("4", 4, C.VILLAGER, C.GOOD)
    state = _state(
        [wolf, teammate, quiet, accused],
        marks=[
            _mark("3", [("4", C.IDENTITY_WOLF)]),
            _mark("4", [("4", C.IDENTITY_WOLF)]),  # 4 号被标记"狼人"两次
        ],
    )

    target, corrections = guard.guard_vote(state, "1", "2", ["2", "3", "4"])

    assert target == "4"
    assert corrections and "狼人队友" in corrections[0].reason


# =====================================================================
# 标记
# =====================================================================
def test_wolf_never_claims_wolf() -> None:
    wolf = _player("1", 1, C.WEREWOLF, C.EVIL)
    other = _player("2", 2, C.VILLAGER, C.GOOD)
    state = _state([wolf, other])
    identity = {"identity": C.IDENTITY_WOLF, "reason": C.REASON_INTUITION}

    corrections = guard.guard_marking(state, "1", identity, [])

    assert identity["identity"] == C.IDENTITY_GOOD
    assert corrections and "自曝身份" in corrections[0].reason


def test_wolf_never_accuses_a_teammate() -> None:
    wolf = _player("1", 1, C.WEREWOLF, C.EVIL)
    teammate = _player("2", 2, C.WOLF_KING, C.EVIL)
    state = _state([wolf, teammate])
    identity = {"identity": C.IDENTITY_GOOD, "reason": C.REASON_INTUITION}
    evaluations = [
        {"target": "2", "identity": C.IDENTITY_WOLF, "reason": C.REASON_INVESTIGATION}
    ]

    corrections = guard.guard_marking(state, "1", identity, evaluations)

    assert evaluations[0]["identity"] == C.IDENTITY_GOOD
    # 理由原本是"查验结论"，改口成"好人"后必须回落成普通理由
    assert evaluations[0]["reason"] == C.REASON_INTUITION
    assert any("自曝关系" in c.reason for c in corrections)


def test_investigation_identity_can_use_investigation_reason() -> None:
    """诈身份是合法玩法：**不能**按真实角色拦截这条理由。

    一个平民声称"预言家"并用查验结论作为理由 → 守卫必须放行（源项目原注释明说）。
    """
    villager = _player("1", 1, C.VILLAGER, C.GOOD)
    other = _player("2", 2, C.WEREWOLF, C.EVIL)
    state = _state([villager, other])
    identity = {"identity": "预言家", "reason": C.REASON_INVESTIGATION}
    evaluations = [
        {"target": "2", "identity": C.IDENTITY_WOLF, "reason": C.REASON_INVESTIGATION}
    ]

    corrections = guard.guard_marking(state, "1", identity, evaluations)

    assert corrections == []
    assert identity["reason"] == C.REASON_INVESTIGATION


def test_claiming_villager_cannot_use_special_reasons() -> None:
    villager = _player("1", 1, C.VILLAGER, C.GOOD)
    other = _player("2", 2, C.WEREWOLF, C.EVIL)
    state = _state([villager, other])
    identity = {"identity": C.IDENTITY_GOOD, "reason": C.REASON_INVESTIGATION}
    evaluations = [
        {"target": "2", "identity": C.IDENTITY_WOLF, "reason": C.REASON_POTION_RESULT}
    ]

    corrections = guard.guard_marking(state, "1", identity, evaluations)

    assert identity["reason"] == C.REASON_INTUITION
    assert evaluations[0]["reason"] == C.REASON_INTUITION
    assert len(corrections) == 2


def test_evaluation_must_match_own_investigation() -> None:
    seer = _player("1", 1, C.SEER, C.GOOD)
    seen_good = _player("2", 2, C.VILLAGER, C.GOOD)
    state = _state([seer, seen_good], rounds=[_seer_night("2")])
    identity = {"identity": "预言家", "reason": C.REASON_INVESTIGATION}
    evaluations = [
        {"target": "2", "identity": C.IDENTITY_WOLF, "reason": C.REASON_INTUITION}
    ]

    corrections = guard.guard_marking(state, "1", identity, evaluations)

    assert evaluations[0]["identity"] == C.IDENTITY_GOOD
    assert evaluations[0]["reason"] == C.REASON_INVESTIGATION
    assert corrections and "查验结论矛盾" in corrections[0].reason


# =====================================================================
# 触发技能
# =====================================================================
def test_wolf_king_does_not_drag_a_teammate() -> None:
    king = _player("1", 1, C.WOLF_KING, C.EVIL)
    teammate = _player("2", 2, C.WEREWOLF, C.EVIL)
    villager = _player("3", 3, C.VILLAGER, C.GOOD)
    state = _state([king, teammate, villager])

    target, corrections = guard.guard_trigger_action(
        state, "1", guard.TRIGGER_WOLF_KING_DRAG, "2", ["2", "3"]
    )

    assert target == "3"
    assert corrections and corrections[0].field == "wolf_king_drag"


def test_hunter_and_knight_targets_are_never_second_guessed() -> None:
    """猎人/骑士没有任何"已确认好人"的私有信息 → 这里**不该有任何纠正**。

    源项目 502ef26 把这段不可实现的校验删了；本移植同样不写死代码 ——
    这条测试就是"别好心加回来"的护栏。
    """
    hunter = _player("1", 1, C.HUNTER, C.GOOD)
    someone = _player("2", 2, C.VILLAGER, C.GOOD)
    state = _state([hunter, someone])

    target, corrections = guard.guard_trigger_action(
        state, "1", "hunter_shoot", "2", ["2"]
    )

    assert target == "2"
    assert corrections == []
