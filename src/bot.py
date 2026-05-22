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

# ── 双路径防御 ──────────────────────────────────────────────
# NoneBot 以 "src.plugins.*" 加载插件，而插件内 `from core import X`
# 解析为 "core.X"。若 Python 同时存在 "src.core.X"（通过包路径），
# 两条路径各自创建独立模块实例 → 全局单例(_runners 等) 被分裂。
# 修复：安装 import hook，让 src.core.* 永远指向 core.* 的同一模块。
import importlib as _il


class _CoreAliasHook:
    """Import hook：任何 `src.core.*` 的 import 都重定向到 `core.*`。"""

    def find_module(self, fullname: str, path=None):  # noqa: ANN001
        if fullname == "src.core" or fullname.startswith("src.core."):
            return self
        return None

    def load_module(self, fullname: str):  # noqa: ANN201
        if fullname in sys.modules:
            return sys.modules[fullname]
        # 去掉 "src." 前缀，用 core.* 路径加载
        real_name = fullname[4:]  # "src.core.X" -> "core.X"
        real_mod = _il.import_module(real_name)
        sys.modules[fullname] = real_mod
        return real_mod


sys.meta_path.insert(0, _CoreAliasHook())

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
        command_start={""},
        command_sep={" "},
    )


def _register_adapters() -> None:
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)


def _load_plugins() -> None:
    # 官方插件
    nonebot.load_plugin("nonebot_plugin_apscheduler")

    nonebot.load_plugin("src.plugins.game_launcher")
    nonebot.load_plugin("src.plugins.message_router")

    # 本项目插件
    nonebot.load_plugin("src.plugins.core_commands")
    nonebot.load_plugin("src.plugins.admin")
    nonebot.load_plugin("src.plugins.games.turtle_soup")
    nonebot.load_plugin("src.plugins.games.trivia")
    nonebot.load_plugin("src.plugins.aoe3")  # 须在 aoe3_battle 之前
    nonebot.load_plugin("src.plugins.games.aoe3_battle")
    nonebot.load_plugin("src.plugins.games.ra2_battle")
    # 小工具（tools/）—— 独立拔插式小功能
    nonebot.load_plugin("src.plugins.tools.food")
    nonebot.load_plugin("src.plugins.tools.ask_ai")
    nonebot.load_plugin("src.plugins.tools.reminder")
    nonebot.load_plugin("src.plugins.tools.yugioh_card")
    nonebot.load_plugin("src.plugins.tools.checkin")


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
