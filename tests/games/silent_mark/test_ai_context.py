"""AI 信息上下文（`ai/context.py`）—— 这里锁的是**信息防火墙**。

AI 不能开天眼，这是整个 AI 子系统最不能出错的地方：
它看到的东西，必须严格等于"这个座位上的真人能看到的东西"。
"""

from __future__ import annotations

from src.plugins.games.silent_mark.ai import context as ai_context
from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812


def _player(pid: str, seat: int, role: str, faction: str, *, alive: bool = True) -> dict:
    return {
        "pid": pid,
        "nickname": f"P{seat}",
        "seat": seat,
        "role": role,
        "faction": faction,
        "alive": alive,
        "items": [],
        "role_state": {},
    }


def _state(players: list[dict], **overrides: object) -> dict:
    state: dict = {
        "status": "playing",
        "round": 2,
        "phase": C.PHASE_DAY_MARKING,
        "players": players,
        "night_actions": {
            "guard": None,
            "wolves": None,
            "witch": None,
            "seer": None,
            "gravedigger": None,
        },
        "night_current_role": None,
        "marking_order": [],
        "marking_current": 0,
        "pending_triggers": [],
        "history": {"rounds": [], "marks": [], "votes": [], "deaths": []},
        "winner": None,
    }
    state.update(overrides)
    return state


BASE_PLAYERS = [
    _player("1", 1, C.WEREWOLF, C.EVIL),
    _player("2", 2, C.WEREWOLF, C.EVIL),
    _player("3", 3, C.SEER, C.GOOD),
    _player("4", 4, C.VILLAGER, C.GOOD),
]


def test_villager_sees_no_private_facts_at_all() -> None:
    """平民没有任何私有信息：一个字段都不该被填上。"""
    state = _state(BASE_PLAYERS)
    ctx = ai_context.build_context(state, "4")
    private = ctx["private_facts"]

    assert private["teammates"] == []
    assert private["investigations"] == []
    assert private["witch"] is None
    assert private["last_guard_target_seat"] is None
    assert private["wolf_attacks"] == []
    assert private["hunter_can_shoot"] is None
    assert private["knight_duel_used"] is None
    assert private["fool_immunity_used"] is None


def test_wolf_sees_teammates_but_villager_does_not() -> None:
    state = _state(BASE_PLAYERS)

    wolf_ctx = ai_context.build_context(state, "1")
    villager_ctx = ai_context.build_context(state, "4")

    assert [t["seat"] for t in wolf_ctx["private_facts"]["teammates"]] == [2]
    assert villager_ctx["private_facts"]["teammates"] == []


def test_seer_sees_only_his_own_results() -> None:
    seer = _player("3", 3, C.SEER, C.GOOD)
    state = _state(
        BASE_PLAYERS,
        history={
            "rounds": [
                {
                    "guard": None,
                    "wolves": {"target": "4"},
                    "witch": {"action": "none"},
                    "seer": {"target": "1"},
                    "gravedigger": None,
                }
            ],
            "marks": [],
            "votes": [],
            "deaths": [],
        },
    )
    assert seer["role"] == C.SEER  # 只是让上面的构建显式一点

    ctx = ai_context.build_context(state, "3")

    assert ctx["private_facts"]["investigations"] == [
        {"round": 1, "kind": "seer", "target_seat": 1, "faction": C.EVIL}
    ]


def test_night_death_cause_is_not_leaked_to_ai() -> None:
    """被毒死的玩家，在 AI 眼里只能是"被狼人袭击"。

    公布真实死因等于告诉全场"女巫用毒了/守卫同守同救了"——那是私有信息。
    """
    poisoned = _player("4", 4, C.VILLAGER, C.GOOD, alive=False)
    state = _state(
        [*BASE_PLAYERS[:3], poisoned],
        history={
            "rounds": [],
            "marks": [],
            "votes": [],
            "deaths": [
                {"pid": "4", "seat": 4, "cause": C.DEATH_POISONED, "round": 1, "relics": []}
            ],
        },
    )

    ctx = ai_context.build_context(state, "1")
    text = ai_context.context_to_text(ctx)

    assert ctx["public_facts"]["dead_players"][0]["cause"] == C.DEATH_ATTACKED
    assert "被狼人袭击" in text
    assert "被毒死" not in text


