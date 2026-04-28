"""海龟汤 NoneBot 插件入口。"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from . import game  # noqa: F401  触发 @register_game
from . import models  # noqa: F401

# 仅当 NoneBot 已初始化时才加载指令模块（测试中直接导入本包时跳过）
try:
    from nonebot import get_driver

    get_driver()
    from . import commands  # noqa: F401
except Exception:
    # 测试环境或未初始化时忽略；bot.py 启动后再次 import 时会成功
    pass

__plugin_meta__ = PluginMetadata(
    name="turtle_soup",
    description="海龟汤（LLM 驱动）",
    usage="/play turtle_soup",
)
