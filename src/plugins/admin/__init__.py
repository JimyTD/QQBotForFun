"""管理员指令插件。"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from . import handlers  # noqa: F401

__plugin_meta__ = PluginMetadata(
    name="admin",
    description="管理员指令",
    usage="/admin",
)
