"""核心通用指令插件。"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from . import handlers  # noqa: F401

__plugin_meta__ = PluginMetadata(
    name="core_commands",
    description="系统通用指令：/help /menu /profile /balance",
    usage="/help",
)
