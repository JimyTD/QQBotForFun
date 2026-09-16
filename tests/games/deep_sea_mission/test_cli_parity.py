"""深海任务 · CLI 与线上行为对齐测试（铁律 13：CLI 跑通 = 群里能跑通）。

锁住 6 项此前只在 CLI 侧失配的行为：
出牌结束条件 / pass 保护 / 自由选任务先到先得 / M25 队长不接任务 /
预测阶段（T090/T091）/ Epilogue 入口。

每条都对着 game.py 的线上实现（括号里给出行号来源）：
- playing_ended = any(手牌为空)
- 未分配任务数 >= 玩家数时拒绝「过」
- 自由选任务任何座位都能抢（先到先得）
- ASG_CAPTAIN_NO_TASK 时 selector 每步跳过队长
- 任务选完 → 预测 → 出牌
- 战役 epilogue:N 入口
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = str(ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from cli_adapters import deep_sea_mission as cli_mod  # noqa: E402
from cli_adapters.deep_sea_mission import DeepSeaMissionCLIAdapter  # noqa: E402

from src.plugins.games.deep_sea_mission.campaign import (  # noqa: E402
    ASG_CAPTAIN_NO_TASK,
    MOD_FREE_SELECTION,
    Mission,
)

HANDS = {"1": ["blue:1"], "2": ["blue:2"], "3": ["sub:4"]}


def _adapter(
    *,
    hands: dict[str, list[str]] | None = None,
    tasks: list[dict] | None = None,
) -> DeepSeaMissionCLIAdapter:
    a = DeepSeaMissionCLIAdapter()
    a.players = [1, 2, 3]
    a.names = {1: "P1", 2: "P2", 3: "P3"}
    a.order = [1, 2, 3]
    a.captain = 1
    a.current = 1
    a.hands = {k: list(v) for k, v in (hands or HANDS).items()}
    a.tasks = [dict(t) for t in (tasks or [])]
    return a


def _task(task_id: str, *, owner: int | None = None) -> dict:
    return {"id": task_id, "text": f"任务{task_id}", "difficulty": 1, "assigned_to": owner}


# ==================== 出牌结束条件 ====================


async def test_playing_ended_when_any_hand_empty(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """任一玩家空手即出牌结束（线上 any(not hands...)），并进入手动结算。"""
    a = _adapter(hands={"1": [], "2": ["blue:2"], "3": ["sub:4"]}, tasks=[_task("T001", owner=1)])
    monkeypatch.setattr(cli_mod, "prompt", lambda msg="": "fail")

    assert a._after_trick() is True  # 收局，不再继续出牌
    out = capsys.readouterr().out
    assert "有玩家已无手牌，本局出牌结束" in out
    assert "任务失败" in out
    assert not a._aborted


async def test_playing_continues_when_all_have_cards(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """全员还有手牌时不应误判为结束。"""
    a = _adapter(tasks=[_task("T001", owner=1)])

    def never(msg: str = "") -> str:
        raise AssertionError("不该进入结算提示")

    monkeypatch.setattr(cli_mod, "prompt", never)
    assert a._after_trick() is False


# ==================== pass 保护 ====================


async def test_pass_blocked_when_enough_tasks(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """任务数 >= 玩家数时不能跳过（线上「还有足够任务可选，暂不能跳过」）。"""
    a = _adapter(tasks=[_task("T001"), _task("T002"), _task("T003")])
    seq = iter(["过", "过", "过", "1", "2", "3"])
    monkeypatch.setattr(cli_mod, "prompt", lambda msg="": next(seq))

    await a._select_tasks_normal()

    out = capsys.readouterr().out
    assert out.count("还有足够任务可选，暂不能跳过") == 3
    assert all(t["assigned_to"] is not None for t in a.tasks)


async def test_pass_allowed_when_tasks_fewer_than_players(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """任务少于玩家数时允许跳过（线上同一条件）。"""
    a = _adapter(tasks=[_task("T001"), _task("T002")])
    seq = iter(["过", "1", "2"])
    monkeypatch.setattr(cli_mod, "prompt", lambda msg="": next(seq))

    await a._select_tasks_normal()

    assert all(t["assigned_to"] is not None for t in a.tasks)


# ==================== 自由选任务（先到先得） ====================


async def test_free_selection_picks_by_seat(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """自由选任务：谁抢到归谁（用显式座位对应发话人），不再全塞给同一个人。"""
    a = _adapter(tasks=[_task("T001"), _task("T002")])
    a.mission = Mission(17, 9, modifiers=(MOD_FREE_SELECTION,))
    seq = iter(["P2 1", "3 2"])
    monkeypatch.setattr(cli_mod, "prompt", lambda msg="": next(seq))

    await a._select_tasks()

    assert [t["assigned_to"] for t in a.tasks] == [2, 3]
    assert "先到先得" in capsys.readouterr().out


async def test_free_selection_rejects_bad_input(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """自由选任务下非法输入（含 pass）应提示而不是把任务胡乱派出去。"""
    a = _adapter(tasks=[_task("T001")])
    a.mission = Mission(17, 9, modifiers=(MOD_FREE_SELECTION,))
    seq = iter(["pass", "P9 1", "1"])
    monkeypatch.setattr(cli_mod, "prompt", lambda msg="": next(seq))

    await a._select_tasks()

    assert a.tasks[0]["assigned_to"] == 1  # 默认座位 = 提示中的座位
    assert capsys.readouterr().out.count("无效输入") == 2


# ==================== M25 队长不接任务 ====================


async def test_captain_never_picked_when_captain_no_task(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """ASG_CAPTAIN_NO_TASK：每一步轮转都跳过队长（线上 _advance_selector）。"""
    a = _adapter(tasks=[_task(f"T00{i}") for i in range(1, 5)])
    a.mission = Mission(25, 12, assignment=ASG_CAPTAIN_NO_TASK)
    asked: list[str] = []
    counter = {"n": 1}

    def fake(msg: str = "") -> str:
        asked.append(msg)
        if "选任务" in msg:
            n = counter["n"]
            counter["n"] += 1
            return str(n)
        return "1"

    monkeypatch.setattr(cli_mod, "prompt", fake)
    await a._select_tasks()

    assert all(t["assigned_to"] is not None for t in a.tasks)
    select_prompts = [m for m in asked if "选任务" in m]
    assert select_prompts
    assert not any(m.startswith("P1 ") for m in select_prompts)
    assert all(t["assigned_to"] != a.captain for t in a.tasks)


# ==================== 预测阶段 ====================


async def test_prediction_phase_collects_and_validates(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """T090/T091 必须报出赢墩数；越界/非数字被拒；普通任务不问。"""
    a = _adapter(tasks=[_task("T090", owner=2), _task("T091", owner=3), _task("T001", owner=1)])
    seq = iter(["99", "1", "abc", "0"])
    monkeypatch.setattr(cli_mod, "prompt", lambda msg="": next(seq))

    a._ask_predictions()

    assert a.tasks[0]["prediction"] == 1  # 超出上限被拒后接受合法值
    assert a.tasks[1]["prediction"] == 0
    assert "prediction" not in a.tasks[2]
    out = capsys.readouterr().out
    assert "预测墩数应为 0-1" in out
    assert "公开预测" in out and "秘密预测" in out


async def test_prediction_phase_skips_when_already_set(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """已有预测值的任务不再重复询问。"""
    task = _task("T090", owner=2)
    task["prediction"] = 1
    a = _adapter(tasks=[task])

    monkeypatch.setattr(cli_mod, "prompt", lambda msg="": "0")
    a._ask_predictions()

    assert a.tasks[0]["prediction"] == 1


# ==================== Epilogue 入口 ====================


async def test_epilogue_entry_and_no_level_advance(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """setlevel epilogue:N 进入 Epilogue（自由选任务），胜利不推进战役关卡号。"""
    monkeypatch.setattr(DeepSeaMissionCLIAdapter, "_campaign_level", 1)
    monkeypatch.setattr(DeepSeaMissionCLIAdapter, "_epilogue_difficulty", None)
    a = _adapter()

    a._handle_setlevel("setlevel epilogue:6")
    assert DeepSeaMissionCLIAdapter._epilogue_difficulty == 6

    monkeypatch.setattr(cli_mod, "prompt", lambda msg="": "3")
    await a.start("campaign")

    assert a.mission is not None
    assert a.mission.no == 0  # no=0 → 面板显示 Epilogue
    assert MOD_FREE_SELECTION in a.mission.modifiers
    assert a.tasks
    assert "Epilogue" in a._campaign_header()

    a.mode_id = "campaign"
    a._on_win()
    assert DeepSeaMissionCLIAdapter._campaign_level == 1  # 不推进关卡号
    assert DeepSeaMissionCLIAdapter._epilogue_difficulty == 6
    assert "Epilogue 通关" in capsys.readouterr().out

    # 回到普通关卡时 Epilogue 状态要清掉
    a._handle_setlevel("setlevel 5")
    assert DeepSeaMissionCLIAdapter._epilogue_difficulty is None
    assert DeepSeaMissionCLIAdapter._campaign_level == 5
