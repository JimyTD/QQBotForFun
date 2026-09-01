"""AI 助手（ai / 查资料）。

触发：@机器人 ai/查资料/搜索 <问题>
行为：联网取材料后写成能用的回答；搜不到再纯模型兜底。
"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="ask_ai",
    description="AI 助手：ai 起手，后面的话联网取材料后作答",
    usage="@机器人 ai 你的问题",
)

try:
    from nonebot import get_driver

    get_driver()
    from . import commands  # noqa: F401
except Exception:
    pass
