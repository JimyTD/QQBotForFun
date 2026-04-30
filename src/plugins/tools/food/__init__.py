"""今天吃什么 · 小工具插件。

详见 docs/tools/food.md。
"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

# models 是纯 SQLAlchemy，无 NoneBot 依赖，任何环境都能安全 import
from . import models  # noqa: F401

# 只有 NoneBot 已初始化时才加载 commands（避免 seed 脚本 / 测试里踩雷）
try:
    from nonebot import get_driver

    get_driver()
    from . import commands  # noqa: F401
except Exception:
    # 测试环境或 seed 脚本场景：跳过命令注册
    pass


__plugin_meta__ = PluginMetadata(
    name="food",
    description="今天吃什么 · 小工具",
    usage="/吃什么",
)
