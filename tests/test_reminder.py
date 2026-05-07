"""工作提醒单元测试。"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


class TestWindowConfig:
    """测试时段窗口配置。"""

    def test_windows_have_correct_keys(self):
        from src.plugins.tools.reminder.scheduler_jobs import WINDOWS

        expected = {"morning", "afternoon", "offwork"}
        assert set(WINDOWS.keys()) == expected

    def test_all_windows_have_required_fields(self):
        from src.plugins.tools.reminder.scheduler_jobs import WINDOWS

        for name, config in WINDOWS.items():
            assert "start" in config, f"{name} missing start"
            assert "end" in config, f"{name} missing end"
            assert "probability" in config, f"{name} missing probability"
            assert isinstance(config["start"], time)
            assert isinstance(config["end"], time)
            assert 0 < config["probability"] <= 1.0

    def test_windows_do_not_overlap(self):
        from src.plugins.tools.reminder.scheduler_jobs import WINDOWS

        ranges = []
        for name, config in WINDOWS.items():
            start_min = config["start"].hour * 60 + config["start"].minute
            end_min = config["end"].hour * 60 + config["end"].minute
            ranges.append((start_min, end_min, name))

        ranges.sort()
        for i in range(len(ranges) - 1):
            assert ranges[i][1] <= ranges[i + 1][0], (
                f"Window {ranges[i][2]} ({ranges[i][0]}-{ranges[i][1]}) "
                f"overlaps with {ranges[i + 1][2]} ({ranges[i + 1][0]}-{ranges[i + 1][1]})"
            )

    def test_no_food_windows(self):
        """确认没有 lunch/dinner 窗口。"""
        from src.plugins.tools.reminder.scheduler_jobs import WINDOWS

        assert "lunch" not in WINDOWS
        assert "dinner" not in WINDOWS


class TestContentPool:
    """测试内容池。"""

    def test_content_pool_matches_windows(self):
        from src.plugins.tools.reminder.scheduler_jobs import CONTENT_POOL, WINDOWS

        assert set(CONTENT_POOL.keys()) == set(WINDOWS.keys())

    def test_each_pool_not_empty(self):
        from src.plugins.tools.reminder.scheduler_jobs import CONTENT_POOL

        for slot, pool in CONTENT_POOL.items():
            assert len(pool) > 0, f"Pool for {slot} is empty"

    def test_image_items_have_valid_category(self):
        from src.plugins.tools.reminder.scheduler_jobs import CONTENT_POOL

        valid_categories = {"stand", "afternoon", "offwork"}
        for slot, pool in CONTENT_POOL.items():
            for item in pool:
                if item.type == "image":
                    assert item.category in valid_categories, (
                        f"Invalid category '{item.category}' in {slot}"
                    )

    def test_no_food_content(self):
        """确认没有食物相关内容。"""
        from src.plugins.tools.reminder.scheduler_jobs import CONTENT_POOL

        assert "lunch" not in CONTENT_POOL
        assert "dinner" not in CONTENT_POOL
        for slot, pool in CONTENT_POOL.items():
            for item in pool:
                if item.type == "image":
                    assert item.category != "food"


class TestImageCache:
    """测试图片缓存加载。"""

    def test_load_image_cache(self):
        from src.plugins.tools.reminder.scheduler_jobs import _image_cache, load_image_cache

        load_image_cache()
        assert "stand" in _image_cache
        assert "afternoon" in _image_cache
        assert "offwork" in _image_cache
        assert "food" not in _image_cache

    def test_image_files_exist(self):
        """验证素材目录下确实有图片。"""
        from src.plugins.tools.reminder.scheduler_jobs import _ROOT

        reminders_dir = _ROOT / "resources" / "reminders"
        if reminders_dir.exists():
            stand = list(reminders_dir.glob("stand_*"))
            afternoon = list(reminders_dir.glob("afternoon_*"))
            offwork = list(reminders_dir.glob("offwork_*"))
            assert len(stand) >= 1, "Expected at least 1 stand image"
            assert len(afternoon) >= 1, "Expected at least 1 afternoon image"
            assert len(offwork) >= 1, "Expected at least 1 offwork image"


class TestPlanToday:
    """测试每日规划逻辑。"""

    async def test_weekend_skip(self):
        """周末不规划。"""
        from src.plugins.tools.reminder import scheduler_jobs

        with patch.object(scheduler_jobs, "_planned_date", None):
            with patch("src.plugins.tools.reminder.scheduler_jobs.date") as mock_date:
                mock_date.today.return_value = date(2026, 5, 9)  # Saturday
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

                mock_schedule = AsyncMock(return_value="job_id")
                with patch("core.scheduler.schedule_once", mock_schedule):
                    await scheduler_jobs.plan_today()
                    mock_schedule.assert_not_called()

    async def test_workday_all_hit(self):
        """工作日 + 所有概率命中 → 3 个任务。"""
        from src.plugins.tools.reminder import scheduler_jobs

        monday = date(2026, 5, 4)
        fake_now = datetime(2026, 5, 4, 0, 6)

        with patch.object(scheduler_jobs, "_planned_date", None):
            with patch("src.plugins.tools.reminder.scheduler_jobs.date") as mock_date:
                mock_date.today.return_value = monday
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

                with patch("src.plugins.tools.reminder.scheduler_jobs.datetime") as mock_dt:
                    mock_dt.now.return_value = fake_now
                    mock_dt.combine = datetime.combine

                    with patch("src.plugins.tools.reminder.scheduler_jobs.random.random", return_value=0.0):
                        with patch("src.plugins.tools.reminder.scheduler_jobs.random.randint", return_value=600):
                            mock_schedule = AsyncMock(return_value="job_id")
                            with patch("core.scheduler.schedule_once", mock_schedule):
                                await scheduler_jobs.plan_today()
                                assert mock_schedule.call_count == 3

    async def test_all_probability_miss(self):
        """所有概率不命中 → 0 个任务。"""
        from src.plugins.tools.reminder import scheduler_jobs

        monday = date(2026, 5, 4)
        fake_now = datetime(2026, 5, 4, 0, 6)

        with patch.object(scheduler_jobs, "_planned_date", None):
            with patch("src.plugins.tools.reminder.scheduler_jobs.date") as mock_date:
                mock_date.today.return_value = monday
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

                with patch("src.plugins.tools.reminder.scheduler_jobs.datetime") as mock_dt:
                    mock_dt.now.return_value = fake_now
                    mock_dt.combine = datetime.combine

                    with patch("src.plugins.tools.reminder.scheduler_jobs.random.random", return_value=1.0):
                        mock_schedule = AsyncMock(return_value="job_id")
                        with patch("core.scheduler.schedule_once", mock_schedule):
                            await scheduler_jobs.plan_today()
                            mock_schedule.assert_not_called()

    async def test_past_windows_skipped(self):
        """启动补偿场景：已过去的窗口不注册。"""
        from src.plugins.tools.reminder import scheduler_jobs

        monday = date(2026, 5, 4)
        # 15:00 → morning 已过，afternoon 部分可用，offwork 未到
        fake_now = datetime(2026, 5, 4, 15, 0)

        with patch.object(scheduler_jobs, "_planned_date", None):
            with patch("src.plugins.tools.reminder.scheduler_jobs.date") as mock_date:
                mock_date.today.return_value = monday
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

                with patch("src.plugins.tools.reminder.scheduler_jobs.datetime") as mock_dt:
                    mock_dt.now.return_value = fake_now
                    mock_dt.combine = datetime.combine

                    # 所有概率命中
                    with patch("src.plugins.tools.reminder.scheduler_jobs.random.random", return_value=0.0):
                        # randint 对 morning 返回 600(10:00) → 已过
                        # 对 afternoon 返回 870(14:30) → 已过
                        # 对 offwork 返回 1140(19:00) → 未到
                        call_count = [0]

                        def fake_randint(a, b):
                            call_count[0] += 1
                            # morning: 10:00 = 600, afternoon: 14:30 = 870, offwork: 19:00 = 1140
                            if a == 600:  # morning
                                return 600
                            elif a == 870:  # afternoon
                                return 870
                            else:  # offwork start=1140
                                return 1140

                        with patch("src.plugins.tools.reminder.scheduler_jobs.random.randint", side_effect=fake_randint):
                            mock_schedule = AsyncMock(return_value="job_id")
                            with patch("core.scheduler.schedule_once", mock_schedule):
                                await scheduler_jobs.plan_today()
                                # 只有 offwork(19:00) 在 15:00 之后
                                assert mock_schedule.call_count == 1


class TestSendReminder:
    """测试发送逻辑。"""

    async def test_no_enabled_groups_skips(self):
        """没有启用群时静默跳过。"""
        from src.plugins.tools.reminder.scheduler_jobs import _send_reminder

        with patch(
            "src.plugins.tools.reminder.scheduler_jobs.get_enabled_groups",
            new_callable=AsyncMock,
            return_value=[],
        ):
            mock_broadcast = AsyncMock()
            with patch("core.session.broadcast", mock_broadcast):
                await _send_reminder(slot="morning")
                mock_broadcast.assert_not_called()

    async def test_text_message_sent(self):
        """文字消息正常发送到启用群。"""
        from src.plugins.tools.reminder.scheduler_jobs import _send_reminder, ContentItem

        text_item = ContentItem("text", msg="test message")
        with patch(
            "src.plugins.tools.reminder.scheduler_jobs.get_enabled_groups",
            new_callable=AsyncMock,
            return_value=["12345", "67890"],
        ):
            with patch("src.plugins.tools.reminder.scheduler_jobs.random.choice", return_value=text_item):
                mock_broadcast = AsyncMock()
                with patch("core.session.broadcast", mock_broadcast):
                    await _send_reminder(slot="morning")
                    assert mock_broadcast.call_count == 2
                    mock_broadcast.assert_any_call(12345, "test message")
                    mock_broadcast.assert_any_call(67890, "test message")

    async def test_broadcast_failure_silent(self):
        """单群发送失败不影响其他群。"""
        from src.plugins.tools.reminder.scheduler_jobs import _send_reminder, ContentItem

        text_item = ContentItem("text", msg="hello")
        with patch(
            "src.plugins.tools.reminder.scheduler_jobs.get_enabled_groups",
            new_callable=AsyncMock,
            return_value=["111", "222", "333"],
        ):
            with patch("src.plugins.tools.reminder.scheduler_jobs.random.choice", return_value=text_item):
                call_log = []

                async def fake_broadcast(gid, msg):
                    call_log.append(gid)
                    if gid == 222:
                        raise RuntimeError("network error")

                with patch("core.session.broadcast", side_effect=fake_broadcast):
                    await _send_reminder(slot="morning")
                    # 所有 3 群都尝试了
                    assert call_log == [111, 222, 333]


class TestStorage:
    """测试数据库操作。"""

    async def test_enable_disable_group(self):
        """开关逻辑。"""
        from src.plugins.tools.reminder.storage import get_enabled_groups, set_group_enabled

        # 初始无群
        groups = await get_enabled_groups()
        assert groups == []

        # 开启
        result = await set_group_enabled("12345", True, "user1")
        assert result is True
        groups = await get_enabled_groups()
        assert "12345" in groups

        # 再次开启（幂等）
        result = await set_group_enabled("12345", True, "user2")
        assert result is True

        # 关闭
        result = await set_group_enabled("12345", False, "user1")
        assert result is False
        groups = await get_enabled_groups()
        assert "12345" not in groups

    async def test_multiple_groups(self):
        """多群独立控制。"""
        from src.plugins.tools.reminder.storage import get_enabled_groups, set_group_enabled

        await set_group_enabled("111", True, "u1")
        await set_group_enabled("222", True, "u2")
        await set_group_enabled("333", False, "u3")

        groups = await get_enabled_groups()
        assert "111" in groups
        assert "222" in groups
        assert "333" not in groups
