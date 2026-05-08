"""查资料命令处理器（搜索优先版）。

触发方式：
    @机器人 查资料 <问题>
    @机器人 问AI <问题>
    @机器人 ai <问题>
    @机器人 搜索 <问题>
    @机器人 搜一下 <问题>
    @机器人 search <问题>

行为：
    1. 默认先联网搜索（Searxng），将搜索结果交给 LLM 总结回答
    2. 仅当搜索不可用或问题明显无需搜索时，fallback 到纯 LLM 回答
    搜索倾向大：宁可多搜一次，也不要凭记忆瞎编。
"""

from __future__ import annotations

import re

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from core import llm, render
from src.plugins.tools.web_search.searxng import (
    format_results_for_llm,
    format_sources_for_user,
    search,
)


# -------- Prompts --------

_SEARCH_SYSTEM_PROMPT = (
    "你是一个群聊助手，根据搜索结果回答用户的问题。\n"
    "要求：\n"
    "- 优先基于搜索结果回答，如果搜索结果信息不够详细，可以结合你自身的知识补充\n"
    '- 直接给出具体答案，不要说"请参考xx"或"可以查看xx"\n'
    "- 回答简洁明了，控制在 300 字以内\n"
    "- 如果完全不确定答案，诚实说明\n"
    "- 不要输出 Markdown 格式，用纯文本\n"
    "- 语气轻松友好\n"
    "- 不需要逐条引用来源编号"
)

_FALLBACK_SYSTEM_PROMPT = (
    "你是一个群聊助手，回答用户的问题。\n"
    "要求：\n"
    "- 回答简洁明了，控制在 300 字以内\n"
    "- 如果不确定答案，诚实说明\n"
    "- 不要输出 Markdown 格式，用纯文本\n"
    "- 语气轻松友好"
)

# 明显不需要搜索的模式（纯闲聊/简单计算/打招呼等）
_SKIP_SEARCH_PATTERNS = re.compile(
    r"^("
    r"\d[\d\s\+\-\*\/\.\(\)]*\d"  # 纯数学表达式：1+1, 3*5
    r"|你好|hello|hi|嗨|早|晚安|谢谢"  # 简单打招呼
    r"|你是谁|你叫什么"  # 问机器人自身
    r")$",
    re.IGNORECASE,
)


def _should_skip_search(question: str) -> bool:
    """判断是否跳过搜索，直接用 LLM。倾向于不跳过（搜索优先）。"""
    q = question.strip()
    if len(q) <= 3 and not any("\u4e00" <= c <= "\u9fff" for c in q):
        # 极短的非中文输入（如 "hi"）不搜索
        return True
    return bool(_SKIP_SEARCH_PATTERNS.match(q))


# -------- 命令注册 --------

_cmd = on_command(
    "查资料",
    aliases={"问AI", "问ai", "ai", "AI", "搜索", "搜一下", "search"},
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
                    "  @我 搜索 今天有什么新闻",
                    "  @我 ai Python怎么读文件",
                ],
                emoji="🔍",
            )
        )
        return

    # ---- 路径 1：搜索优先 ----
    if not _should_skip_search(question):
        results = await search(question)

        if results:
            # 有搜索结果 → LLM 基于结果总结
            search_context = format_results_for_llm(results)
            user_prompt = (
                f"用户问题：{question}\n\n"
                f"以下是网络搜索结果：\n\n{search_context}\n\n"
                "请基于以上搜索结果回答用户的问题。"
            )

            try:
                resp = await llm.chat(
                    messages=[
                        llm.LLMMessage(role="system", content=_SEARCH_SYSTEM_PROMPT),
                        llm.LLMMessage(role="user", content=user_prompt),
                    ],
                    scene="web_search",
                )
                answer = resp.content.strip()
            except Exception:  # noqa: BLE001
                # LLM 总结失败 → 降级展示摘要
                snippets = [f"• {r.title}: {r.snippet}" for r in results[:3]]
                answer = "\n".join(snippets)

            if not answer:
                answer = "\n".join(f"• {r.title}: {r.snippet}" for r in results[:3])

            sources = format_sources_for_user(results)
            body_lines = [answer, "", "📎 来源："] + sources

            await matcher.finish(
                render.text_card(
                    "🔍 查资料",
                    body_lines,
                    emoji="🔍",
                    footer=[f"Q: {question[:30]}{'…' if len(question) > 30 else ''}"],
                )
            )
            return

        # 搜索无结果 → 继续走 fallback LLM

    # ---- 路径 2：纯 LLM（跳过搜索或搜索无果）----
    try:
        resp = await llm.chat(
            messages=[
                llm.LLMMessage(role="system", content=_FALLBACK_SYSTEM_PROMPT),
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
