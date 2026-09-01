"""深海任务：任务自动判定。"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .cards import suit_of, value_of


PREDICTION_TASK_IDS = {"T090", "T091"}
FINAL_ONLY_TASK_IDS = {
    "T001", "T002", "T003", "T004", "T005", "T006",
    "T025", "T026", "T037", "T040", "T041", "T042",
    "T051", "T052", "T053", "T055", "T056", "T057",
    "T074", "T076", "T077", "T078", "T080", "T081", "T082",
    "T083", "T084", "T087", "T088", "T089", "T090", "T091",
    "T092", "T095", "T096",
}


def task_needs_prediction(task: dict[str, Any]) -> bool:
    return str(task.get("id")) in PREDICTION_TASK_IDS


def evaluate_tasks(state: dict[str, Any], *, final: bool = False) -> list[str]:
    """刷新已分配任务状态，返回本次变化说明。"""
    changes: list[str] = []
    for task in state.get("tasks", []):
        owner = task.get("assigned_to")
        if owner is None or task.get("failed") or task.get("completed"):
            continue
        tid = str(task.get("id"))
        if tid in FINAL_ONLY_TASK_IDS and not final:
            continue
        result = _evaluate_one(state, task, int(owner), final=final)
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


def _evaluate_one(state: dict[str, Any], task: dict[str, Any], owner: int, *, final: bool) -> str:
    tid = str(task.get("id"))
    order = [int(x) for x in state.get("order", [])]
    counts = _trick_counts(state)
    owner_count = counts.get(owner, 0)
    won_cards = _won_cards(state, owner)
    won_tricks = _won_tricks(state, owner)
    last_no = _last_trick_no(state)
    captain = int(state.get("captain_id", 0))

    if tid == "T001":
        return _final_bool(final, all(owner_count > counts.get(p, 0) for p in order if p != owner))
    if tid == "T002":
        return _final_bool(final, owner_count > sum(counts.get(p, 0) for p in order if p != owner))
    if tid == "T003":
        return _final_bool(final, all(owner_count < counts.get(p, 0) for p in order if p != owner))
    if tid == "T004":
        return _final_bool(final, owner != captain and owner_count > counts.get(captain, 0))
    if tid == "T005":
        return _final_bool(final, owner != captain and owner_count < counts.get(captain, 0))
    if tid == "T006":
        return _final_bool(final, owner != captain and owner_count == counts.get(captain, 0))

    if tid == "T007":
        return _exists_trick(won_tricks, lambda cards, _winner_card: _no_sub(cards) and all(value_of(c) < 7 for c in cards))
    if tid == "T008":
        return _exists_trick(won_tricks, lambda cards, _winner_card: _no_sub(cards) and all(value_of(c) > 5 for c in cards))
    if tid in {"T009", "T010", "T011", "T015"}:
        target = {"T009": 6, "T010": 5, "T011": 3, "T015": 2}[tid]
        return _exists_trick(won_tricks, lambda cards, _winner_card: any(value_of(c) == target for c in cards))
    if tid == "T012":
        return _exists_trick(won_tricks, lambda cards, winner_card: value_of(winner_card) == 7 and any(value_of(c) == 5 for c in cards if c != winner_card))
    if tid == "T013":
        return _exists_trick(won_tricks, lambda cards, winner_card: value_of(winner_card) == 4 and any(value_of(c) == 8 for c in cards if c != winner_card))
    if tid == "T014":
        return _exists_trick(won_tricks, lambda cards, _winner_card: sum(1 for c in cards if value_of(c) == 6) >= 2)

    if tid in _SINGLE_CARD_TASKS:
        return _has_cards(won_cards, [_SINGLE_CARD_TASKS[tid]])
    if tid in _CARD_SET_TASKS:
        return _has_cards(won_cards, _CARD_SET_TASKS[tid])
    if tid in {"T020", "T024"}:
        value = 3 if tid == "T020" else 9
        return _bool_result(sum(1 for c in won_cards if value_of(c) == value) == 4)
    if tid in {"T021", "T022", "T023"}:
        value, amount = {"T021": (5, 3), "T022": (9, 3), "T023": (7, 2)}[tid]
        return _bool_result(sum(1 for c in won_cards if value_of(c) == value) >= amount)
    if tid == "T025":
        return _final_bool(final, sum(1 for c in won_cards if value_of(c) == 6) == 3)
    if tid == "T026":
        return _final_bool(final, sum(1 for c in won_cards if value_of(c) == 9) == 2)
    if tid == "T036":
        return _bool_result(any(t["no"] == last_no and "green:2" in t["cards"] for t in won_tricks)) if final else "pending"

    if tid == "T037":
        return _final_bool(final, _suit_count(won_cards, "pink") == 1 and _suit_count(won_cards, "green") == 1)
    if tid == "T038":
        return _bool_result(_suit_count(won_cards, "yellow") >= 7)
    if tid == "T039":
        return _bool_result(_suit_count(won_cards, "pink") >= 5)
    if tid == "T040":
        return _final_bool(final, _suit_count(won_cards, "green") == 2)
    if tid == "T041":
        return _final_bool(final, _suit_count(won_cards, "blue") == 2)
    if tid == "T042":
        return _final_bool(final, _suit_count(won_cards, "pink") == 1)
    if tid == "T043":
        return _fail_if(_suit_count(won_cards, "pink") > 0, final)
    if tid == "T044":
        return _bool_result(all(_suit_count(won_cards, suit) >= 1 for suit in ("pink", "yellow", "blue", "green")))
    if tid == "T045":
        return _bool_result(any(_suit_count(won_cards, suit) == 9 for suit in ("pink", "yellow", "blue", "green")))

    if tid == "T046":
        return _exists_trick(won_tricks, lambda cards, _winner_card: _no_sub(cards) and all(value_of(c) % 2 == 0 for c in cards))
    if tid == "T047":
        return _exists_trick(won_tricks, lambda cards, _winner_card: _no_sub(cards) and all(value_of(c) % 2 == 1 for c in cards))
    if tid == "T048":
        threshold = {3: 23, 4: 28, 5: 31}[len(order)]
        return _exists_trick(won_tricks, lambda cards, _winner_card: _no_sub(cards) and sum(value_of(c) for c in cards) > threshold)
    if tid == "T049":
        threshold = {3: 8, 4: 12, 5: 16}[len(order)]
        return _exists_trick(won_tricks, lambda cards, _winner_card: _no_sub(cards) and sum(value_of(c) for c in cards) < threshold)
    if tid == "T050":
        return _exists_trick(won_tricks, lambda cards, _winner_card: sum(value_of(c) for c in cards) in {22, 23})

    if tid == "T051":
        return _final_bool(final, _suit_count(won_cards, "sub") == 1)
    if tid == "T052":
        return _final_bool(final, set(_sub_values(won_cards)) == {1})
    if tid == "T053":
        return _final_bool(final, set(_sub_values(won_cards)) == {2})
    if tid == "T054":
        return _has_cards(won_cards, ["sub:3"])
    if tid == "T055":
        return _final_bool(final, _suit_count(won_cards, "sub") == 2)
    if tid == "T056":
        return _final_bool(final, _suit_count(won_cards, "sub") == 3)
    if tid == "T057":
        return _fail_if(_suit_count(won_cards, "sub") > 0, final)
    if tid == "T058":
        return _exists_trick(won_tricks, lambda cards, winner_card: suit_of(winner_card) == "sub" and "pink:7" in cards)
    if tid == "T059":
        return _exists_trick(won_tricks, lambda cards, winner_card: suit_of(winner_card) == "sub" and "green:9" in cards)

    if tid == "T060":
        return _fail_if(any(_lead_suit(t) in {"pink", "yellow", "blue"} for t in _opened_tricks(state, owner)), final)
    if tid == "T061":
        return _fail_if(any(_lead_suit(t) in {"pink", "green"} for t in _opened_tricks(state, owner)), final)
    if tid in _NO_SUIT_TASKS:
        return _fail_if(any(suit_of(c) in _NO_SUIT_TASKS[tid] for c in won_cards), final)
    if tid in _NO_VALUE_TASKS:
        return _fail_if(any(value_of(c) in _NO_VALUE_TASKS[tid] for c in won_cards), final)
    if tid == "T071":
        return _fail_if(any(t["no"] <= 4 for t in won_tricks), final)
    if tid == "T072":
        return _fail_if(any(t["no"] <= 3 for t in won_tricks), final)
    if tid == "T073":
        return _fail_if(any(t["no"] <= 5 for t in won_tricks), final)
    if tid == "T074":
        return _final_bool(final, owner_count == 0)
    if tid == "T075":
        return _fail_if(_has_consecutive([t["no"] for t in won_tricks], 2), final)

    if tid == "T076":
        return _final_bool(final, any(t["no"] == last_no for t in won_tricks))
    if tid == "T077":
        return _final_bool(final, {1, 2, 3}.issubset({t["no"] for t in won_tricks}))
    if tid == "T078":
        return _final_bool(final, {1, 2}.issubset({t["no"] for t in won_tricks}))
    if tid == "T079":
        return _bool_result(any(t["no"] == 1 for t in won_tricks))
    if tid == "T080":
        return _final_bool(final, any(t["no"] == 1 for t in won_tricks) and any(t["no"] == last_no for t in won_tricks))
    if tid == "T081":
        return _final_bool(final, [t["no"] for t in won_tricks] == [last_no])
    if tid == "T082":
        return _final_bool(final, [t["no"] for t in won_tricks] == [1])
    if tid == "T083":
        return _final_bool(final, owner_count == 1)
    if tid == "T084":
        return _final_bool(final, owner_count == 2)
    if tid == "T085":
        return _bool_result(_has_consecutive([t["no"] for t in won_tricks], 2))
    if tid == "T086":
        return _bool_result(_has_consecutive([t["no"] for t in won_tricks], 3))
    if tid == "T087":
        return _final_bool(final, owner_count == 4)
    if tid == "T088":
        return _final_bool(final, _max_consecutive([t["no"] for t in won_tricks]) == 3)
    if tid == "T089":
        return _final_bool(final, _max_consecutive([t["no"] for t in won_tricks]) == 2)
    if tid in {"T090", "T091"}:
        prediction = task.get("prediction")
        return "pending" if prediction is None else _final_bool(final, owner_count == int(prediction))

    if tid == "T092":
        return _final_bool(final, _suit_count(won_cards, "pink") == _suit_count(won_cards, "yellow") > 0)
    if tid == "T093":
        return _exists_trick(won_tricks, lambda cards, _winner_card: _suit_count(cards, "green") == _suit_count(cards, "yellow") > 0)
    if tid == "T094":
        return _exists_trick(won_tricks, lambda cards, _winner_card: _suit_count(cards, "pink") == _suit_count(cards, "blue") > 0)
    if tid == "T095":
        return _final_bool(final, _suit_count(won_cards, "yellow") > _suit_count(won_cards, "blue"))
    if tid == "T096":
        return _final_bool(final, _suit_count(won_cards, "pink") > _suit_count(won_cards, "green"))

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
    return cards


def _won_tricks(state: dict[str, Any], owner: int) -> list[dict[str, Any]]:
    tricks: list[dict[str, Any]] = []
    for trick in state.get("trick_history", []):
        if int(trick["winner"]) != owner:
            continue
        plays = trick.get("plays", [])
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


def _has_cards(cards: list[str], required: list[str]) -> str:
    have = Counter(cards)
    need = Counter(required)
    return _bool_result(all(have[card] >= count for card, count in need.items()))


def _exists_trick(won_tricks: list[dict[str, Any]], predicate) -> str:  # noqa: ANN001
    for trick in won_tricks:
        if predicate(trick["cards"], trick["winner_card"]):
            return "completed"
    return "pending"


def _bool_result(value: bool) -> str:
    return "completed" if value else "pending"


def _final_bool(final: bool, value: bool) -> str:
    if value:
        return "completed"
    return "failed" if final else "pending"


def _fail_if(value: bool, final: bool) -> str:
    if value:
        return "failed"
    return "completed" if final else "pending"


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
