"""查资料问答后端：搜索材料 + 成文。Bot / CLI 共用。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from nonebot import logger

from core import llm
from src.plugins.tools.ask_ai.prompts import (
    build_fallback_system_prompt,
    build_search_system_prompt,
)
from src.plugins.tools.ask_ai.recency import (
    drop_stale_results,
    is_recency_question,
    rewrite_search_query,
)
from src.plugins.tools.web_search.searxng import (
    SearchResult,
    format_results_for_llm,
    format_sources_for_user,
    search,
)

_SKIP_SEARCH_PATTERNS = re.compile(
    r"^("
    r"\d[\d\s\+\-\*\/\.\(\)]*\d"
    r"|你好|hello|hi|嗨|早|晚安|谢谢"
    r"|你是谁|你叫什么"
    r")$",
    re.IGNORECASE,
)

#: 问机器人**自身**的问题：答案就在本地 prompt 里，联网只会搜回垃圾材料。
#: 2026-09-18 生产日志：`你是什么模型` / `介绍一下你自己` / `你能做什么`
#: 三次全被拿去搜狗搜，回答因此被污染，用户只好反复追问。
_SELF_PATTERNS = re.compile(
    r"(你|您)(是|用的|使用|调用|基于)(了)?(什么|哪个|啥)?(模型|大模型|llm|ai|机器人)"
    r"|(介绍|说说|讲讲|说明)(一下)?(你|您)(自己|自身)"
    r"|(你|您)(能|会|可以)(做|干)(什么|啥|哪些)"
    r"|(你|您)(有|提供)(什么|哪些)(功能|能力|玩法|命令|指令)"
    r"|(你|您)(怎么|如何)(用|使用)"
    r"|(你|您)是谁|(你|您)叫什么",
    re.IGNORECASE,
)

#: 口语指令词。检索时没有信息量，却会挤占关键词权重。
_FILLER_WORDS = re.compile(
    r"(请|请问|帮我|帮忙|给我|麻烦您?|我想知道|我想问一下|我想问|想问一下|想问|问一下|"
    r"介绍一下|介绍下|介绍|解释一下|解释|说一下|说明一下|说说|讲讲|告诉我|"
    r"查一下|查查|搜一下|搜索一下|搜索|"
    r"并列出|列出|罗列|列举|分别是|分别|"
    r"总结一下|总结|概括|归纳|"
    r"推荐一下|推荐|建议|"
    r"有哪些|有什么|"
    r"详细|尽量|尽可能)"
)

_PUNCT = re.compile(r"[，。！？、；：,.!?;:~（）()\[\]【】\"'“”‘’…—]+")


def should_skip_search(question: str) -> bool:
    """仅闲聊 / 心算 / 问机器人自身时跳过搜索。默认都搜，避免凭记忆瞎编。"""
    q = question.strip()
    if len(q) <= 3 and not any("\u4e00" <= c <= "\u9fff" for c in q):
        return True
    if _SELF_PATTERNS.search(q):
        return True
    return bool(_SKIP_SEARCH_PATTERNS.match(q))


def condense_query(question: str) -> str:
    """把口语问句压成关键词串，再交给搜狗。

    实测问题（2026-09-18 日志）：整句原话直接丢给搜索引擎，例如
    「介绍一下鸣潮当期卡池和下一期卡池，并列出抽卡推荐」共 24 字，
    指令词挤占关键词权重 → 群友吐槽「搜索有点蠢」。

    保守处理：只删无信息量的指令 / 语气词并规范标点，
    **不做分词、不猜实体**；删过头（无实义）就退回原句。
    """
    q = question.strip()
    if not q:
        return q
    core = _PUNCT.sub(" ", q)
    core = _FILLER_WORDS.sub(" ", core)
    core = re.sub(r"\s+", " ", core).strip()
    return core if len(core) >= 2 else q


@dataclass
class AskResult:
    answer: str
    sources: list[str] = field(default_factory=list)
    used_search: bool = False
    #: 成文时撞上输出上限被截断，调用方应提示用户（别让人看半句话）。
    truncated: bool = False


def _snippet_fallback(results: list[SearchResult]) -> str:
    lines = []
    for r in results[:3]:
        bit = r.body or r.snippet
        if bit:
            lines.append(f"• {r.title}: {bit[:120]}")
        else:
            lines.append(f"• {r.title}")
    return "\n".join(lines) or "搜到了结果，但没法整理成回答。"


async def _summarize(question: str, results: list[SearchResult]) -> tuple[str, bool]:
    """依据材料成文。返回 ``(回答, 是否被截断)``。"""
    search_context = format_results_for_llm(results)
    user_prompt = (
        f"用户问题：{question}\n\n"
        f"搜索材料：\n\n{search_context}\n\n"
        "请依据材料把问题答完。"
    )
    try:
        resp = await llm.chat(
            messages=[
                llm.LLMMessage(role="system", content=build_search_system_prompt()),
                llm.LLMMessage(role="user", content=user_prompt),
            ],
            scene="web_search",
        )
        answer = resp.content.strip()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ask_ai] 成文失败，退回摘要: {e}")
        return _snippet_fallback(results), False
    return (answer or _snippet_fallback(results)), resp.truncated


async def _direct_answer(question: str) -> str:
    resp = await llm.chat(
        messages=[
            llm.LLMMessage(role="system", content=build_fallback_system_prompt()),
            llm.LLMMessage(role="user", content=question),
        ],
        scene="ask_ai",
    )
    return resp.content.strip()


async def answer_question(question: str) -> AskResult:
    """对 `ai` / 查资料 后面的那句话给出完整回答。"""
    q = question.strip()
    if not q:
        return AskResult(answer="")

    if not should_skip_search(q):
        # 先压缩成关键词（去掉「介绍一下…并列出…」这类指令），再补时间锚点。
        search_q = rewrite_search_query(condense_query(q))
        results = await search(search_q)
        if not results and search_q != q:
            # 压缩过猛导致搜空 → 退回原句再试一次，宁可搜得糙也不能不搜。
            search_q = rewrite_search_query(q)
            results = await search(search_q)
        if is_recency_question(q):
            results = drop_stale_results(results)
        if results:
            answer, truncated = await _summarize(q, results)
            # 回答内容以前完全不落盘 —— 事后无法复盘答得好不好，只能靠猜用户吐槽。
            logger.info(
                f"[ask_ai] q={q[:40]!r} search={search_q[:40]!r} "
                f"hits={len(results)} len={len(answer)} truncated={truncated} "
                f"head={answer[:60]!r}"
            )
            return AskResult(
                answer=answer,
                sources=format_sources_for_user(results),
                used_search=True,
                truncated=truncated,
            )

    try:
        answer = await _direct_answer(q)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ask_ai] 直答失败: {e}")
        return AskResult(answer="")
    return AskResult(answer=answer, used_search=False)
