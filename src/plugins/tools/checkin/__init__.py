"""每日签到 · 小工具插件。

详见 docs/tools/checkin.md。

功能：
- 每日签到领取 coin + score
- 连续签到阶梯加成（7/14/21/30 天）
- 满 30 天循环重置
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
    from .fortune import load_image_cache

    # 启动时预缓存名人梗图
    load_image_cache()
except Exception:
    # 测试环境或 seed 脚本场景：跳过命令注册
    pass

__plugin_meta__ = PluginMetadata(
    name="checkin",
    description="每日签到 · 小工具",
    usage="@我 签到",
)
