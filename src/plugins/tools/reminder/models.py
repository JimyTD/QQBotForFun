"""工作提醒 · 数据模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from core.storage import Base, register_model


class ReminderGroup(Base):
    """群提醒开关。"""

    __tablename__ = "tool_reminder_groups"

    group_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="always", nullable=False)  # always / random
    enabled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    enabled_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


register_model(ReminderGroup, migration_group="tool_reminder")
