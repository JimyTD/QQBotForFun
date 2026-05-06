"""查资料命令处理器。

触发方式：
    @机器人 查资料 <问题>
    @机器人 问AI <问题>
    @机器人 ai <问题>

行为：调用 LLM 回答问题，单次问答，无状态，不涉及经济/对局/排行。
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me
from nonebot.adapters.onebot.v11 import Message

from core import llm, render


_SYSTEM_PROMPT = (
    "你是一个群聊助手，回答用户的问题。\n"
    "要求：\n"
    "- 回答简洁明了，控制在 300 字以内\n"
    "- 如果不确定答案，诚实说明\n"
    "- 不要输出 Markdown 格式，用纯文本\n"
    "- 语气轻松友好"
)


_cmd = on_command(
    "查资料",
    aliases={"问AI", "问ai", "ai", "AI"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_cmd.handle()
async def _(matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()) -> None:
    question = args.extract_plain_text().strip()
    if not question:
        await matcher.finish(
            render.text_card(
                "查资料",
                [
                    "用法：@我 查资料 你的问题",
                    "",
                    "示例：",
                    "  @我 查资料 量子力学是什么",
                    "  @我 ai Python怎么读文件",
                ],
                emoji="🔍",
            )
        )
        return

    # 调用 LLM
    try:
        resp = await llm.chat(
            messages=[
                llm.LLMMessage(role="system", content=_SYSTEM_PROMPT),
                llm.LLMMessage(role="user", content=question),
            ],
            scene="ask_ai",
        )
        answer = resp.content.strip()
    except Exception:  # noqa: BLE001
        await matcher.finish("⚠️ AI 暂时走神了，请稍后再试。")
        return

    if not answer:
        await matcher.finish("⚠️ AI 没有返回有效回答，请换个问法试试。")
        return

    await matcher.finish(
        render.text_card(
            "🔍 查资料",
            [answer],
            emoji="🔍",
            footer=[f"Q: {question[:30]}{'…' if len(question) > 30 else ''}"],
        )
    )
