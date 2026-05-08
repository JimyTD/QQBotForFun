"""工作提醒 · 小工具插件。

详见 docs/tools/work-reminder.md。

功能：
- 工作日随机时段发送活动/休息/下班提醒
- 群级开关，任何群友可控制
"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

# models 是纯 SQLAlchemy，无 NoneBot 依赖，安全 import
from . import models  # noqa: F401

# 只有 NoneBot 已初始化时才加载 commands + scheduler
try:
    from nonebot import get_driver

    get_driver()
    from . import commands  # noqa: F401
    from .scheduler_jobs import load_image_cache, plan_today, is_planned_today

    # 启动时：加载图片缓存 + 注册每日规划 cron + 启动补偿
    driver = get_driver()

    @driver.on_startup
    async def _reminder_startup() -> None:
        from nonebot import logger
        from core.scheduler import schedule_cron

        # 1. 预加载图片缓存
        load_image_cache()

        # 2. 注册每日规划 cron：工作日北京时间 00:05
        #    apscheduler 按容器默认时区解释（CST），所以直接写 00:05
        await schedule_cron("5 0 * * 1-5", plan_today, tag="reminder_daily_plan")
        logger.info("[reminder] registered daily plan cron (00:05 CST weekdays)")

        # 3. 启动补偿：如果今天还没规划过，立即规划
        if not is_planned_today():
            logger.info("[reminder] startup compensation: planning today...")
            await plan_today()

except Exception:
    # 测试环境或 seed 脚本场景：跳过命令/调度注册
    pass


__plugin_meta__ = PluginMetadata(
    name="reminder",
    description="工作提醒 · 小工具",
    usage="提醒 开/关",
)
