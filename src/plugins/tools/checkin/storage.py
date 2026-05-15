"""tool_checkin 表的 CRUD 封装。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from core.storage import get_session

from .models import CheckinRecord


async def get_checkin_record(qq_id: int) -> CheckinRecord | None:
    """查询某玩家的签到记录。无记录返回 None。"""
    async with get_session() as sess:
        stmt = select(CheckinRecord).where(CheckinRecord.qq_id == qq_id)
        return (await sess.execute(stmt)).scalar_one_or_none()


async def upsert_checkin(
    qq_id: int, checkin_date: date, streak: int, total_checkins: int,
) -> None:
    """插入或更新签到记录。"""
    async with get_session() as sess:
        stmt = select(CheckinRecord).where(CheckinRecord.qq_id == qq_id)
        record = (await sess.execute(stmt)).scalar_one_or_none()

        if record is None:
            sess.add(
                CheckinRecord(
                    qq_id=qq_id,
                    last_checkin_date=checkin_date,
                    streak=streak,
                    total_checkins=total_checkins,
                )
            )
        else:
            record.last_checkin_date = checkin_date
            record.streak = streak
            record.total_checkins = total_checkins

        await sess.commit()
