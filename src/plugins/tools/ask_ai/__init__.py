"""查资料（搜索优先）—— 联网搜索 + LLM 总结。

触发方式：@机器人 查资料/搜索/问AI/ai <问题>
行为：优先联网搜索获取实时信息，由 LLM 总结后回答。
      仅当搜索不可用或问题明显无需搜索时 fallback 到纯 LLM。
"""

from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="ask_ai",
    description="查资料（搜索优先）：联网搜索 + LLM 总结",
    usage="@机器人 查资料/搜索 你的问题",
)

from . import commands as commands  # noqa: E402, F401
