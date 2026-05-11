"""游戏王查卡 · 小工具插件。"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

try:
    from nonebot import get_driver

    get_driver()
    from . import commands  # noqa: F401
except Exception:
    pass

__plugin_meta__ = PluginMetadata(
    name="yugioh_card",
    description="游戏王卡片查询 · 小工具",
    usage="@我 查卡 卡名",
)