def test_public_death_cause_is_kept_for_daytime_events() -> None:
    exiled = _player("4", 4, C.VILLAGER, C.GOOD, alive=False)
    state = _state(
        [*BASE_PLAYERS[:3], exiled],
        history={
            "rounds": [],
            "marks": [],
            "votes": [],
            "deaths": [
                {"pid": "4", "seat": 4, "cause": C.DEATH_EXILED, "round": 1, "relics": []}
            ],
        },
    )

    text = ai_context.context_to_text(ai_context.build_context(state, "1"))

    assert "被放逐" in text


def test_revealed_relics_are_visible_to_ai() -> None:
    dead = _player("4", 4, C.VILLAGER, C.GOOD, alive=False)
    state = _state(
        [*BASE_PLAYERS[:3], dead],
        history={
            "rounds": [],
            "marks": [],
            "votes": [],
            "deaths": [
                {
                    "pid": "4",
                    "seat": 4,
                    "cause": C.DEATH_ATTACKED,
                    "round": 1,
                    "relics": [
                        {"type": C.MOONSTONE, "value": 2, "revealed": True},
                        {"type": C.BALANCE, "value": "", "revealed": False},
                    ],
                }
            ],
        },
    )

    ctx = ai_context.build_context(state, "1")
    relics = ctx["public_facts"]["dead_players"][0]["relics"]
    text = ai_context.context_to_text(ctx)

    # 未公开的遗物不进上下文（revealed=False 的那件）
    assert len(relics) == 1 and relics[0]["type"] == C.MOONSTONE
    assert "月光石" in text


def test_witch_context_carries_victim_and_potion_history() -> None:
    witch = _player("2", 2, C.WITCH, C.GOOD)
    witch["role_state"] = {"antidote_used": True, "poison_used": False}
    state = _state(
        [BASE_PLAYERS[0], witch, *BASE_PLAYERS[2:]],
        round=2,
        phase=C.PHASE_NIGHT,
        night_actions={"guard": None, "wolves": {"target": "4"}, "witch": None, "seer": None, "gravedigger": None},
        history={
            "rounds": [
                {
                    "guard": None,
                    "wolves": {"target": "3"},
                    "witch": {"action": "antidote", "target": "3"},
                    "seer": None,
                    "gravedigger": None,
                }
            ],
            "marks": [],
            "votes": [],
            "deaths": [],
        },
    )

    ctx = ai_context.build_context(state, "2")
    witch_private = ctx["private_facts"]["witch"]

    assert witch_private is not None
    assert witch_private["antidote_used"] is True
    assert witch_private["current_victim_seat"] == 4
    assert witch_private["potion_history"] == [
        {"round": 1, "potion": "antidote", "target_seat": 3}
    ]
    text = ai_context.context_to_text(ctx)
    assert "解药：已使用" in text
    assert "今夜被刀：4号玩家" in text


def test_guard_context_carries_last_target() -> None:
    guard = _player("2", 2, C.GUARD, C.GOOD)
    guard["role_state"] = {"last_guard_target": "3"}
    state = _state([BASE_PLAYERS[0], guard, *BASE_PLAYERS[2:]])

    ctx = ai_context.build_context(state, "2")

    assert ctx["private_facts"]["last_guard_target_seat"] == 3
    assert "上轮守护：3号玩家（不可连守）" in ai_context.context_to_text(ctx)


def test_text_lists_alive_marks_and_votes() -> None:
    state = _state(
        BASE_PLAYERS,
        history={
            "rounds": [],
            "marks": [
                {
                    "player": "1",
                    "round": 1,
                    "identity_mark": {"identity": "平民", "reason": C.REASON_INTUITION},
                    "evaluation_marks": [
                        {
                            "target": "3",
                            "identity": C.IDENTITY_WOLF,
                            "reason": C.REASON_MARK_ANALYSIS,
                        }
                    ],
                }
            ],
            "votes": [[{"voter": "1", "target": "3"}, {"voter": "3", "target": "1"}]],
            "deaths": [
                {"pid": "3", "seat": 3, "cause": C.DEATH_EXILED, "round": 1, "relics": []}
            ],
        },
    )

    text = ai_context.context_to_text(ai_context.build_context(state, "4"))

    assert "第 2 轮，当前阶段：标记发言" in text
    assert "声称身份：平民（直觉判断）" in text
    assert "评价：3号玩家 = 狼人（标记分析）" in text
    assert "1号→3号，3号→1号" in text
    assert "3号玩家被放逐" in text
    assert "4号玩家（你）" in text
