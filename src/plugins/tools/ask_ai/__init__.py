"""查资料 / 问AI —— 单轮 LLM 问答工具。

触发方式：@机器人 查资料 <问题>
行为：调用 LLM 回答问题，单次问答，无状态。
"""

from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="ask_ai",
    description="群内单轮 LLM 问答",
    usage="@机器人 查资料 你的问题",
)

from . import commands as commands  # noqa: E402, F401
