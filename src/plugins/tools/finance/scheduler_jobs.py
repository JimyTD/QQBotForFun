"""经济天气 · 定时播报任务。

每个工作日北京时间 15:30 执行。
"""

from __future__ import annotations

from datetime import date

from nonebot import logger

from .detector import run_detection
from .reporter import generate_report
from .storage import get_enabled_groups


async def daily_finance_report() -> None:
    """定时任务入口：检测 + 生成报告 + 群发。仅中国法定工作日执行。"""
    from chinese_calendar import is_workday

    today = date.today()
    if not is_workday(today):
        logger.debug(f"[finance] {today} is not a CN workday, skip")
        return

    logger.info("[finance] daily report job started")

    try:
        anomalies, macros, top_mover = await run_detection()
        logger.info(f"[finance] detection done: {len(anomalies)} anomalies, {len(macros)} macros")

        report = await generate_report(anomalies, macros, top_mover)
        if report is None:
            logger.info("[finance] nothing to report today, skip")
            return

        groups = await get_enabled_groups()
        if not groups:
            logger.info("[finance] no enabled groups, skip")
            return

        from core.session import broadcast

        for group_id in groups:
            try:
                await broadcast(int(group_id), report)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[finance] send failed group={group_id}: {e}")

        logger.info(f"[finance] report sent to {len(groups)} groups")

    except Exception as e:  # noqa: BLE001
        logger.error(f"[finance] daily report failed: {e}", exc_info=True)
