"""深海任务：任务自动判定。

任务语义与提前胜负原则见 ``docs/games/deep-sea-mission.md``。
只使用公开信息：已打出的墩/牌、赢墩数、剩余墩数（手牌张数）、未出场牌数量。
不看各人手牌内容，不用跟花推演。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

from .cards import display_card, display_suit, suit_of, value_of


PREDICTION_TASK_IDS = {"T090", "T091"}
_SPECIAL_MISSIONS = {8, 12, 21, 23, 27}

_SUIT_TOTAL = {"pink": 9, "yellow": 9, "blue": 9, "green": 9, "sub": 4}
_COLOR_VALUE_TOTAL = 4
_COLORS = ("pink", "yellow", "blue", "green")

_TrickPred = Callable[[list[str], str], bool]


def task_needs_prediction(task: dict[str, Any]) -> bool:
    return str(task.get("id")) in PREDICTION_TASK_IDS


def remaining_tricks(state: dict[str, Any], *, final: bool = False) -> int:
    """剩余墩数 R。``final=True`` 视为出牌结束（调试后门「胜利」走这条）。

    有手牌时只看各手 **张数**（公开）；否则用人数推总墩数 − 已打墩数。
    """
    if final:
        return 0
    order = [int(x) for x in state.get("order", [])]
    hands = state.get("hands")
    if isinstance(hands, dict) and order and any(str(pid) in hands for pid in order):
        return min(len(hands.get(str(pid), [])) for pid in order)
    n = len(order)
    if n >= 3:
        total = 13 if n == 3 else 40 // n
        return max(0, total - len(state.get("trick_history", [])))
    return 0


def evaluate_tasks(state: dict[str, Any], *, final: bool = False) -> list[str]:
    """刷新已分配任务状态，返回本次变化说明。"""
    r = remaining_tricks(state, final=final)
    changes: list[str] = []
    for task in state.get("tasks", []):
        owner = task.get("assigned_to")
        if owner is None or task.get("failed") or task.get("completed"):
            continue
        result = _evaluate_one(state, task, int(owner), r)
        if result == "completed":
            task["completed"] = True
            changes.append(f"任务 {task.get('display_no', '?')} 自动完成：{task['text']}")
        elif result == "failed":
            task["failed"] = True
            changes.append(f"任务 {task.get('display_no', '?')} 判定失败：{task['text']}")
    return changes


def all_tasks_completed(state: dict[str, Any]) -> bool:
    tasks = state.get("tasks", [])
    return bool(tasks) and all(t.get("completed") for t in tasks)


def any_task_failed(state: dict[str, Any]) -> bool:
    return any(t.get("failed") for t in state.get("tasks", []))


def mission_locked_win(state: dict[str, Any]) -> bool:
    """整局是否已锁死胜利（全部任务完成，或无任务关约束锁死达成）。"""
    tasks = state.get("tasks") or []
    if tasks:
        return all_tasks_completed(state) and not any_task_failed(state)
    status, _ = evaluate_campaign_special(state)
    return status == "completed"


def evaluate_campaign_special(state: dict[str, Any], *, final: bool = False) -> tuple[str, str | None]:
    """无难度关约束。返回 ``(completed|failed|pending, 失败说明)``。"""
    if state.get("mode") != "campaign":
        return "pending", None
    no = state.get("mission", {}).get("no") if isinstance(state.get("mission"), dict) else None
    if no not in _SPECIAL_MISSIONS:
        return "pending", None
    r = remaining_tricks(state, final=final)
    if no in {8, 21}:
        value, label = (9, "9") if no == 8 else (1, "1")
        return _special_value_gap(state, value, label, r)
    if no == 12:
        return _special_no_pink_or_sub_lead(state, r)
    if no == 23:
        return _special_first_winner_lead(state, r)
    return _special_yellow5_last(state, r)


def _evaluate_one(state: dict[str, Any], task: dict[str, Any], owner: int, r: int) -> str:
    tid = str(task.get("id"))
    order = [int(x) for x in state.get("order", [])]
    counts = _trick_counts(state)
    owner_count = counts.get(owner, 0)
    won_cards = _won_cards(state, owner)
    won_tricks = _won_tricks(state, owner)
    last_no = _last_trick_no(state)
    captain = int(state.get("captain_id", 0))
    played = _all_played_cards(state)
    won_nos = [t["no"] for t in won_tricks]

    if tid == "T001":
        others = [counts.get(p, 0) for p in order if p != owner]
        return _more_than_each(owner_count, others, r)
    if tid == "T002":
        others = [counts.get(p, 0) for p in order if p != owner]
        return _cmp_lock(owner_count, sum(others), r, more=True)
    if tid == "T003":
        others = [counts.get(p, 0) for p in order if p != owner]
        return _fewer_than_each(owner_count, others, r)
    if tid == "T004":
        if owner == captain:
            return "failed"
        return _cmp_lock(owner_count, counts.get(captain, 0), r, more=True)
    if tid == "T005":
        if owner == captain:
            return "failed"
        return _fewer_than_one(owner_count, counts.get(captain, 0), r)
    if tid == "T006":
        if owner == captain:
            return "failed"
        return _equal_tricks(owner_count, counts.get(captain, 0), r)

    if tid == "T007":
        return _exists_trick(
            won_tricks,
            lambda cards, _w: _no_sub(cards) and all(value_of(c) < 7 for c in cards),
            r,
        )
    if tid == "T008":
        return _exists_trick(
            won_tricks,
            lambda cards, _w: _no_sub(cards) and all(value_of(c) > 5 for c in cards),
            r,
        )
    if tid in {"T009", "T010", "T011", "T015"}:
        target = {"T009": 6, "T010": 5, "T011": 3, "T015": 2}[tid]
        # 潜艇牌同样是「点数 target」牌，也能赢下含该点数的墩，必须计入剩余机会
        extra = _winnable_color_value(state, target, r)
        if r > 0 and f"sub:{target}" not in played:
            extra += 1
        return _exists_trick(
            won_tricks,
            lambda cards, _w, t=target: any(value_of(c) == t for c in cards),
            r,
            key_unplayed=extra,
        )
    if tid == "T012":
        return _exists_trick(
            won_tricks,
            lambda cards, winner_card: value_of(winner_card) == 7
            and any(value_of(c) == 5 for c in cards if c != winner_card),
            r,
            key_unplayed=_winnable_color_value(state, 7, r)
            + _sub_unplayed(played, 7, r),
        )
    if tid == "T013":
        return _exists_trick(
            won_tricks,
            lambda cards, winner_card: value_of(winner_card) == 4
            and any(value_of(c) == 8 for c in cards if c != winner_card),
            r,
            key_unplayed=_winnable_color_value(state, 4, r)
            + _sub_unplayed(played, 4, r),
        )
    if tid == "T014":
        found = _exists_trick(
            won_tricks,
            lambda cards, _w: sum(1 for c in cards if value_of(c) == 6) >= 2,
            r,
        )
        if found == "completed":
            return found
        if _winnable_color_value(state, 6, r) < 2:
            return "failed"
        return found

    if tid in _SINGLE_CARD_TASKS:
        return _has_cards(won_cards, [_SINGLE_CARD_TASKS[tid]], played, r)
    if tid in _CARD_SET_TASKS:
        return _has_cards(won_cards, _CARD_SET_TASKS[tid], played, r)
    if tid in {"T020", "T024"}:
        value = 3 if tid == "T020" else 9
        return _at_least(
            sum(1 for c in won_cards if suit_of(c) != "sub" and value_of(c) == value),
            4,
            _winnable_color_value(state, value, r),
            r,
        )
    if tid in {"T021", "T022", "T023"}:
        value, amount = {"T021": (5, 3), "T022": (9, 3), "T023": (7, 2)}[tid]
        return _at_least(
            sum(1 for c in won_cards if suit_of(c) != "sub" and value_of(c) == value),
            amount,
            _winnable_color_value(state, value, r),
            r,
        )
    if tid == "T025":
        return _exact_count(
            sum(1 for c in won_cards if suit_of(c) != "sub" and value_of(c) == 6),
            3,
            _winnable_color_value(state, 6, r),
        )
    if tid == "T026":
        return _exact_count(
            sum(1 for c in won_cards if suit_of(c) != "sub" and value_of(c) == 9),
            2,
            _winnable_color_value(state, 9, r),
        )
    if tid == "T036":
        return _green2_last(state, owner, r, last_no)

    if tid == "T037":
        return _exact_two_suits(state, won_cards, "pink", 1, "green", 1, r)
    if tid == "T038":
        return _at_least(_suit_count(won_cards, "yellow"), 7, _winnable_suit(state, "yellow", r), r)
    if tid == "T039":
        return _at_least(_suit_count(won_cards, "pink"), 5, _winnable_suit(state, "pink", r), r)
    if tid == "T040":
        return _exact_count(_suit_count(won_cards, "green"), 2, _winnable_suit(state, "green", r))
    if tid == "T041":
        return _exact_count(_suit_count(won_cards, "blue"), 2, _winnable_suit(state, "blue", r))
    if tid == "T042":
        return _exact_count(_suit_count(won_cards, "pink"), 1, _winnable_suit(state, "pink", r))
    if tid == "T043":
        return _avoid_suit(won_cards, state, {"pink"}, r)
    if tid == "T044":
        if all(_suit_count(won_cards, suit) >= 1 for suit in _COLORS):
            return "completed"
        for suit in _COLORS:
            if _suit_count(won_cards, suit) + _winnable_suit(state, suit, r) < 1:
                return "failed"
        return "failed" if r == 0 else "pending"
    if tid == "T045":
        if any(_suit_count(won_cards, suit) == 9 for suit in _COLORS):
            return "completed"
        if all(_suit_count(won_cards, suit) + _winnable_suit(state, suit, r) < 9 for suit in _COLORS):
            return "failed"
        return "failed" if r == 0 else "pending"

    if tid == "T046":
        return _exists_trick(
            won_tricks,
            lambda cards, _w: _no_sub(cards) and all(value_of(c) % 2 == 0 for c in cards),
            r,
        )
    if tid == "T047":
        return _exists_trick(
            won_tricks,
            lambda cards, _w: _no_sub(cards) and all(value_of(c) % 2 == 1 for c in cards),
            r,
        )
    if tid == "T048":
        threshold = {3: 23, 4: 28, 5: 31}[len(order)]
        return _exists_trick(
            won_tricks,
            lambda cards, _w, th=threshold: _no_sub(cards) and sum(value_of(c) for c in cards) > th,
            r,
        )
    if tid == "T049":
        threshold = {3: 8, 4: 12, 5: 16}[len(order)]
        return _exists_trick(
            won_tricks,
            lambda cards, _w, th=threshold: _no_sub(cards) and sum(value_of(c) for c in cards) < th,
            r,
        )
    if tid == "T050":
        return _exists_trick(
            won_tricks,
            lambda cards, _w: sum(value_of(c) for c in cards) in {22, 23},
            r,
        )

    if tid == "T051":
        return _exact_count(_suit_count(won_cards, "sub"), 1, _winnable_suit(state, "sub", r))
    if tid == "T052":
        return _only_sub(won_cards, played, 1, r)
    if tid == "T053":
        return _only_sub(won_cards, played, 2, r)
    if tid == "T054":
        return _has_cards(won_cards, ["sub:3"], played, r)
    if tid == "T055":
        return _exact_count(_suit_count(won_cards, "sub"), 2, _winnable_suit(state, "sub", r))
    if tid == "T056":
        return _exact_count(_suit_count(won_cards, "sub"), 3, _winnable_suit(state, "sub", r))
    if tid == "T057":
        return _avoid_suit(won_cards, state, {"sub"}, r)
    if tid == "T058":
        key = 0 if "pink:7" in played or _winnable_suit(state, "sub", r) == 0 else 1
        return _exists_trick(
            won_tricks,
            lambda cards, winner_card: suit_of(winner_card) == "sub" and "pink:7" in cards,
            r,
            key_unplayed=key,
        )
    if tid == "T059":
        key = 0 if "green:9" in played or _winnable_suit(state, "sub", r) == 0 else 1
        return _exists_trick(
            won_tricks,
            lambda cards, winner_card: suit_of(winner_card) == "sub" and "green:9" in cards,
            r,
            key_unplayed=key,
        )

    if tid == "T060":
        return _avoid_lead(state, owner, {"pink", "yellow", "blue"}, r)
    if tid == "T061":
        return _avoid_lead(state, owner, {"pink", "green"}, r)
    if tid in _NO_SUIT_TASKS:
        return _avoid_suit(won_cards, state, _NO_SUIT_TASKS[tid], r)
    if tid in _NO_VALUE_TASKS:
        return _avoid_values(won_cards, state, _NO_VALUE_TASKS[tid], r)
    if tid == "T071":
        return _avoid_first_n(won_tricks, 4, last_no, r)
    if tid == "T072":
        return _avoid_first_n(won_tricks, 3, last_no, r)
    if tid == "T073":
        return _avoid_first_n(won_tricks, 5, last_no, r)
    if tid == "T074":
        if owner_count > 0:
            return "failed"
        return "completed" if r == 0 else "pending"
    if tid == "T075":
        if _has_consecutive(won_nos, 2):
            return "failed"
        return "completed" if r == 0 else "pending"

    if tid == "T076":
        if r > 0:
            return "pending"
        return _bool_result(any(t["no"] == last_no for t in won_tricks), r)
    if tid == "T077":
        return _win_first_n(won_nos, 3, last_no)
    if tid == "T078":
        return _win_first_n(won_nos, 2, last_no)
    if tid == "T079":
        return _win_first_n(won_nos, 1, last_no)
    if tid == "T080":
        if last_no >= 1 and 1 not in won_nos:
            return "failed"
        if r > 0:
            return "pending"
        return "completed" if 1 in won_nos and last_no in won_nos else "failed"
    if tid == "T081":
        if r > 0:
            return "failed" if owner_count > 0 else "pending"
        return "completed" if won_nos == [last_no] else "failed"
    if tid == "T082":
        if last_no >= 1 and 1 not in won_nos:
            return "failed"
        if owner_count > 1:
            return "failed"
        if 1 in won_nos and owner_count == 1:
            return "completed" if r == 0 else "pending"
        return "failed" if r == 0 else "pending"
    if tid == "T083":
        return _exact_tricks(owner_count, 1, r)
    if tid == "T084":
        return _exact_tricks(owner_count, 2, r)
    if tid == "T085":
        return _at_least_consecutive(won_nos, 2, last_no, r)
    if tid == "T086":
        return _at_least_consecutive(won_nos, 3, last_no, r)
    if tid == "T087":
        return _exact_tricks(owner_count, 4, r)
    if tid == "T088":
        return _exact_consecutive(won_nos, 3, last_no, r)
    if tid == "T089":
        return _exact_consecutive(won_nos, 2, last_no, r)
    if tid in {"T090", "T091"}:
        prediction = task.get("prediction")
        if prediction is None:
            return "pending"
        return _exact_tricks(owner_count, int(prediction), r)

    if tid == "T092":
        return _equal_suits_positive(state, won_cards, "pink", "yellow", r)
    if tid == "T093":
        return _exists_trick(
            won_tricks,
            lambda cards, _w: _suit_count(cards, "green") == _suit_count(cards, "yellow") > 0,
            r,
        )
    if tid == "T094":
        return _exists_trick(
            won_tricks,
            lambda cards, _w: _suit_count(cards, "pink") == _suit_count(cards, "blue") > 0,
            r,
        )
    if tid == "T095":
        return _suit_more(state, won_cards, "yellow", "blue", r)
    if tid == "T096":
        return _suit_more(state, won_cards, "pink", "green", r)

    return "pending"


_SINGLE_CARD_TASKS = {
    "T016": "pink:3",
    "T017": "yellow:1",
    "T018": "blue:4",
    "T019": "green:6",
}

_CARD_SET_TASKS = {
    "T027": ["blue:1", "blue:2", "blue:3"],
    "T028": ["blue:6", "yellow:7"],
    "T029": ["pink:5", "yellow:6"],
    "T030": ["green:5", "blue:8"],
    "T031": ["blue:5", "pink:8"],
    "T032": ["pink:9", "yellow:8"],
    "T033": ["pink:1", "green:7"],
    "T034": ["yellow:9", "blue:7"],
    "T035": ["green:3", "yellow:4", "yellow:5"],
}

_NO_SUIT_TASKS = {
    "T062": {"green"},
    "T063": {"yellow"},
    "T064": {"pink", "blue"},
    "T065": {"yellow", "green"},
}

_NO_VALUE_TASKS = {
    "T066": {8, 9},
    "T067": {9},
    "T068": {5},
    "T069": {1},
    "T070": {1, 2, 3},
}


def _more_than_each(owner: int, others: list[int], r: int) -> str:
    if not others:
        return "pending"
    mx = max(others)
    if owner > mx + r:
        return "completed"
    if owner + r <= mx:
        return "failed"
    return "pending"


def _fewer_than_each(owner: int, others: list[int], r: int) -> str:
    """领取者要严格少于「每一个」他人。

    打平不等于失败：别人还会继续吃墩，只要那些人最终都超过领取者即可。
    只有把剩余 R 墩全用来抬人、仍抬不动（有人注定不超过领取者）时才锁死失败。
    """
    if not others:
        return "pending"
    if owner + r < min(others):
        return "completed"
    if _raise_needed(owner, others) > r:
        return "failed"
    return "pending"


def _fewer_than_one(owner: int, other: int, r: int) -> str:
    if owner >= other + r:
        return "failed"
    if owner + r < other:
        return "completed"
    return "pending"


def _raise_needed(owner: int, others: list[int]) -> int:
    """让所有「不高于领取者」的人都反超，至少需要的墩数。"""
    return sum(max(0, owner - n + 1) for n in others)


def _cmp_lock(owner: int, other: int, r: int, *, more: bool) -> str:
    if more:
        if owner > other + r:
            return "completed"
        if owner + r <= other:
            return "failed"
        return "pending"
    return _fewer_than_one(owner, other, r)


def _equal_tricks(owner: int, other: int, r: int) -> str:
    if abs(owner - other) > r:
        return "failed"
    if r == 0:
        return "completed" if owner == other else "failed"
    return "pending"


def _at_least(current: int, need: int, extra: int, r: int) -> str:
    if current >= need:
        return "completed"
    if current + extra < need:
        return "failed"
    return "failed" if r == 0 else "pending"


def _exact_count(current: int, target: int, extra: int) -> str:
    if current > target:
        return "failed"
    if current + extra < target:
        return "failed"
    if current == target and extra == 0:
        return "completed"
    return "pending"


def _exact_tricks(owner_count: int, target: int, r: int) -> str:
    if owner_count > target:
        return "failed"
    if owner_count + r < target:
        return "failed"
    if owner_count == target and r == 0:
        return "completed"
    return "pending"


def _win_first_n(won_nos: list[int], n: int, last_no: int) -> str:
    won_set = set(won_nos)
    for k in range(1, n + 1):
        if k <= last_no and k not in won_set:
            return "failed"
    if all(k in won_set for k in range(1, n + 1)):
        return "completed"
    return "pending"


def _avoid_first_n(won_tricks: list[dict[str, Any]], n: int, last_no: int, r: int) -> str:
    if any(t["no"] <= n for t in won_tricks):
        return "failed"
    if last_no >= n or r == 0:
        return "completed"
    return "pending"


def _avoid_lead(state: dict[str, Any], owner: int, forbidden: set[str], r: int) -> str:
    if any(_lead_suit(t) in forbidden for t in _opened_tricks(state, owner)):
        return "failed"
    return "completed" if r == 0 else "pending"


def _avoid_suit(won_cards: list[str], state: dict[str, Any], suits: set[str], r: int) -> str:
    if any(suit_of(c) in suits for c in won_cards):
        return "failed"
    extra = sum(_winnable_suit(state, s, r) for s in suits)
    if extra == 0:
        return "completed"
    return "completed" if r == 0 else "pending"


def _avoid_values(won_cards: list[str], state: dict[str, Any], values: set[int], r: int) -> str:
    if any(suit_of(c) != "sub" and value_of(c) in values for c in won_cards):
        return "failed"
    extra = sum(_winnable_color_value(state, v, r) for v in values)
    if extra == 0:
        return "completed"
    return "completed" if r == 0 else "pending"


def _at_least_consecutive(won_nos: list[int], need: int, last_no: int, r: int) -> str:
    mx = _max_consecutive(won_nos)
    if mx >= need:
        return "completed"
    end_run = _run_ending_at(set(won_nos), last_no)
    if max(mx, end_run + r) < need:
        return "failed"
    return "failed" if r == 0 else "pending"


def _exact_consecutive(won_nos: list[int], target: int, last_no: int, r: int) -> str:
    mx = _max_consecutive(won_nos)
    end_run = _run_ending_at(set(won_nos), last_no)
    if mx > target:
        return "failed"
    if max(mx, end_run + r) < target:
        return "failed"
    if mx == target and end_run + r <= target:
        return "completed"
    return "pending"


def _exact_two_suits(
    state: dict[str, Any],
    won_cards: list[str],
    a: str,
    na: int,
    b: str,
    nb: int,
    r: int,
) -> str:
    ca, cb = _suit_count(won_cards, a), _suit_count(won_cards, b)
    if ca > na or cb > nb:
        return "failed"
    extra_a, extra_b = _winnable_suit(state, a, r), _winnable_suit(state, b, r)
    if ca + extra_a < na or cb + extra_b < nb:
        return "failed"
    if ca == na and cb == nb and extra_a == 0 and extra_b == 0:
        return "completed"
    return "pending"


def _equal_suits_positive(
    state: dict[str, Any],
    won_cards: list[str],
    a: str,
    b: str,
    r: int,
) -> str:
    ca, cb = _suit_count(won_cards, a), _suit_count(won_cards, b)
    extra_a, extra_b = _winnable_suit(state, a, r), _winnable_suit(state, b, r)
    if extra_a == 0 and ca == 0:
        return "failed"
    if extra_b == 0 and cb == 0:
        return "failed"
    lo_a, hi_a = ca, ca + extra_a
    lo_b, hi_b = cb, cb + extra_b
    overlap_hi = min(hi_a, hi_b)
    overlap_lo = max(lo_a, lo_b, 1)
    if overlap_lo > overlap_hi:
        return "failed"
    if ca == cb > 0 and extra_a == 0 and extra_b == 0:
        return "completed"
    return "pending"


def _suit_more(state: dict[str, Any], won_cards: list[str], more: str, less: str, r: int) -> str:
    cm, cl = _suit_count(won_cards, more), _suit_count(won_cards, less)
    extra_m, extra_l = _winnable_suit(state, more, r), _winnable_suit(state, less, r)
    if cm > cl + extra_l:
        return "completed"
    if cm + extra_m <= cl:
        return "failed"
    return "pending"


def _only_sub(won_cards: list[str], played: list[str], value: int, r: int) -> str:
    subs = set(_sub_values(won_cards))
    if any(v != value for v in subs):
        return "failed"
    target = f"sub:{value}"
    if value not in subs:
        if target in played or r == 0:
            return "failed"
        return "pending"
    extra = 0 if r == 0 else max(0, _SUIT_TOTAL["sub"] - sum(1 for c in played if suit_of(c) == "sub"))
    if extra == 0:
        return "completed"
    return "pending"


def _green2_last(state: dict[str, Any], owner: int, r: int, last_no: int) -> str:
    appeared_no: int | None = None
    appeared_winner: int | None = None
    for trick in state.get("trick_history", []):
        cards = [str(p["card"]) for p in trick.get("plays", [])]
        if "green:2" in cards:
            appeared_no = int(trick["no"])
            appeared_winner = int(trick["winner"])
            break
    if r > 0:
        return "failed" if appeared_no is not None else "pending"
    if appeared_no == last_no and appeared_winner == owner:
        return "completed"
    return "failed"


def _has_cards(cards: list[str], required: list[str], played: list[str], r: int) -> str:
    have = Counter(cards)
    need = Counter(required)
    if all(have[card] >= count for card, count in need.items()):
        return "completed"
    played_set = set(played)
    for card, count in need.items():
        if have[card] >= count:
            continue
        if card in played_set or r == 0:
            return "failed"
    return "pending"


def _sub_unplayed(played: list[str], value: int, r: int) -> int:
    """点数 value 的潜艇牌是否还可能出场（潜艇可当该点数赢墩）。"""
    if r == 0 or value > _SUIT_TOTAL["sub"]:
        return 0
    return 0 if f"sub:{value}" in played else 1


def _exists_trick(
    won_tricks: list[dict[str, Any]],
    predicate: _TrickPred,
    r: int,
    *,
    key_unplayed: int | None = None,
) -> str:
    for trick in won_tricks:
        if predicate(trick["cards"], trick["winner_card"]):
            return "completed"
    if key_unplayed == 0:
        return "failed"
    return "failed" if r == 0 else "pending"


def _bool_result(value: bool, r: int = 0) -> str:
    if value:
        return "completed"
    return "failed" if r == 0 else "pending"


def _special_value_gap(state: dict[str, Any], value: int, label: str, r: int) -> tuple[str, str | None]:
    counts = _value_won_counts(state, value)
    if len(counts) < 2:
        return "pending", None
    nums = list(counts.values())
    hi_seat = max(counts, key=lambda s: counts[s])
    lo_seat = min(counts, key=lambda s: counts[s])
    gap = counts[hi_seat] - counts[lo_seat]
    if gap >= 2:
        return "failed", f"违反约束：有人赢得的 {label} 比别人多 2 张及以上"
    extra = 0 if r == 0 else max(0, _COLOR_VALUE_TOTAL - sum(nums))
    if max(nums) + extra - min(nums) < 2:
        return "completed", None
    return "pending", None


def _special_no_pink_or_sub_lead(state: dict[str, Any], r: int) -> tuple[str, str | None]:
    for trick in state.get("trick_history", []):
        plays = trick.get("plays") or []
        if not plays:
            continue
        first = str(plays[0]["card"])
        if suit_of(first) in {"pink", "sub"}:
            return "failed", f"违反约束：第 {trick['no']} 墩用禁色开墩（禁止粉牌或潜艇开墩）"
    return ("completed", None) if r == 0 else ("pending", None)


def _special_first_winner_lead(state: dict[str, Any], r: int) -> tuple[str, str | None]:
    history = state.get("trick_history", [])
    if not history:
        return "pending", None
    first_winner = int(history[0]["winner"])
    order = [int(x) for x in state.get("order", [])]
    counts = {pid: 0 for pid in order}
    for trick in history:
        counts[int(trick["winner"])] = counts.get(int(trick["winner"]), 0) + 1
        fw = counts.get(first_winner, 0)
        for seat, n in counts.items():
            if seat != first_winner and n >= fw:
                return "failed", "违反约束：首墩赢家未能始终严格领先赢墩数"
    others = [n for s, n in counts.items() if s != first_winner]
    mx = max(others) if others else 0
    fw = counts.get(first_winner, 0)
    if fw > mx + r:
        return "completed", None
    return "pending", None


def _special_yellow5_last(state: dict[str, Any], r: int) -> tuple[str, str | None]:
    history = state.get("trick_history", [])
    appeared = False
    for trick in history:
        for play in trick.get("plays", []):
            if str(play["card"]) == "yellow:5":
                appeared = True
                break
        if appeared:
            break
    if r > 0:
        if appeared:
            return "failed", "违反约束：黄5已打出，但不是最后一墩的最后一张"
        return "pending", None
    if not history:
        return "failed", "违反约束：黄5须为最后一墩的最后一张牌"
    final_card = str(history[-1]["plays"][-1]["card"])
    if final_card == "yellow:5":
        return "completed", None
    return "failed", f"违反约束：最后一墩的最后一张牌应为黄5"


def _value_won_counts(state: dict[str, Any], value: int) -> dict[int, int]:
    order = [int(x) for x in state.get("order", [])]
    counts = {pid: 0 for pid in order}
    history = state.get("trick_history") or []
    if history and any(t.get("plays") for t in history):
        for trick in history:
            winner = int(trick["winner"])
            for play in trick.get("plays", []):
                card = str(play["card"])
                if suit_of(card) != "sub" and value_of(card) == value:
                    counts[winner] = counts.get(winner, 0) + 1
        return counts
    won = state.get("won_tricks") or {}
    for seat in order:
        counts[seat] = sum(
            1
            for t in won.get(str(seat), [])
            for c in t.get("cards", [])
            if value_of(str(c)) == value
        )
    return counts


def _all_played_cards(state: dict[str, Any]) -> list[str]:
    cards: list[str] = []
    for trick in state.get("trick_history", []):
        cards.extend(str(p["card"]) for p in trick.get("plays", []))
    if cards:
        return cards
    for tricks in (state.get("won_tricks") or {}).values():
        for trick in tricks:
            cards.extend(str(c) for c in trick.get("cards", []))
    return cards


def _unplayed_suit(state: dict[str, Any], suit: str) -> int:
    played = sum(1 for c in _all_played_cards(state) if suit_of(c) == suit)
    return max(0, _SUIT_TOTAL[suit] - played)


def _unplayed_color_value(state: dict[str, Any], value: int) -> int:
    played = sum(
        1
        for c in _all_played_cards(state)
        if suit_of(c) != "sub" and value_of(c) == value
    )
    return max(0, _COLOR_VALUE_TOTAL - played)


def _winnable_suit(state: dict[str, Any], suit: str, r: int) -> int:
    return 0 if r == 0 else _unplayed_suit(state, suit)


def _winnable_color_value(state: dict[str, Any], value: int, r: int) -> int:
    return 0 if r == 0 else _unplayed_color_value(state, value)


def _trick_counts(state: dict[str, Any]) -> dict[int, int]:
    counts = {int(pid): 0 for pid in state.get("order", [])}
    for trick in state.get("trick_history", []):
        winner = int(trick["winner"])
        counts[winner] = counts.get(winner, 0) + 1
    return counts


def _won_cards(state: dict[str, Any], owner: int) -> list[str]:
    cards: list[str] = []
    for trick in state.get("trick_history", []):
        if int(trick["winner"]) == owner:
            cards.extend(str(play["card"]) for play in trick.get("plays", []))
    if cards:
        return cards
    for trick in (state.get("won_tricks") or {}).get(str(owner), []):
        cards.extend(str(c) for c in trick.get("cards", []))
    return cards


def _won_tricks(state: dict[str, Any], owner: int) -> list[dict[str, Any]]:
    tricks: list[dict[str, Any]] = []
    for trick in state.get("trick_history", []):
        if int(trick["winner"]) != owner:
            continue
        plays = trick.get("plays", [])
        if not plays:
            continue
        winner_card = next(str(p["card"]) for p in plays if int(p["player"]) == owner)
        tricks.append(
            {
                "no": int(trick["no"]),
                "cards": [str(p["card"]) for p in plays],
                "winner_card": winner_card,
                "lead_card": str(plays[0]["card"]),
            }
        )
    return tricks


def _opened_tricks(state: dict[str, Any], owner: int) -> list[dict[str, Any]]:
    tricks: list[dict[str, Any]] = []
    for trick in state.get("trick_history", []):
        plays = trick.get("plays", [])
        if not plays or int(plays[0]["player"]) != owner:
            continue
        winner_card = next(str(p["card"]) for p in plays if int(p["player"]) == int(trick["winner"]))
        tricks.append(
            {
                "no": int(trick["no"]),
                "cards": [str(p["card"]) for p in plays],
                "winner_card": winner_card,
                "lead_card": str(plays[0]["card"]),
            }
        )
    return tricks


def _last_trick_no(state: dict[str, Any]) -> int:
    history = state.get("trick_history", [])
    if not history:
        return 0
    return max(int(t["no"]) for t in history)


def _no_sub(cards: list[str]) -> bool:
    return all(suit_of(c) != "sub" for c in cards)


def _suit_count(cards: list[str], suit: str) -> int:
    return sum(1 for c in cards if suit_of(c) == suit)


def _sub_values(cards: list[str]) -> list[int]:
    return [value_of(c) for c in cards if suit_of(c) == "sub"]


def _lead_suit(trick: dict[str, Any]) -> str:
    return suit_of(str(trick["lead_card"]))


def _has_consecutive(numbers: list[int], amount: int) -> bool:
    return _max_consecutive(numbers) >= amount


def _run_ending_at(won_set: set[int], last_no: int) -> int:
    if last_no not in won_set:
        return 0
    run = 0
    n = last_no
    while n in won_set:
        run += 1
        n -= 1
    return run


def _max_consecutive(numbers: list[int]) -> int:
    if not numbers:
        return 0
    nums = sorted(set(numbers))
    best = run = 1
    prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            run += 1
        else:
            run = 1
        best = max(best, run)
        prev = n
    return best


def task_progress(
    state: dict[str, Any],
    task: dict[str, Any],
    *,
    owner_label: str = "你",
) -> str | None:
    """未完成任务的一行进度提示；无进度可报返回 None。

    只使用公开信息（已打出并赢下的牌、赢墩数），不泄露任何手牌。
    与 ``_evaluate_one`` 的判定口径保持一致，仅做展示、不参与胜负。

    ``owner_label`` 用于指代任务领取者：群内公开面板与 CLI 控制台会被非领取者看到，
    调用方应传昵称，不能写死「你」。
    """
    tid = str(task.get("id"))
    owner = task.get("assigned_to")
    if owner is None:
        return None
    owner = int(owner)
    order = [int(x) for x in state.get("order", [])]
    won_cards = _won_cards(state, owner)
    won_tricks = _won_tricks(state, owner)
    counts = _trick_counts(state)
    owner_count = counts.get(owner, 0)
    r = remaining_tricks(state)

    def at_least(current: int, need: int, label: str) -> str:
        return f"{label} {current}/{need}"

    def exact(current: int, target: int, label: str) -> str:
        return f"{label} {current}/{target}（超 {target} 失败）"

    def suit_label(suit: str) -> str:
        return display_suit(suit)

    def value_count(value: int) -> int:
        return sum(1 for c in won_cards if suit_of(c) != "sub" and value_of(c) == value)

    if tid in {"T020", "T024"}:
        value = 3 if tid == "T020" else 9
        return at_least(value_count(value), 4, f"{value}点")
    if tid in {"T021", "T022", "T023"}:
        value, amount = {"T021": (5, 3), "T022": (9, 3), "T023": (7, 2)}[tid]
        return at_least(value_count(value), amount, f"{value}点")
    if tid in {"T025", "T026"}:
        value, target = {"T025": (6, 3), "T026": (9, 2)}[tid]
        return exact(value_count(value), target, f"{value}点")

    if tid in {"T038", "T039"}:
        suit, need = {"T038": ("yellow", 7), "T039": ("pink", 5)}[tid]
        return at_least(_suit_count(won_cards, suit), need, suit_label(suit))
    if tid in {"T040", "T041", "T042"}:
        suit, target = {"T040": ("green", 2), "T041": ("blue", 2), "T042": ("pink", 1)}[tid]
        return exact(_suit_count(won_cards, suit), target, suit_label(suit))

    if tid == "T037":
        return (
            f"{suit_label('pink')} {_suit_count(won_cards, 'pink')}/1 · "
            f"{suit_label('green')} {_suit_count(won_cards, 'green')}/1（各超 1 失败）"
        )
    if tid == "T044":
        return " ".join(f"{suit_label(s)}{_suit_count(won_cards, s)}" for s in _COLORS)
    if tid == "T045":
        return " ".join(f"{suit_label(s)}{_suit_count(won_cards, s)}" for s in _COLORS) + " /9"
    if tid == "T092":
        return (
            f"{suit_label('pink')} {_suit_count(won_cards, 'pink')} · "
            f"{suit_label('yellow')} {_suit_count(won_cards, 'yellow')}"
        )
    if tid in {"T095", "T096"}:
        more, less = {"T095": ("yellow", "blue"), "T096": ("pink", "green")}[tid]
        return (
            f"{suit_label(more)} {_suit_count(won_cards, more)} · "
            f"{suit_label(less)} {_suit_count(won_cards, less)}"
        )

    if tid in {"T051", "T055", "T056"}:
        target = {"T051": 1, "T055": 2, "T056": 3}[tid]
        return exact(_suit_count(won_cards, "sub"), target, suit_label("sub"))

    if tid in _CARD_SET_TASKS:
        return " ".join(
            f"{display_card(c)}{'✅' if c in won_cards else '□'}" for c in _CARD_SET_TASKS[tid]
        )

    if tid in {"T090", "T091"}:
        prediction = task.get("prediction")
        if prediction is None:
            return None
        return f"已赢 {owner_count} / 预测 {int(prediction)}"

    # ---- P1：墩数 / 连续 / 对比类 ----
    if tid == "T001":
        others = [counts.get(p, 0) for p in order if p != owner]
        top = max(others) if others else 0
        return f"{owner_label} {owner_count} · 其他人最多 {top}（需更多）"
    if tid == "T002":
        others = [counts.get(p, 0) for p in order if p != owner]
        return f"{owner_label} {owner_count} · 其他人合计 {sum(others)}（需更多）"
    if tid == "T003":
        others = [counts.get(p, 0) for p in order if p != owner]
        low = min(others) if others else 0
        return f"{owner_label} {owner_count} · 其他人最少 {low}（需更少）"
    if tid in {"T004", "T005", "T006"}:
        captain = int(state.get("captain_id", 0))
        if owner == captain:
            return None
        op = {"T004": "（需更多）", "T005": "（需更少）", "T006": "（需相同）"}[tid]
        return f"{owner_label} {owner_count} · 队长 {counts.get(captain, 0)} {op}"
    if tid in {"T083", "T084", "T087"}:
        target = {"T083": 1, "T084": 2, "T087": 4}[tid]
        return f"已赢 {owner_count}/{target}（超 {target} 失败）"
    if tid in {"T085", "T086"}:
        need = {"T085": 2, "T086": 3}[tid]
        won_nos = [t["no"] for t in won_tricks]
        run = _run_ending_at(set(won_nos), _last_trick_no(state))
        best = _max_consecutive(won_nos)
        return f"最长连赢 {best}/{need} · 当前 {run}"
    if tid in {"T088", "T089"}:
        target = {"T088": 3, "T089": 2}[tid]
        won_nos = [t["no"] for t in won_tricks]
        run = _run_ending_at(set(won_nos), _last_trick_no(state))
        best = _max_consecutive(won_nos)
        return f"最长连赢 {best}/{target} · 当前 {run}（超 {target} 失败）"
    if tid == "T075":
        won_nos = [t["no"] for t in won_tricks]
        run = _run_ending_at(set(won_nos), _last_trick_no(state))
        best = _max_consecutive(won_nos)
        return f"最长连赢 {best} · 当前 {run}"
    if tid in {"T071", "T072", "T073"}:
        n = {"T071": 4, "T072": 3, "T073": 5}[tid]
        last_no = _last_trick_no(state)
        return f"已忍 {min(last_no, n)}/{n} 墩"
    if tid in _SINGLE_CARD_TASKS:
        card = _SINGLE_CARD_TASKS[tid]
        if card in won_cards:
            return f"{display_card(card)} 已赢"
        if card in _all_played_cards(state):
            return f"{display_card(card)} 未赢到"
        return f"{display_card(card)} 未打出"

    # ---- P2：剩余机会 / 威胁提示 ----
    if tid in {"T007", "T008", "T012", "T013", "T014", "T046", "T047", "T048", "T049", "T050", "T058", "T059", "T093", "T094"}:
        return f"还剩 {r} 墩"
    if tid in {"T009", "T010", "T011", "T015"}:
        value = {"T009": 6, "T010": 5, "T011": 3, "T015": 2}[tid]
        got = sum(
            1
            for t in won_tricks
            if any(suit_of(c) != "sub" and value_of(c) == value for c in t["cards"])
        )
        return f"含{value}的墩 {got}/1"
    if tid in _NO_SUIT_TASKS or tid in {"T043", "T057"}:
        suits = _NO_SUIT_TASKS.get(tid) or {"T043": {"pink"}, "T057": {"sub"}}[tid]
        left = sum(_unplayed_suit(state, s) for s in suits)
        return f"未打出 {left} 张"
    if tid in _NO_VALUE_TASKS:
        left = sum(_unplayed_color_value(state, v) for v in _NO_VALUE_TASKS[tid])
        return f"未打出 {left} 张"
    if tid in {"T060", "T061"}:
        opened = _opened_tricks(state, owner)
        return f"已开墩 {len(opened)} 次"
    if tid in {"T077", "T078", "T079"}:
        n = {"T077": 3, "T078": 2, "T079": 1}[tid]
        won_nos = [t["no"] for t in won_tricks]
        got = [k for k in range(1, n + 1) if k in won_nos]
        return f"前{n}墩 {len(got)}/{n}"
    if tid == "T080":
        won_nos = [t["no"] for t in won_tricks]
        total = _last_trick_no(state) + r
        f1 = "✅" if 1 in won_nos else "□"
        fl = "✅" if total in won_nos else "□"
        return f"第1墩 {f1} · 第{total}墩 {fl}"
    if tid == "T082":
        won_nos = [t["no"] for t in won_tricks]
        return f"第1墩 {'✅' if 1 in won_nos else '□'} · 已赢 {owner_count}/1（超 1 失败）"
    if tid == "T076":
        return f"还剩 {r} 墩"
    if tid in {"T052", "T053"}:
        value = 1 if tid == "T052" else 2
        subs = set(_sub_values(won_cards))
        others = sum(1 for v in subs if v != value)
        got = 1 if value in subs else 0
        return f"潜艇{value} {got}/1 · 其他潜艇 {others}"
    if tid == "T054":
        card = "sub:3"
        if card in won_cards:
            return "潜艇3 已赢"
        if card in _all_played_cards(state):
            return "潜艇3 未赢到"
        return "潜艇3 未打出"

    return None
