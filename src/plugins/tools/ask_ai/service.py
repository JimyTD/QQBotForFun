"""查资料问答后端：搜索材料 + 成文。Bot / CLI 共用。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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


def should_skip_search(question: str) -> bool:
    """仅闲聊/心算跳过搜索。默认都搜，避免凭记忆瞎编。"""
    q = question.strip()
    if len(q) <= 3 and not any("\u4e00" <= c <= "\u9fff" for c in q):
        return True
    return bool(_SKIP_SEARCH_PATTERNS.match(q))


@dataclass
class AskResult:
    answer: str
    sources: list[str] = field(default_factory=list)
    used_search: bool = False


def _snippet_fallback(results: list[SearchResult]) -> str:
    lines = []
    for r in results[:3]:
        bit = r.body or r.snippet
        if bit:
            lines.append(f"• {r.title}: {bit[:120]}")
        else:
            lines.append(f"• {r.title}")
    return "\n".join(lines) or "搜到了结果，但没法整理成回答。"


async def _summarize(question: str, results: list[SearchResult]) -> str:
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
    except Exception:
        return _snippet_fallback(results)
    return answer or _snippet_fallback(results)


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
        search_q = rewrite_search_query(q)
        results = await search(search_q)
        if is_recency_question(q):
            results = drop_stale_results(results)
            if not results and search_q != q:
                results = drop_stale_results(await search(q))
        if results:
            answer = await _summarize(q, results)
            return AskResult(
                answer=answer,
                sources=format_sources_for_user(results),
                used_search=True,
            )

    try:
        answer = await _direct_answer(q)
    except Exception:
        return AskResult(answer="")
    return AskResult(answer=answer, used_search=False)
