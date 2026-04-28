"""Core 公共模型。

> 游戏专属模型放在各游戏的 `models.py` 里，不要写在这里。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.storage import Base, TimestampMixin, register_model


# 用于 ORM 主键：SQLite 需要 INTEGER 才能自增，其他数据库用 BigInteger
_BigAutoId = BigInteger().with_variant(Integer(), "sqlite")


# ---------- user ----------
class UserRecord(Base, TimestampMixin):
    __tablename__ = "user"

    qq_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    nickname: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(256), default="", nullable=False)


register_model(UserRecord, migration_group="core")


# ---------- economy ----------
class EconomyBalance(Base, TimestampMixin):
    __tablename__ = "economy_balance"

    id: Mapped[int] = mapped_column(_BigAutoId, primary_key=True, autoincrement=True)
    qq_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(32), nullable=False, default="coin")
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("qq_id", "currency", name="ux_economy_balance_qq_currency"),
    )


register_model(EconomyBalance, migration_group="core")


class EconomyTx(Base):
    __tablename__ = "economy_tx"

    id: Mapped[int] = mapped_column(_BigAutoId, primary_key=True, autoincrement=True)
    qq_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(32), nullable=False)
    delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    ref_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_economy_tx_qq_created", "qq_id", "created_at"),
        Index("ix_economy_tx_ref", "ref_type", "ref_id"),
    )


register_model(EconomyTx, migration_group="core")


class EconomyItem(Base, TimestampMixin):
    __tablename__ = "economy_item"

    id: Mapped[int] = mapped_column(_BigAutoId, primary_key=True, autoincrement=True)
    qq_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("qq_id", "item_id", name="ux_economy_item_qq_item"),
    )


register_model(EconomyItem, migration_group="core")


# ---------- game session ----------
class GameSessionRecord(Base):
    __tablename__ = "game_session"

    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    game_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    host_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    players: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    end_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_game_session_group_status", "group_id", "status"),
        Index("ix_game_session_game_started", "game_id", "started_at"),
    )


register_model(GameSessionRecord, migration_group="core")


# ---------- cooldown (fallback for non-redis) ----------
class CooldownRecord(Base):
    __tablename__ = "cooldown"

    id: Mapped[int] = mapped_column(_BigAutoId, primary_key=True, autoincrement=True)
    scope_key: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        UniqueConstraint("scope_key", name="ux_cooldown_scope"),
    )


register_model(CooldownRecord, migration_group="core")


# ---------- admin ----------
class AdminRole(Base, TimestampMixin):
    __tablename__ = "admin_role"

    qq_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="admin")
    granted_by: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


register_model(AdminRole, migration_group="core")


# 让 Text 类型未使用但保留 import
_ = Text
