"""经济天气 · 小工具插件。

详见 docs/tools/finance.md。

功能：
- 每工作日 15:30 检测市场异动 + 宏观数据更新
- 自动生成大白话播报，推送到启用的群
- 群级开关，任何群友可控制
"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from . import models  # noqa: F401

try:
    from nonebot import get_driver

    get_driver()
    from . import commands  # noqa: F401
    from .scheduler_jobs import daily_finance_report

    driver = get_driver()

    @driver.on_startup
    async def _finance_startup() -> None:
        from nonebot import logger
        from core.scheduler import schedule_cron
        from .config import CRON_SCHEDULE

        await schedule_cron(CRON_SCHEDULE, daily_finance_report, tag="finance_daily_report")
        logger.info(f"[finance] registered daily report cron ({CRON_SCHEDULE})")

except Exception:
    pass


__plugin_meta__ = PluginMetadata(
    name="finance",
    description="经济天气 · 每日播报",
    usage="经济天气 开/关/查看",
)
