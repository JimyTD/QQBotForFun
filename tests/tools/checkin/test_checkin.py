"""每日签到功能单元测试。

覆盖：
- 首次签到
- 重复签到（同一天）
- 连续签到天数递增
- 断签重置
- 满 30 天循环
- 里程碑奖励
- calc_reward 纯函数
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from src.plugins.tools.checkin.models import CheckinRecord
from src.plugins.tools.checkin.service import (
    BASE_COIN,
    BASE_SCORE,
    MILESTONE_REWARDS,
    STREAK_CYCLE,
    calc_reward,
    do_checkin,
)


# ------------------------------------------------------------------
# calc_reward 纯函数测试
# ------------------------------------------------------------------
class TestCalcReward:
    def test_normal_day_returns_base(self) -> None:
        assert calc_reward(1) == (BASE_COIN, BASE_SCORE)
        assert calc_reward(3) == (BASE_COIN, BASE_SCORE)
        assert calc_reward(6) == (BASE_COIN, BASE_SCORE)

    def test_milestone_7(self) -> None:
        assert calc_reward(7) == MILESTONE_REWARDS[7]

    def test_milestone_14(self) -> None:
        assert calc_reward(14) == MILESTONE_REWARDS[14]

    def test_milestone_21(self) -> None:
        assert calc_reward(21) == MILESTONE_REWARDS[21]

    def test_milestone_30(self) -> None:
        assert calc_reward(30) == MILESTONE_REWARDS[30]

    def test_non_milestone_between_milestones(self) -> None:
        assert calc_reward(8) == (BASE_COIN, BASE_SCORE)
        assert calc_reward(15) == (BASE_COIN, BASE_SCORE)
        assert calc_reward(29) == (BASE_COIN, BASE_SCORE)

    def test_all_rewards_are_positive(self) -> None:
        """所有奖励必须为正数（永不负反馈）。"""
        for streak in range(1, STREAK_CYCLE + 1):
            coin, score = calc_reward(streak)
            assert coin > 0, f"streak={streak} coin={coin}"
            assert score > 0, f"streak={streak} score={score}"

    def test_milestone_rewards_greater_than_base(self) -> None:
        """里程碑奖励应大于基础奖励。"""
        for streak, (coin, score) in MILESTONE_REWARDS.items():
            assert coin >= BASE_COIN, f"milestone {streak} coin < base"
            assert score >= BASE_SCORE, f"milestone {streak} score < base"


# ------------------------------------------------------------------
# do_checkin 集成测试（mock storage + economy）
# ------------------------------------------------------------------
_MODULE = "src.plugins.tools.checkin.service"


def _make_record(
    qq_id: int = 12345,
    last_date: date | None = None,
    streak: int = 1,
    total: int = 1,
) -> CheckinRecord:
    r = CheckinRecord()
    r.qq_id = qq_id
    r.last_checkin_date = last_date or date.today()
    r.streak = streak
    r.total_checkins = total
    return r


@pytest.fixture()
def _mock_deps():
    """Mock storage 和 economy 依赖。"""
    with (
        patch(f"{_MODULE}.get_checkin_record", new_callable=AsyncMock) as mock_get,
        patch(f"{_MODULE}.upsert_checkin", new_callable=AsyncMock) as mock_upsert,
        patch(f"{_MODULE}.economy") as mock_eco,
    ):
        mock_eco.add = AsyncMock(return_value=0)
        mock_eco.balance = AsyncMock(return_value=100)
        yield mock_get, mock_upsert, mock_eco


@pytest.mark.usefixtures("_mock_deps")
class TestDoCheckin:
    async def test_first_checkin(self, _mock_deps) -> None:
        mock_get, mock_upsert, mock_eco = _mock_deps
        mock_get.return_value = None

        result = await do_checkin(12345)

        assert not result.already_done
        assert result.streak == 1
        assert result.total_checkins == 1
        assert result.coin == BASE_COIN
        assert result.score == BASE_SCORE
        mock_upsert.assert_called_once()

    async def test_already_checked_in_today(self, _mock_deps) -> None:
        mock_get, mock_upsert, _eco = _mock_deps

        with patch(f"{_MODULE}._today_cst", return_value=date(2026, 5, 15)):
            mock_get.return_value = _make_record(
                last_date=date(2026, 5, 15), streak=3, total=10,
            )
            result = await do_checkin(12345)

        assert result.already_done
        assert result.streak == 3
        assert result.total_checkins == 10
        mock_upsert.assert_not_called()

    async def test_consecutive_day_increments_streak(self, _mock_deps) -> None:
        mock_get, mock_upsert, _eco = _mock_deps

        with patch(f"{_MODULE}._today_cst", return_value=date(2026, 5, 15)):
            mock_get.return_value = _make_record(
                last_date=date(2026, 5, 14), streak=5, total=20,
            )
            result = await do_checkin(12345)

        assert not result.already_done
        assert result.streak == 6
        assert result.total_checkins == 21

    async def test_broken_streak_resets_to_1(self, _mock_deps) -> None:
        mock_get, mock_upsert, _eco = _mock_deps

        with patch(f"{_MODULE}._today_cst", return_value=date(2026, 5, 15)):
            # 上次签到是 5/13，跳过了 5/14 → 断签
            mock_get.return_value = _make_record(
                last_date=date(2026, 5, 13), streak=10, total=30,
            )
            result = await do_checkin(12345)

        assert result.streak == 1
        assert result.total_checkins == 31

    async def test_streak_cycles_after_30(self, _mock_deps) -> None:
        mock_get, mock_upsert, _eco = _mock_deps

        with patch(f"{_MODULE}._today_cst", return_value=date(2026, 5, 15)):
            mock_get.return_value = _make_record(
                last_date=date(2026, 5, 14), streak=30, total=60,
            )
            result = await do_checkin(12345)

        # 30 % 30 + 1 = 1，循环重置
        assert result.streak == 1
        assert result.total_checkins == 61

    async def test_milestone_day_7(self, _mock_deps) -> None:
        mock_get, mock_upsert, _eco = _mock_deps

        with patch(f"{_MODULE}._today_cst", return_value=date(2026, 5, 15)):
            mock_get.return_value = _make_record(
                last_date=date(2026, 5, 14), streak=6, total=6,
            )
            result = await do_checkin(12345)

        assert result.streak == 7
        assert result.is_milestone
        assert result.coin == MILESTONE_REWARDS[7][0]
        assert result.score == MILESTONE_REWARDS[7][1]

    async def test_milestone_day_30(self, _mock_deps) -> None:
        mock_get, mock_upsert, _eco = _mock_deps

        with patch(f"{_MODULE}._today_cst", return_value=date(2026, 5, 15)):
            mock_get.return_value = _make_record(
                last_date=date(2026, 5, 14), streak=29, total=29,
            )
            result = await do_checkin(12345)

        assert result.streak == 30
        assert result.is_milestone
        assert result.coin == MILESTONE_REWARDS[30][0]
        assert result.score == MILESTONE_REWARDS[30][1]

    async def test_economy_failure_does_not_crash(self, _mock_deps) -> None:
        """经济系统异常不应阻塞签到流程。"""
        mock_get, mock_upsert, mock_eco = _mock_deps
        mock_get.return_value = None
        mock_eco.add = AsyncMock(side_effect=RuntimeError("DB down"))
        mock_eco.balance = AsyncMock(return_value=0)

        # 不应抛异常
        result = await do_checkin(12345)
        assert not result.already_done
        assert result.streak == 1
