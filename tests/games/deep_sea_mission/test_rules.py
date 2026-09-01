"""深海任务：公开信息锁死判定。"""

from __future__ import annotations

from src.plugins.games.deep_sea_mission.rules import (
    evaluate_campaign_special,
    evaluate_tasks,
    mission_locked_win,
    remaining_tricks,
)


def _task(tid: str, owner: int = 1, **extra: object) -> dict:
    return {
        "id": tid,
        "text": tid,
        "display_no": 1,
        "assigned_to": owner,
        "completed": False,
        "failed": False,
        **extra,
    }


def _trick(no: int, winner: int, cards: list[str], players: list[int] | None = None) -> dict:
    seats = players or [1, 2, 3]
    return {
        "no": no,
        "winner": winner,
        "plays": [{"player": seats[i % len(seats)], "card": card} for i, card in enumerate(cards)],
    }


def _state(
    tasks: list[dict],
    history: list[dict],
    *,
    r_hands: int = 5,
    captain: int = 3,
    extra_hands: dict[str, list[str]] | None = None,
    **more: object,
) -> dict:
    order = [1, 2, 3]
    hands = extra_hands or {str(p): ["x"] * r_hands for p in order}
    state: dict = {
        "order": order,
        "captain_id": captain,
        "hands": hands,
        "tasks": tasks,
        "trick_history": history,
        "mode": "mission",
    }
    state.update(more)
    return state


def test_remaining_tricks_uses_hand_lengths_only() -> None:
    state = _state([], [], extra_hands={"1": ["a", "b"], "2": ["c"], "3": ["d"]})
    assert remaining_tricks(state) == 1


def test_t079_completes_after_first_trick() -> None:
    state = _state(
        [_task("T079", 3)],
        [_trick(1, 3, ["sub:4", "blue:1", "yellow:1"])],
        r_hands=1,
    )
    evaluate_tasks(state)
    assert state["tasks"][0]["completed"] is True
    assert mission_locked_win(state) is True


def test_t077_completes_after_third_trick_and_fails_if_missed() -> None:
    win123 = [
        _trick(1, 1, ["blue:9", "blue:1", "blue:2"]),
        _trick(2, 1, ["yellow:9", "yellow:1", "yellow:2"]),
        _trick(3, 1, ["green:9", "green:1", "green:2"]),
    ]
    ok = _state([_task("T077")], win123, r_hands=2)
    evaluate_tasks(ok)
    assert ok["tasks"][0]["completed"] is True

    missed = _state(
        [_task("T077")],
        [
            _trick(1, 1, ["blue:9", "blue:1", "blue:2"]),
            _trick(2, 2, ["yellow:9", "yellow:1", "yellow:2"]),
        ],
        r_hands=3,
    )
    evaluate_tasks(missed)
    assert missed["tasks"][0]["failed"] is True


def test_t071_completes_when_window_closes() -> None:
    history = [
        _trick(1, 2, ["blue:9", "yellow:1", "green:1"]),
        _trick(2, 2, ["blue:8", "yellow:2", "green:2"]),
        _trick(3, 2, ["blue:7", "yellow:3", "green:3"]),
        _trick(4, 2, ["blue:6", "yellow:4", "green:4"]),
    ]
    state = _state([_task("T071", 1)], history, r_hands=2)
    evaluate_tasks(state)
    assert state["tasks"][0]["completed"] is True


def test_t001_locks_on_remaining_tricks_not_current_lead() -> None:
    # 甲 4 墩、乙丙各 1，R=2：4 > 1+2，锁死完成
    history = [
        *[_trick(i, 1, ["sub:4", "blue:1", "yellow:1"]) for i in range(1, 5)],
        _trick(5, 2, ["blue:9", "blue:2", "yellow:2"]),
        _trick(6, 3, ["green:9", "green:2", "pink:2"]),
    ]
    locked = _state([_task("T001")], history, r_hands=2)
    evaluate_tasks(locked)
    assert locked["tasks"][0]["completed"] is True

    # 甲 2、乙 1、丙 0，R=3：2 > 1+3？否；尚未锁死
    early = _state(
        [_task("T001")],
        [_trick(1, 1, ["blue:9", "blue:1", "yellow:1"]), _trick(2, 2, ["green:9", "green:1", "pink:1"])],
        r_hands=3,
    )
    evaluate_tasks(early)
    assert early["tasks"][0]["completed"] is False
    assert early["tasks"][0]["failed"] is False


def test_t043_completes_when_all_pinks_are_out_not_when_hidden_in_hands() -> None:
    pinks = [f"pink:{v}" for v in range(1, 10)]
    others = ["blue:1", "yellow:1"]
    history = []
    for i, pink in enumerate(pinks, 1):
        winner = 2 if i <= 5 else 3
        history.append(_trick(i, winner, [pink, others[0], others[1]]))
    done = _state([_task("T043")], history, r_hands=2)
    evaluate_tasks(done)
    assert done["tasks"][0]["completed"] is True

    hidden = _state(
        [_task("T043")],
        [_trick(1, 2, ["blue:9", "yellow:9", "green:9"])],
        extra_hands={
            "1": ["blue:1", "blue:2"],
            "2": ["pink:8", "pink:3", "pink:1"],
            "3": ["pink:2", "sub:4"],
        },
    )
    evaluate_tasks(hidden)
    assert hidden["tasks"][0]["completed"] is False
    assert hidden["tasks"][0]["failed"] is False
    assert remaining_tricks(hidden) == 2


