"""经济天气 · 数据库操作。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from core.storage import get_session

from .models import FinanceGroup, FinanceMacroSeen


# ── 群开关 ──────────────────────────────────────────────

async def get_enabled_groups() -> list[str]:
    """返回所有启用播报的群 ID 列表。"""
    async with get_session() as sess:
        result = await sess.execute(
            select(FinanceGroup.group_id).where(FinanceGroup.enabled == True)  # noqa: E712
        )
        return list(result.scalars().all())


async def set_group_enabled(group_id: str, enabled: bool, operator_id: str) -> bool:
    """设置群开关，返回操作后的状态。"""
    async with get_session() as sess:
        row = await sess.get(FinanceGroup, group_id)
        if row is None:
            row = FinanceGroup(
                group_id=group_id,
                enabled=enabled,
                enabled_at=datetime.utcnow() if enabled else None,
                enabled_by=operator_id if enabled else None,
            )
            sess.add(row)
        else:
            row.enabled = enabled
            if enabled:
                row.enabled_at = datetime.utcnow()
                row.enabled_by = operator_id
        return row.enabled


# ── 宏观数据去重 ──────────────────────────────────────────

async def get_macro_seen(indicator_id: str) -> tuple[str, str]:
    """返回 (last_date, last_value)，未见过返回空字符串。"""
    async with get_session() as sess:
        row = await sess.get(FinanceMacroSeen, indicator_id)
        if row is None:
            return ("", "")
        return (row.last_date, row.last_value)


async def set_macro_seen(indicator_id: str, date_str: str, value_str: str) -> None:
    """记录已播报的最新数据点。"""
    async with get_session() as sess:
        row = await sess.get(FinanceMacroSeen, indicator_id)
        if row is None:
            row = FinanceMacroSeen(
                indicator_id=indicator_id,
                last_date=date_str,
                last_value=value_str,
            )
            sess.add(row)
        else:
            row.last_date = date_str
            row.last_value = value_str
