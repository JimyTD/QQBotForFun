"""Core · storage

统一的数据库封装。

- 使用 SQLAlchemy 2.0 async
- 公共表：表名无前缀
- 游戏专属表：表名必须以 `game_<id>_` 开头

用法：
    from core.storage import Base, get_session, register_model

    class MyModel(Base):
        __tablename__ = "game_xxx_mytable"
        ...

    register_model(MyModel, migration_group="game_xxx")

    async with get_session() as sess:
        sess.add(MyModel(...))
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.settings import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的共同基类。"""


class TimestampMixin:
    """为模型附加标准 created_at / updated_at 字段（毫秒精度）。"""

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


# ---------- 模型注册（用于诊断 + 表名前缀校验）----------
_registered_models: dict[str, str] = {}  # table_name -> migration_group


def register_model(model: type[Base], migration_group: str = "core") -> None:
    """登记一个模型。游戏专属表会强制校验前缀。

    Args:
        model: SQLAlchemy 模型类
        migration_group: 迁移分组名，例如 "core" 或 "game_turtle_soup"
    """
    table_name: str = model.__tablename__  # type: ignore[attr-defined]
    if migration_group.startswith("game_"):
        # game_<id> 的表名必须以 game_<id>_ 开头
        expect_prefix = migration_group + "_"
        if not table_name.startswith(expect_prefix):
            raise ValueError(
                f"Model {model.__name__} table '{table_name}' does not start with "
                f"required prefix '{expect_prefix}' for migration_group='{migration_group}'."
            )
    _registered_models[table_name] = migration_group


def registered_tables() -> dict[str, str]:
    return dict(_registered_models)


# ---------- 引擎 & Session ----------
_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _create_engine() -> AsyncEngine:
    settings = get_settings()
    url = settings.database_url
    # SQLite 特别处理：允许多线程访问 + 打开外键
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    return engine


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = _create_engine()
        _sessionmaker = async_sessionmaker(
            _engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        _setup_sqlite_pragmas(_engine)
    return _engine


def _setup_sqlite_pragmas(engine: AsyncEngine) -> None:
    """SQLite 启用外键约束。"""
    if not str(engine.url).startswith("sqlite"):
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn: Any, _rec: Any) -> None:  # pragma: no cover
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """获取一个 async session 上下文。自动 commit/rollback。"""
    sm = get_sessionmaker()
    async with sm() as sess:
        try:
            yield sess
            await sess.commit()
        except Exception:
            await sess.rollback()
            raise


async def init_db() -> None:
    """启动时初始化。此处仅确认引擎可建立；建表由 Alembic 负责。

    在 dev 模式下，若数据库是空的 SQLite，也可以用 `Base.metadata.create_all` 做首次建表（方便起步）。
    生产必须走 alembic upgrade。
    """
    settings = get_settings()
    engine = get_engine()
    if settings.is_dev and str(engine.url).startswith("sqlite"):
        # 导入所有模型，确保 metadata 完整
        _import_all_models()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


# Suppress warning: engine is not used here after assignment
_ = Engine  # keep import for potential future typing use


def _import_all_models() -> None:
    """触发所有模型模块导入，确保 metadata 完整。

    新增模型模块时，在此处追加 import（允许缺失以便独立测试）。
    """
    # 公共模型
    try:
        from core import _models_common  # noqa: F401
    except Exception as e:  # noqa: BLE001
        from nonebot import logger

        logger.warning(f"[storage] import _models_common failed: {e}")

    # 游戏模型（按 ID 顺序追加）
    try:
        from src.plugins.games.turtle_soup import models as _ts_models  # noqa: F401
    except Exception as e:  # noqa: BLE001
        from nonebot import logger

        logger.debug(f"[storage] turtle_soup models not loaded: {e}")

    # 小工具模型
    try:
        from src.plugins.tools.food import models as _food_models  # noqa: F401
    except Exception as e:  # noqa: BLE001
        from nonebot import logger

        logger.debug(f"[storage] tools/food models not loaded: {e}")

    try:
        from src.plugins.tools.reminder import models as _reminder_models  # noqa: F401
    except Exception as e:  # noqa: BLE001
        from nonebot import logger

        logger.debug(f"[storage] tools/reminder models not loaded: {e}")
