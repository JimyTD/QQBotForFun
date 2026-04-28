"""Pytest 全局 fixture。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 确保项目根和 src 都在 sys.path
_TESTS = Path(__file__).resolve().parent
_ROOT = _TESTS.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

# 测试用内存 SQLite
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("ONEBOT_ACCESS_TOKEN", "test")
os.environ.setdefault("LLM_CONFIG_PATH", "./config/llm.yaml")


@pytest.fixture(autouse=True)
async def _init_db() -> None:
    """每个测试独立的内存数据库。"""
    from core import storage
    from src.settings import get_settings

    get_settings.cache_clear()
    # 每次都新建引擎，避免复用
    await storage.close_db()
    await storage.init_db()
    yield
    await storage.close_db()
