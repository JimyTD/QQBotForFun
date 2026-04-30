"""QQBotForFun · 机器人入口。

使用：
    uv run python -m src.bot
或（安装后）：
    qqbot
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

# 确保 src 目录在 sys.path 上（使得 `from core import ...` 能工作）
_SRC = Path(__file__).resolve().parent
_ROOT = _SRC.parent
for p in (str(_SRC), str(_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.settings import get_settings  # noqa: E402


def _configure_nonebot() -> None:
    settings = get_settings()
    # 将我们的关键字段注入 NoneBot 配置
    nonebot.init(
        driver="~fastapi+~websockets",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        onebot_access_token=settings.onebot_access_token,
        command_start={"/", ""},
        command_sep={" "},
    )


def _register_adapters() -> None:
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)


def _load_plugins() -> None:
    # 官方插件
    nonebot.load_plugin("nonebot_plugin_apscheduler")

    # 消息路由（必须先加载，保证优先级）
    nonebot.load_plugin("src.plugins.message_router")

    # 本项目插件
    nonebot.load_plugin("src.plugins.core_commands")
    nonebot.load_plugin("src.plugins.game_launcher")
    nonebot.load_plugin("src.plugins.admin")
    nonebot.load_plugin("src.plugins.games.turtle_soup")
    nonebot.load_plugin("src.plugins.games.trivia")


def _register_lifecycle() -> None:
    driver = nonebot.get_driver()

    @driver.on_startup
    async def _on_startup() -> None:
        from core import game_base, llm, storage
        from nonebot import logger

        logger.info("[bot] startup: init llm config...")
        try:
            llm.init()
        except Exception as e:  # noqa: BLE001
            logger.error(f"[bot] llm.init failed: {e}")

        logger.info("[bot] startup: init database...")
        await storage.init_db()

        logger.info("[bot] startup: recover active sessions...")
        recovered = await game_base.recover_active_sessions()
        if recovered:
            logger.warning(f"[bot] recovered {recovered} active sessions (all marked aborted)")

        logger.info("[bot] ready.")

    @driver.on_shutdown
    async def _on_shutdown() -> None:
        from core import storage
        from nonebot import logger

        logger.info("[bot] shutdown: close db...")
        await storage.close_db()


def main() -> None:
    _configure_nonebot()
    _register_adapters()
    _load_plugins()
    _register_lifecycle()
    nonebot.run()


if __name__ == "__main__":
    main()


# asyncio 引用保留以避免 linter 警告（部分平台需要）
_ = asyncio
