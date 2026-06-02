"""经济天气 · 数据模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.storage import Base, register_model


class FinanceGroup(Base):
    """群播报开关。"""

    __tablename__ = "tool_finance_groups"

    group_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    enabled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    enabled_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


class FinanceMacroSeen(Base):
    """宏观数据已播报记录，用于去重。"""

    __tablename__ = "tool_finance_macro_seen"

    indicator_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_date: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_value: Mapped[str] = mapped_column(Text, default="", nullable=False)


register_model(FinanceGroup, migration_group="tool_finance")
register_model(FinanceMacroSeen, migration_group="tool_finance")
