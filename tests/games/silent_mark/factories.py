"""静夜标记测试用构造器。

规则内核的状态是普通 dict，这里提供最小构造器，避免每个测试文件各写一份。
"""

from __future__ import annotations

from typing import Any

from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812
from src.plugins.games.silent_mark.engine.roles import new_role_state
from src.plugins.games.silent_mark.engine.types import empty_history, empty_night_actions


def make_player(
    pid: str,
    role: str,
    *,
    seat: int | None = None,
    alive: bool = True,
    role_state: dict[str, Any] | None = None,
    items: list[dict[str, Any]] | None = None,
    nickname: str | None = None,
) -> dict[str, Any]:
    """造一个玩家。``seat`` 为 None 时由 ``make_state`` 按列表顺序编号。"""
    return {
        "pid": pid,
        "nickname": nickname or pid,
        "seat": seat,
        "role": role,
        "faction": C.ROLE_FACTION[role],
        "alive": alive,
        # 显式传入的 role_state 原样使用（不合并默认值），便于测"技能已用掉"的场景
        "role_state": dict(role_state) if role_state is not None else new_role_state(role),
        "items": list(items or []),
    }


def make_item(
    item_type: str, value: int | str | None = None, *, revealed: bool = False
) -> dict[str, Any]:
    """造一件物品。``value`` 省略时按类型给默认值（月光石是数字计数，天平徽章是字符串）。"""
    if value is None:
        value = 0 if item_type == C.MOONSTONE else ""
    return {"type": item_type, "value": value, "revealed": revealed}


def make_state(
    players: list[dict[str, Any]], **overrides: Any
) -> dict[str, Any]:
    """造一个对局状态（默认第 1 轮夜晚）。未指定座位的玩家按列表顺序编号。"""
    for index, player in enumerate(players):
        if player["seat"] is None:
            player["seat"] = index + 1

    state: dict[str, Any] = {
        "status": "playing",
        "round": 1,
        "phase": C.PHASE_NIGHT,
        "players": players,
        "night_actions": empty_night_actions(),
        "night_current_role": None,
        "marking_order": [],
        "marking_current": 0,
        "pending_triggers": [],
        "history": empty_history(),
        "winner": None,
        "win_condition": C.WIN_EDGE,
    }
    state.update(overrides)
    return state


def make_night(
    *,
    wolves_target: str | None = None,
    wolves_votes: dict[str, str] | None = None,
    guard_target: str | None = None,
    witch_action: str | None = None,
    witch_target: str | None = None,
    seer_target: str | None = None,
    gravedigger_target: str | None = None,
) -> dict[str, Any]:
    """造一份夜晚行动表（只填用得到的槽位）。"""
    night = empty_night_actions()
    if wolves_target is not None or wolves_votes is not None:
        night["wolves"] = {"target": wolves_target, "votes": dict(wolves_votes or {})}
    if guard_target is not None:
        night["guard"] = {"target": guard_target}
    if witch_action is not None:
        night["witch"] = {"action": witch_action, "target": witch_target}
    if seer_target is not None:
        night["seer"] = {"target": seer_target}
    if gravedigger_target is not None:
        night["gravedigger"] = {"target": gravedigger_target}
    return night
