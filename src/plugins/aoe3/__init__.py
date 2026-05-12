"""AoE3 查询工具 —— 插件入口。"""

from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="帝国时代3百科",
    description="AoE3:DE 兵种查询 / 对比 / 克制 / 文明",
    usage="@Bot aoe3 火枪手 | @Bot aoe3 对比 火枪手 散兵 | @Bot aoe3 克制 骑兵 | @Bot aoe3 文明 日本",
)

try:
    from nonebot import get_driver
    get_driver()
    from . import commands as _commands  # noqa: F401
except Exception:
    pass
