"""查资料 / ai 命令处理器。

触发：@机器人 ai/查资料/搜索 <后面整句话>
后面那句话按助手来答（搜材料 + 写成能用的回答），入口本身不改。
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from core import render
from src.plugins.tools.ask_ai.service import answer_question

_cmd = on_command(
    "查资料",
    aliases={"问AI", "问ai", "ai", "AI", "搜索", "搜一下", "search"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_cmd.handle()
async def _(matcher: Matcher, _event: GroupMessageEvent, args: Message = CommandArg()) -> None:
    question = args.extract_plain_text().strip()
    if not question:
        await matcher.finish(
            render.text_card(
                "AI",
                [
                    "用法：@我 ai 你的问题",
                    "",
                    "示例：",
                    "  @我 ai 量子力学是什么",
                    "  @我 ai 今天有什么新闻",
                    "  @我 ai Python怎么读文件",
                ],
                emoji="🔍",
            )
        )
        return

    await matcher.send("⏳ 正在查…")
    result = await answer_question(question)

    if not result.answer:
        await matcher.finish("⚠️ AI 暂时走神了，请稍后再试。")
        return

    body: list[str] = [result.answer]
    if result.sources:
        body.extend(["", "📎 来源："])
        body.extend(result.sources)

    footer = [f"Q: {question[:30]}{'…' if len(question) > 30 else ''}"]
    if not result.used_search:
        footer.append("未联网，仅凭已有知识")

    await matcher.finish(
        render.text_card("AI", body, emoji="🔍", footer=footer)
    )
