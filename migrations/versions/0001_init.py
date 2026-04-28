"""init

Revision ID: 0001_init
Revises:
Create Date: 2026-04-28 00:00:00.000000

首次迁移：创建所有公共表 + 海龟汤表。

注意：本项目开发模式下依赖 storage.init_db() 使用 create_all 建表，无需跑 alembic；
     生产模式必须运行 alembic upgrade head。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- user ----------
    op.create_table(
        "user",
        sa.Column("qq_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("nickname", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("avatar_url", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # ---------- economy_balance ----------
    op.create_table(
        "economy_balance",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("qq_id", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=32), nullable=False, server_default="coin"),
        sa.Column("balance", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("qq_id", "currency", name="ux_economy_balance_qq_currency"),
    )
    op.create_index("ix_economy_balance_qq_id", "economy_balance", ["qq_id"])

    # ---------- economy_tx ----------
    op.create_table(
        "economy_tx",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("qq_id", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=32), nullable=False),
        sa.Column("delta", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=128), nullable=False),
        sa.Column("ref_type", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("ref_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_economy_tx_qq_created", "economy_tx", ["qq_id", "created_at"])
    op.create_index("ix_economy_tx_ref", "economy_tx", ["ref_type", "ref_id"])

    # ---------- economy_item ----------
    op.create_table(
        "economy_item",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("qq_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("qq_id", "item_id", name="ux_economy_item_qq_item"),
    )

    # ---------- game_session ----------
    op.create_table(
        "game_session",
        sa.Column("session_id", sa.String(length=32), primary_key=True),
        sa.Column("game_id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("host_id", sa.BigInteger(), nullable=False),
        sa.Column("players", sa.JSON(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("end_reason", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_game_session_game_id", "game_session", ["game_id"])
    op.create_index("ix_game_session_group_id", "game_session", ["group_id"])
    op.create_index(
        "ix_game_session_group_status", "game_session", ["group_id", "status"]
    )
    op.create_index(
        "ix_game_session_game_started", "game_session", ["game_id", "started_at"]
    )

    # ---------- cooldown ----------
    op.create_table(
        "cooldown",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("scope_key", name="ux_cooldown_scope"),
    )

    # ---------- admin_role ----------
    op.create_table(
        "admin_role",
        sa.Column("qq_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="admin"),
        sa.Column("granted_by", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # ---------- turtle_soup puzzle ----------
    op.create_table(
        "game_turtle_soup_puzzle",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="日常"),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.Column("truth", sa.Text(), nullable=False),
        sa.Column("key_clues", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="builtin"),
        sa.Column("difficulty", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("play_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("win_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_game_turtle_soup_puzzle_source", "game_turtle_soup_puzzle", ["source"])
    op.create_index(
        "ix_game_turtle_soup_puzzle_play_count",
        "game_turtle_soup_puzzle",
        ["play_count"],
    )

    # ---------- turtle_soup session ----------
    op.create_table(
        "game_turtle_soup_session",
        sa.Column("session_id", sa.String(length=32), primary_key=True),
        sa.Column("puzzle_id", sa.BigInteger(), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winner_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_game_turtle_soup_session_puzzle_id",
        "game_turtle_soup_session",
        ["puzzle_id"],
    )

    # ---------- turtle_soup question ----------
    op.create_table(
        "game_turtle_soup_question",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("asker_id", sa.BigInteger(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("hint", sa.Text(), nullable=True),
        sa.Column("asked_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_game_turtle_soup_question_session_asked",
        "game_turtle_soup_question",
        ["session_id", "asked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_game_turtle_soup_question_session_asked", "game_turtle_soup_question")
    op.drop_table("game_turtle_soup_question")
    op.drop_index("ix_game_turtle_soup_session_puzzle_id", "game_turtle_soup_session")
    op.drop_table("game_turtle_soup_session")
    op.drop_index("ix_game_turtle_soup_puzzle_play_count", "game_turtle_soup_puzzle")
    op.drop_index("ix_game_turtle_soup_puzzle_source", "game_turtle_soup_puzzle")
    op.drop_table("game_turtle_soup_puzzle")
    op.drop_table("admin_role")
    op.drop_table("cooldown")
    op.drop_index("ix_game_session_game_started", "game_session")
    op.drop_index("ix_game_session_group_status", "game_session")
    op.drop_index("ix_game_session_group_id", "game_session")
    op.drop_index("ix_game_session_game_id", "game_session")
    op.drop_table("game_session")
    op.drop_table("economy_item")
    op.drop_index("ix_economy_tx_ref", "economy_tx")
    op.drop_index("ix_economy_tx_qq_created", "economy_tx")
    op.drop_table("economy_tx")
    op.drop_index("ix_economy_balance_qq_id", "economy_balance")
    op.drop_table("economy_balance")
    op.drop_table("user")
