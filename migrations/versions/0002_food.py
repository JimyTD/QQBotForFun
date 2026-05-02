"""add tool_food_item table

Revision ID: 0002_food
Revises: 0001_init
Create Date: 2026-05-02 11:00:00.000000

创建"今天吃什么"工具的菜品表。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_food"
down_revision: Union[str, None] = "0001_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tool_food_item",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("image_path", sa.String(256), nullable=True),
        sa.Column("tags", sa.String(128), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tool_food_item_created_at", "tool_food_item", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_tool_food_item_created_at", table_name="tool_food_item")
    op.drop_table("tool_food_item")
