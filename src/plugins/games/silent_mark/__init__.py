"""静夜标记（Silent Mark）· 基于狼人杀框架的「无发言」社交推理游戏。

与深海任务同构：`game.py` 是本体，`commands.py` 是报名房间与指令。
`commands.py` 必须等 NoneBot 初始化之后再导入（`on_command` 需要 driver）。
"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from . import game  # noqa: F401

try:
    from nonebot import get_driver

    get_driver()
    from . import commands  # noqa: F401
except Exception:  # noqa: BLE001
    # 没有 driver 时（例如单测直接 import 本体）不加载命令层
    pass

__plugin_meta__ = PluginMetadata(
    name="silent_mark",
    description="静夜标记：删掉自由发言的狼人杀——用标记代替发言",
    usage="@我 静夜标记 6gods → @我 加入 → 房主 @我 开始",
)
