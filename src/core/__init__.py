"""Core 层 · 项目核心抽象层。

游戏插件应 **只** 通过 `core.*` 命名空间与底层交互。
请阅读 docs/03-core-api.md 了解完整 API 契约。
"""

from __future__ import annotations

from core import (
    economy,
    errors,
    game_base,
    llm,
    permission,
    render,
    scheduler,
    session,
    storage,
    types,
    user,
)

__all__ = [
    "errors",
    "types",
    "storage",
    "user",
    "session",
    "economy",
    "permission",
    "scheduler",
    "llm",
    "render",
    "game_base",
]
