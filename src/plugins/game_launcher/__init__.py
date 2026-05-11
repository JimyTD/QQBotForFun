"""游戏大厅插件。"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from . import handlers  # noqa: F401

__plugin_meta__ = PluginMetadata(
    name="game_launcher",
    description="游戏大厅：快捷开局 / 结束",
    usage="@我 海龟汤 / @我 趣味问答",
)
