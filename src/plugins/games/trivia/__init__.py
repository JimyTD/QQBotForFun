"""趣味问答 NoneBot 插件入口。"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from . import game  # noqa: F401  触发 @register_game

# 仅当 NoneBot 已初始化时才加载指令模块（测试中直接导入本包时跳过）
try:
    from nonebot import get_driver

    get_driver()
    from . import commands  # noqa: F401
except Exception:
    pass

__plugin_meta__ = PluginMetadata(
    name="trivia",
    description="趣味问答（6 类线索猜答案）",
    usage="/开始 trivia [类型]",
)
