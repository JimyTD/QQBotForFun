"""每日签到工具的数据模型。"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.storage import Base, register_model

# SQLite 需要 INTEGER 才能自增，其他数据库用 BigInteger
_BigAutoId = BigInteger().with_variant(Integer(), "sqlite")


class CheckinRecord(Base):
    """签到记录。每个 QQ 号一条。"""

    __tablename__ = "tool_checkin"

    id: Mapped[int] = mapped_column(_BigAutoId, primary_key=True, autoincrement=True)
    qq_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_checkin_date: Mapped[date] = mapped_column(Date, nullable=False)
    streak: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    total_checkins: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("qq_id", name="ux_tool_checkin_qq"),
    )


register_model(CheckinRecord, migration_group="tool_checkin")
