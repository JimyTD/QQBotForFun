"""红警2斗蛐蛐 —— 独立于帝国3斗蛐蛐。"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from . import game  # noqa: F401  触发 @register_game

try:
    from nonebot import get_driver

    get_driver()
    from . import commands  # noqa: F401
except Exception:
    pass

__plugin_meta__ = PluginMetadata(
    name="ra2_battle",
    description="红警2斗蛐蛐",
    usage="@我 红警斗蛐蛐 / @我 红警斗蛐蛐 单挑",
)
