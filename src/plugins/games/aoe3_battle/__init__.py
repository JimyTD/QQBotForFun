"""AoE3 电子斗蛐蛐 —— 兵种对战模拟游戏。"""

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
    name="aoe3_battle",
    description="帝国3电子斗蛐蛐（兵种对战模拟 · 押注/单挑）",
    usage="@我 斗蛐蛐 / @我 斗蛐蛐 单挑",
)