def test_t025_exact_sixes_lock_when_fourth_is_publicly_out() -> None:
    # 甲 3 张 6，第 4 张 6 在别人墩里 → 完成
    history = [
        _trick(1, 1, ["pink:6", "blue:6", "yellow:1"]),
        _trick(2, 1, ["green:6", "blue:1", "yellow:2"]),
        _trick(3, 2, ["yellow:6", "blue:2", "green:1"]),
    ]
    done = _state([_task("T025")], history, r_hands=4)
    evaluate_tasks(done)
    assert done["tasks"][0]["completed"] is True

    # 甲 3 张 6，第 4 张未出场（哪怕在乙手里）→ 不能完成
    pending = _state(
        [_task("T025")],
        [
            _trick(1, 1, ["pink:6", "blue:6", "yellow:1"]),
            _trick(2, 1, ["green:6", "blue:1", "yellow:2"]),
        ],
        extra_hands={"1": ["blue:2"], "2": ["yellow:6"], "3": ["sub:4"]},
    )
    evaluate_tasks(pending)
    assert pending["tasks"][0]["completed"] is False
    assert pending["tasks"][0]["failed"] is False


def test_t016_fails_when_required_card_won_by_other() -> None:
    state = _state(
        [_task("T016")],
        [_trick(1, 2, ["pink:3", "blue:1", "yellow:1"])],
        r_hands=4,
    )
    evaluate_tasks(state)
    assert state["tasks"][0]["failed"] is True


def test_prediction_locks_over_and_unreachable() -> None:
    over = _state(
        [_task("T090", prediction=1)],
        [_trick(1, 1, ["blue:9", "blue:1", "yellow:1"]), _trick(2, 1, ["green:9", "green:1", "pink:1"])],
        r_hands=3,
    )
    evaluate_tasks(over)
    assert over["tasks"][0]["failed"] is True

    equal = _state(
        [_task("T090", prediction=1)],
        [_trick(1, 1, ["blue:9", "blue:1", "yellow:1"])],
        r_hands=2,
    )
    evaluate_tasks(equal)
    assert equal["tasks"][0]["completed"] is False
    assert equal["tasks"][0]["failed"] is False


def test_t036_fails_if_green2_appears_before_last_trick() -> None:
    state = _state(
        [_task("T036")],
        [_trick(1, 1, ["green:2", "blue:1", "yellow:1"])],
        r_hands=3,
    )
    evaluate_tasks(state)
    assert state["tasks"][0]["failed"] is True


def test_campaign_m8_gap_fail_and_remaining_lock() -> None:
    fail_state = {
        "mode": "campaign",
        "mission": {"no": 8},
        "order": [1, 2, 3],
        "hands": {"1": ["x"] * 4, "2": ["x"] * 4, "3": ["x"] * 4},
        "won_tricks": {
            "1": [{"no": 1, "cards": ["pink:9", "blue:9"]}],
            "2": [{"no": 2, "cards": ["blue:1"]}],
            "3": [],
        },
        "trick_history": [],
        "tasks": [],
    }
    status, msg = evaluate_campaign_special(fail_state)
    assert status == "failed"
    assert msg is not None and "9" in msg

    # 三人各 1 张 9，未出场 1 张：最坏也拉不开差 2
    lock = {
        "mode": "campaign",
        "mission": {"no": 8},
        "order": [1, 2, 3],
        "hands": {"1": ["x"], "2": ["x"], "3": ["x"]},
        "tasks": [],
        "trick_history": [
            _trick(1, 1, ["pink:9", "blue:1", "yellow:1"]),
            _trick(2, 2, ["blue:9", "blue:2", "yellow:2"]),
            _trick(3, 3, ["green:9", "green:1", "pink:1"]),
        ],
    }
    status, _ = evaluate_campaign_special(lock)
    assert status == "completed"
    assert mission_locked_win(lock) is True


def test_campaign_m27_yellow5_early_fail() -> None:
    state = {
        "mode": "campaign",
        "mission": {"no": 27},
        "order": [1, 2, 3],
        "hands": {"1": ["x"], "2": ["x"], "3": ["x"]},
        "tasks": [],
        "trick_history": [_trick(1, 1, ["yellow:5", "blue:1", "green:1"])],
    }
    status, msg = evaluate_campaign_special(state)
    assert status == "failed"
    assert msg is not None


def test_campaign_m23_tie_is_fail() -> None:
    state = {
        "mode": "campaign",
        "mission": {"no": 23},
        "order": [1, 2, 3],
        "hands": {"1": ["x"] * 3, "2": ["x"] * 3, "3": ["x"] * 3},
        "tasks": [],
        "trick_history": [
            {"no": 1, "plays": [{"player": 1, "card": "blue:9"}], "winner": 1},
            {"no": 2, "plays": [{"player": 2, "card": "blue:8"}], "winner": 2},
        ],
    }
    status, _ = evaluate_campaign_special(state)
    assert status == "failed"
