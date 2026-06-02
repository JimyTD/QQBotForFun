"""红警2斗蛐蛐播报层测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.games.ra2_battle.broadcaster import (
    MODE_BRIEF,
    MODE_DETAILED,
    Broadcaster,
    format_battle_report,
)
from plugins.games.ra2_battle.simulator import BattleSimulator, Side

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2，先运行 openra_ra2_export.py")


def test_brief_broadcast_includes_start_and_wipe(require_export):
    result = BattleSimulator([("ghost", 5)], [("e2", 12)], seed=42).run()
    segs = Broadcaster(result, mode=MODE_BRIEF, seed=0).generate()
    texts = [s.text for s in segs]
    assert any("战斗打响" in t for t in texts)
    assert any("全灭" in t or "覆没" in t or "全歼" in t for t in texts)
    assert not any("战斗速递" in t for t in texts)


def test_detailed_broadcast_has_time_windows(require_export):
    result = BattleSimulator([("ghost", 5)], [("e2", 12)], seed=42).run()
    segs = Broadcaster(result, mode=MODE_DETAILED, seed=0).generate()
    texts = [s.text for s in segs]
    assert any("战斗打响" in t for t in texts)
    assert any("⏱" in t for t in texts) or result.duration <= 0


def test_battle_report_stats(require_export):
    result = BattleSimulator([("ghost", 5)], [("e2", 12)], seed=42).run()
    report = format_battle_report(result)
    assert "战斗结果" in report
    assert "战斗时长" in report
    assert "tick" not in report
    assert "海豹突击队" in report
    assert "动员兵" in report
    assert "击杀" in report
    assert "伤害" in report
    assert "🟥" in report or "🟦" in report
    assert result.winner == Side.RED
    assert "红方（1号）" in report


def test_crush_kill_tracked(require_export):
    result = BattleSimulator([("htnk", 3)], [("e2", 20)], seed=1).run()
    red_all = result.red_alive + result.red_dead
    total_kills = sum(u.kills for u in red_all)
    assert total_kills >= 1
    report = format_battle_report(result)
    assert "击杀" in report
