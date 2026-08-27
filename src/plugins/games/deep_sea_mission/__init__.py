"""深海任务插件。"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from . import game  # noqa: F401

try:
    from nonebot import get_driver

    get_driver()
    from . import commands  # noqa: F401
except Exception:
    pass

__plugin_meta__ = PluginMetadata(
    name="deep_sea_mission",
    description="深海任务：合作吃墩桌游框架",
    usage="@我 深海任务 8",
)
