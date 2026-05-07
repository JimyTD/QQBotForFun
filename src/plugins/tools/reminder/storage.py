"""工作提醒 · 数据库操作。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from core.storage import get_session

from .models import ReminderGroup


async def get_enabled_groups() -> list[str]:
    """返回所有启用提醒的群 ID 列表。"""
    async with get_session() as sess:
        result = await sess.execute(
            select(ReminderGroup.group_id).where(ReminderGroup.enabled == True)  # noqa: E712
        )
        return list(result.scalars().all())


async def set_group_enabled(group_id: str, enabled: bool, operator_id: str) -> bool:
    """设置群开关，返回操作后的状态。"""
    async with get_session() as sess:
        row = await sess.get(ReminderGroup, group_id)
        if row is None:
            row = ReminderGroup(
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
