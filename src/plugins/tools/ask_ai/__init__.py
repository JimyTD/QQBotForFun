"""AI 助手（ai / 查资料）。

触发：@机器人 ai/查资料/搜索 <问题>，可带图片。
行为：按任务选择直接回答、联网检索、图片搜索或图片理解。
"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="ask_ai",
    description="群聊 AI 助手：问答、联网检索、图片搜索与图片理解",
    usage="@机器人 ai 你的问题",
)

try:
    from nonebot import get_driver

    get_driver()
    from . import commands  # noqa: F401
except Exception:
    pass
