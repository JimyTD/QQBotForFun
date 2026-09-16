"""深海任务 · CLI 侧声呐对齐测试（铁律 13：CLI 跑通 = 群里能跑通）。

CLI 的判定与文案全部取自 `game.py` 的共用实现，这里锁住：
声呐归属反查、每人一次、rapture 共享额度、时机拦截、写错格式、手牌不泄露。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = str(ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from cli_adapters import deep_sea_mission as cli_mod  # noqa: E402
from cli_adapters.deep_sea_mission import DeepSeaMissionCLIAdapter  # noqa: E402

from src.plugins.games.deep_sea_mission.campaign import get_mission  # noqa: E402

HANDS = {
    "1": ["blue:1", "blue:2"],
    "2": ["blue:3", "yellow:1"],
    "3": ["sub:4", "yellow:2"],
}


def _adapter(
    *,
    hands: dict[str, list[str]] | None = None,
    sonar_mode: str = "normal",
    trick_no: int = 1,
    trick: list[dict[str, int | str]] | None = None,
    mission_no: int | None = None,
) -> DeepSeaMissionCLIAdapter:
    a = DeepSeaMissionCLIAdapter()
    a.players = [1, 2, 3]
    a.names = {1: "P1", 2: "P2", 3: "P3"}
    a.order = [1, 2, 3]
    a.hands = {k: list(v) for k, v in (hands or HANDS).items()}
    a.sonar_mode = sonar_mode
    a.sonar_used = {str(p): False for p in a.players}
    a.sonar_used_count = 0
    a.sonar_quota = len(a.players) - 2
    a.trick_no = trick_no
    a.current_trick = list(trick or [])
    if mission_no is not None:
        a.mission = get_mission(mission_no)
    return a


def test_cli_sonar_declares_and_locks_per_player(capsys) -> None:  # type: ignore[no-untyped-def]
    a = _adapter()
    assert a._declare_sonar("声呐 蓝1 最低") == "ok"
    out = capsys.readouterr().out
    assert "P1 公开 蓝1" in out
    assert "蓝色最低牌" in out

    # 同一个人第二次 → 群里同款文案
    assert a._declare_sonar("声呐 蓝2 最高") == "rejected"
    assert "已经用过声呐" in capsys.readouterr().out

    # 换人还可以发
    assert a._declare_sonar("声呐 黄1 唯一") == "ok"
    assert "P2 公开 黄1" in capsys.readouterr().out


def test_cli_sonar_bad_format_and_illegal(capsys) -> None:  # type: ignore[no-untyped-def]
    a = _adapter()
    assert a._declare_sonar("声呐 蓝1") == "rejected"
    assert "声呐写法不对" in capsys.readouterr().out

    assert a._declare_sonar("声呐 蓝1 最高") == "rejected"  # 蓝1 是蓝最低，不是最高
    assert "声呐声明不合法" in capsys.readouterr().out

    assert a._declare_sonar("蓝1") == "not_sonar"


def test_cli_sonar_timing_messages_match_bot(capsys) -> None:  # type: ignore[no-untyped-def]
    mid_trick = _adapter(trick=[{"player": 3, "card": "sub:4"}])
    assert mid_trick._declare_sonar("声呐 蓝1 最低") == "rejected"
    assert "一墩进行中不能用声呐" in capsys.readouterr().out

    silent = _adapter(sonar_mode="silence")
    assert silent._declare_sonar("声呐 蓝1 最低") == "rejected"
    assert "本关禁止交流" in capsys.readouterr().out

    m23 = _adapter(mission_no=23, trick_no=1)
    assert m23._declare_sonar("声呐 蓝1 最低") == "rejected"
    assert "第二墩前禁止交流" in capsys.readouterr().out

    m23.trick_no = 3  # 第三墩起放开
    assert m23._declare_sonar("声呐 蓝1 最低") == "ok"
    assert "P1 公开 蓝1" in capsys.readouterr().out


def test_cli_sonar_rapture_shared_quota(capsys) -> None:  # type: ignore[no-untyped-def]
    a = _adapter(sonar_mode="rapture")
    assert a.sonar_quota == 1
    assert a._declare_sonar("声呐 蓝1 最低") == "ok"
    assert "剩余共享声呐 0 次" in capsys.readouterr().out
    assert a._declare_sonar("声呐 蓝2 最高") == "rejected"
    assert "全队共享声呐次数已用完" in capsys.readouterr().out


def test_cli_sonar_stage_skips_when_exhausted(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    a = _adapter()
    monkeypatch.setattr(cli_mod, "prompt", lambda msg="": "声呐 蓝1 最低")
    a._sonar_stage()
    out = capsys.readouterr().out
    assert "墩间声呐" in out
    assert "公开 蓝1" in out

    # 3 人正常模式：全用完后再开窗口应当是空操作
    a._declare_sonar("声呐 黄1 唯一")
    a._declare_sonar("声呐 黄2 最高")
    a._sonar_stage()
    assert "墩间声呐" not in capsys.readouterr().out


def test_cli_deal_box_hides_other_hands() -> None:
    a = _adapter()
    text = "\n".join(a._deal_box_lines())
    assert "蓝1" not in text and "黄1" not in text
    assert "P1 2 张" in text and "P2 2 张" in text

    debug = _adapter()
    debug.debug = True
    debug_text = "\n".join(debug._deal_box_lines())
    assert "蓝1" in debug_text  # --debug 才展示全手牌


@pytest.mark.parametrize("sonar_mode", ["normal", "currents"])
async def test_cli_autopilot_full_mission(monkeypatch, capsys, sonar_mode: str) -> None:  # type: ignore[no-untyped-def]
    """整局自动跑完：任务选择 → 墩间声呐 → 出牌，不应崩、不应卡死。"""
    from src.plugins.games.deep_sea_mission.cards import display_card, legal_play

    a = _adapter(sonar_mode=sonar_mode)
    a.tasks = [
        {"id": "T001", "text": "任务A", "difficulty": 1, "assigned_to": None, "completed": False},
    ]
    declared = {"n": 0}
    calls = {"n": 0}

    def fake_prompt(msg: str = "") -> str:
        calls["n"] += 1
        assert calls["n"] < 200, f"prompt 次数异常（疑似死循环），msg={msg!r}"
        if "选任务" in msg:
            for i, t in enumerate(a.tasks):
                if t["assigned_to"] is None:
                    return str(i + 1)
            return "pass"
        if msg.startswith("声呐？"):
            if declared["n"] == 0:
                declared["n"] = 1
                return "声呐 蓝1 最低"
            return ""
        if msg.startswith("结算"):
            # 任一玩家空手即出牌结束（与线上一致），此后进入结算提示
            return "fail"
        hand = a.hands[str(a.current)]
        for card in hand:
            ok, _ = legal_play(hand, card, a.lead_suit)
            if ok:
                return display_card(card)
        raise AssertionError("no legal card")

    monkeypatch.setattr(cli_mod, "prompt", fake_prompt)
    await a.play()
    out = capsys.readouterr().out
    assert declared["n"] == 1
    assert "公开 蓝1" in out
    assert "手牌已打完" in out or "赢" in out or "任务失败" in out
    assert not a._aborted
