"""深海任务：任务进度提示（只读展示，参与不了胜负）。"""

from src.plugins.games.deep_sea_mission.rules import task_progress


def _state(won: list[str]) -> dict:
    """构造一个 owner=2 已赢下 won 这些牌的公开状态。

    每墩都由 2 号出潜艇4（最大潜艇）吃下，赢家恒为 2 号，
    这样 won 列表里的牌全部计入 2 号的已赢牌。
    """
    history = [
        {
            "no": i,
            "plays": [{"player": 2, "card": "sub:4"}, {"player": 1, "card": card}],
            "winner": 2,
        }
        for i, card in enumerate(won, 1)
    ]
    return {
        "order": [1, 2, 3],
        "captain_id": 1,
        "trick_history": history,
        "won_tricks": {},
    }


def _task(tid: str, **extra) -> dict:
    task = {"id": tid, "difficulty": 3, "assigned_to": 2}
    task.update(extra)
    return task


def test_at_least_value():
    s = _state(["pink:9", "yellow:5", "blue:5"])
    assert task_progress(s, _task("T021")) == "5点 2/3"
    assert task_progress(s, _task("T022")) == "9点 1/3"


def test_exact_value_shows_overflow_warning():
    s = _state(["pink:6"])
    assert task_progress(s, _task("T025")) == "6点 1/3（超 3 失败）"
    assert task_progress(s, _task("T026")) == "9点 0/2（超 2 失败）"


def test_at_least_suit():
    s = _state(["yellow:1", "yellow:2", "yellow:3"])
    assert task_progress(s, _task("T038")) == "黄 3/7"
    assert task_progress(s, _task("T039")) == "粉 0/5"


def test_exact_suit_shows_overflow_warning():
    s = _state(["blue:1"])
    assert task_progress(s, _task("T041")) == "蓝 1/2（超 2 失败）"
    assert task_progress(s, _task("T042")) == "粉 0/1（超 1 失败）"


def test_equal_suits_positive():
    s = _state(["pink:1", "pink:2", "yellow:3"])
    assert task_progress(s, _task("T092")) == "粉 2 · 黄 1"


def test_suit_more():
    s = _state(["yellow:1", "blue:2"])
    assert task_progress(s, _task("T095")) == "黄 1 · 蓝 1"


def test_all_colors():
    s = _state(["pink:1", "yellow:2", "blue:3"])
    assert task_progress(s, _task("T044")) == "粉1 黄1 蓝1 绿0"
    assert task_progress(s, _task("T045")) == "粉1 黄1 蓝1 绿0 /9"


def test_two_suits_exact():
    s = _state(["pink:1"])
    assert task_progress(s, _task("T037")) == "粉 1/1 · 绿 0/1（各超 1 失败）"


def test_submarine_exact():
    # 构造里 2 号靠潜艇4 吃墩，因此已自带 1 张潜艇
    s = _state(["pink:1"])
    assert task_progress(s, _task("T051")) == "潜艇 1/1（超 1 失败）"
    assert task_progress(s, _task("T056")) == "潜艇 1/3（超 3 失败）"


def test_card_set():
    s = _state(["yellow:4"])
    assert task_progress(s, _task("T035")) == "绿3□ 黄4✅ 黄5□"


def test_prediction():
    s = _state(["pink:1"])
    assert task_progress(s, _task("T090", prediction=3)) == "已赢 1 / 预测 3"
    assert task_progress(s, _task("T090")) is None


def test_no_progress_cases():
    s = _state(["pink:1"])
    assert task_progress(s, _task("T001")) is None
    assert task_progress(s, _task("T092", assigned_to=None)) is None
