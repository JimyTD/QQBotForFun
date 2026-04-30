"""'今天吃什么' 工具的数据模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.storage import Base, register_model


class FoodItem(Base):
    """菜品条目。"""

    __tablename__ = "tool_food_item"

    # 用英文 snake_case 做主键（如 "malatang"），便于人工维护 + 对应图片文件名
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)  # 展示名"麻辣烫"
    description: Mapped[str] = mapped_column(Text, nullable=False)  # 2-3 句说明
    image_path: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 相对项目根
    tags: Mapped[str] = mapped_column(String(128), default="", nullable=False)  # 逗号分隔
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_tool_food_item_created_at", "created_at"),
    )


register_model(FoodItem, migration_group="tool_food")
