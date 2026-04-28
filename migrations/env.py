"""Alembic 迁移环境。

- 自动从 Settings 读取 DATABASE_URL
- 触发所有 models 导入确保 metadata 完整
- 支持 async 引擎
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# 确保项目根和 src 都在 sys.path
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from core.storage import Base, _import_all_models  # noqa: E402
from src.settings import get_settings  # noqa: E402

# Alembic Config
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 触发所有模型导入
_import_all_models()
target_metadata = Base.metadata


def _get_url() -> str:
    url = config.get_main_option("sqlalchemy.url") or ""
    if not url:
        url = get_settings().database_url
    return url


def run_migrations_offline() -> None:
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _get_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
