"""AI 助手编排：输入 → 意图 → 工具 → 交付结果。"""

from __future__ import annotations

from nonebot import logger

from core import llm
from src.plugins.tools.web_search.models import (
    SearchError,
    SearchNotConfiguredError,
    SearchResult,
    format_results_for_llm,
    format_sources_for_user,
)
from src.plugins.tools.web_search.service import search

from . import context
from .image_search import (
    ImageSearchFailedError,
    download_valid_image,
    image_mime_to_base64,
    search_images,
)
from .intent import classify, image_query
from .media import ImageInputError, fetch_image, prepare_image
from .models import AskResult, AssistantInput, SearchState, TaskKind
from .prompts import (
    build_chat_system_prompt,
    build_router_system_prompt,
    build_search_system_prompt,
    build_vision_system_prompt,
)
from .recency import (
    drop_stale_results,
    is_recency_question,
    rewrite_search_query,
)

_FOLLOW_UP = ("继续", "展开", "详细说", "第二点", "这个", "刚才", "上面")


async def answer(
    user_input: AssistantInput,
    *,
    classify_with_llm: bool = True,
) -> AskResult:
    text = user_input.text.strip()
    history = context.history(user_input.group_id, user_input.user_id)
    kind = classify(text, has_image=user_input.has_image)

    if classify_with_llm and not user_input.has_image and _needs_llm_router(text, kind):
        kind, routed_query = await _route_with_llm(text)
        if routed_query:
            text = routed_query if kind != TaskKind.CHAT else text
    elif kind == TaskKind.IMAGE_SEARCH:
        text = image_query(text)

    if kind == TaskKind.IMAGE_SEARCH:
        previous = context.last(user_input.group_id, user_input.user_id)
        query = text or (previous.search_query if previous else "")
        if not query:
            return AskResult(
                answer="告诉我想找什么图，我就帮你找。",
                error="missing_image_query",
            )
        return await _answer_image_search(query, user_input)

    if kind == TaskKind.IMAGE_UNDERSTAND:
        return await _answer_image_understand(text, user_input, history)

    if kind == TaskKind.WEB_SEARCH:
        return await _answer_web_search(text, user_input, history)

    return await _answer_chat(text, user_input, history)


def _needs_llm_router(text: str, kind: TaskKind) -> bool:
    if len(text) < 3:
        return False
    # 规则已能明确判定聊天和时效问题时不必多花一次模型调用。
    # 疑问句、指代句和规则无法识别的句子交给 LLM 分类，避免把“帮我搜个壁纸”
    # 这类换个说法的图片请求误判成普通聊天。
    if kind != TaskKind.CHAT:
        return False
    if any(word in text for word in _FOLLOW_UP):
        return False
    return any(mark in text for mark in ("?", "？", "吗", "怎么", "搜", "找", "图"))


async def _route_with_llm(text: str) -> tuple[TaskKind, str]:
    try:
        resp = await llm.chat(
            messages=[
                llm.LLMMessage(role="system", content=build_router_system_prompt()),
                llm.LLMMessage(role="user", content=text),
            ],
            scene="ask_ai",
            max_tokens=160,
            json_mode=True,
        )
        data = resp.json()
        kind = TaskKind(str(data.get("kind", "chat")))
        query = str(data.get("query") or "").strip()
        return kind, query
    except Exception as e:  # noqa: BLE001
        logger.info(f"[ask_ai] 意图分类失败，使用规则结果: {e}")
        return TaskKind.CHAT, ""


async def _answer_chat(
    text: str,
    user_input: AssistantInput,
    history: list[context.Turn],
) -> AskResult:
    messages = [llm.LLMMessage(role="system", content=build_chat_system_prompt())]
    if history:
        messages.append(
            llm.LLMMessage(role="system", content=_history_prompt(history))
        )
    messages.append(llm.LLMMessage(role="user", content=text))
    try:
        resp = await llm.chat(messages=messages, scene="ask_ai")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ask_ai] 直答失败: {e}")
        return AskResult(answer="", error="llm_unavailable")
    result = AskResult(
        answer=resp.content.strip(),
        truncated=resp.truncated,
        status_message="",
    )
    context.remember(
        user_input.group_id,
        user_input.user_id,
        question=text,
        answer=result.answer,
    )
    return result


async def _answer_web_search(
    text: str,
    user_input: AssistantInput,
    history: list[context.Turn],
) -> AskResult:
    previous = context.last(user_input.group_id, user_input.user_id)
    query = text
    if _is_follow_up(text) and previous and previous.search_query:
        query = f"{previous.search_query} {text}"
    search_q = rewrite_search_query(query)
    try:
        bundle = await search(search_q)
    except SearchNotConfiguredError:
        fallback = await _answer_chat(text, user_input, history)
        fallback.search_state = SearchState.FAILED
        fallback.error = "search_not_configured"
        return fallback
    except SearchError:
        fallback = await _answer_chat(text, user_input, history)
        fallback.search_state = SearchState.FAILED
        fallback.answer = _prepend_status(
            fallback.answer,
            "联网检索失败，以下是基于已有知识的回答。",
        )
        fallback.error = "search_failed"
        return fallback

    results = bundle.web_results
    if is_recency_question(query):
        results = drop_stale_results(results)
    if not results:
        fallback = await _answer_chat(text, user_input, history)
        fallback.search_state = SearchState.FAILED
        fallback.answer = _prepend_status(
            fallback.answer,
            "没有检索到可靠材料，以下是基于已有知识的回答。",
        )
        fallback.error = "no_results"
        return fallback

    answer, truncated = await _summarize_with_materials(text, results)
    if not answer:
        answer = _fallback_summary(results)
    result = AskResult(
        answer=answer,
        sources=format_sources_for_user(results),
        used_search=True,
        search_state=SearchState.USED,
        truncated=truncated,
    )
    context.remember(
        user_input.group_id,
        user_input.user_id,
        question=text,
        answer=answer,
        search_query=search_q,
    )
    logger.info(
        f"[ask_ai] q={text[:40]!r} search={search_q[:40]!r} "
        f"hits={len(results)} len={len(answer)}"
    )
    return result


async def _summarize_with_materials(
    text: str, results: list[SearchResult]
) -> tuple[str, bool]:
    prompt = (
        f"用户问题：{text}\n\n"
        f"检索材料：\n\n{format_results_for_llm(results)}\n\n"
        "请依据材料把问题答完。"
    )
    try:
        resp = await llm.chat(
            messages=[
                llm.LLMMessage(role="system", content=build_search_system_prompt()),
                llm.LLMMessage(role="user", content=prompt),
            ],
            scene="web_search",
        )
        return resp.content.strip(), resp.truncated
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ask_ai] 检索总结失败: {e}")
        return "", False


def _fallback_summary(results: list[SearchResult]) -> str:
    lines = []
    for r in results[:3]:
        bit = (r.body or r.snippet).strip()
        if bit:
            lines.append(f"• {r.title}：{bit[:160]}")
    return "\n".join(lines) or "搜到了结果，但暂时无法整理成回答。"


async def _answer_image_understand(
    text: str,
    user_input: AssistantInput,
    history: list[context.Turn],
) -> AskResult:
    if not user_input.image_urls:
        return AskResult(answer="把要看的图片和问题一起发给我。")
    texts = [text or "看看这张图是什么，并说明关键细节。"]
    if history:
        texts.append(_history_prompt(history))

    content: list[dict] = [{"type": "text", "text": "\n\n".join(texts)}]
    try:
        for url in user_input.image_urls[:2]:
            raw = await fetch_image(url)
            prepared = prepare_image(raw)
            content.append(
                {"type": "image_url", "image_url": {"url": prepared.data_url}}
            )
            logger.info(
                f"[ask_ai] vision input {prepared.width}x{prepared.height} "
                f"{prepared.size_bytes}B"
            )
    except ImageInputError as e:
        return AskResult(answer=str(e), error="image_input_invalid")

    try:
        resp = await llm.chat(
            messages=[
                llm.LLMMessage(role="system", content=build_vision_system_prompt()),
                llm.LLMMessage(role="user", content=content),
            ],
            scene="vision",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ask_ai] 图片理解失败: {e}")
        return AskResult(
            answer="这张图暂时无法识别，请稍后再试，或改用文字描述。",
            error="vision_unavailable",
        )

    answer = resp.content.strip()
    result = AskResult(answer=answer, truncated=resp.truncated)
    context.remember(
        user_input.group_id,
        user_input.user_id,
        question=text or "[图片]",
        answer=answer,
    )
    return result


async def _answer_image_search(query: str, user_input: AssistantInput) -> AskResult:
    if "换一张" in query or "再来一张" in query or "再找一张" in query:
        previous = context.last(user_input.group_id, user_input.user_id)
        query = previous.search_query if previous else query
    previous = context.last(user_input.group_id, user_input.user_id)
    exclude: set[str] = set()
    if previous and previous.image_urls:
        exclude = set(previous.image_urls)
    try:
        candidates = await search_images(query)
        raw, mime, chosen = await download_valid_image(candidates, exclude_urls=exclude)
    except SearchNotConfiguredError:
        return AskResult(
            answer="图片和联网搜索尚未配置。请在服务器 .env 填入 BOCHA_API_KEY 后重启 bot。",
            search_state=SearchState.FAILED,
            error="search_not_configured",
        )
    except (SearchError, ImageSearchFailedError) as e:
        logger.info(f"[ask_ai] 图片搜索失败 q={query!r}: {e}")
        return AskResult(
            answer="没有找到可直接发送的合适图片，换个关键词再试试。",
            search_state=SearchState.FAILED,
            error="image_search_failed",
        )

    encoded = image_mime_to_base64(raw, mime)
    caption = f"给你找了一张：{chosen.title[:60]}" if chosen.title else "给你找了一张图。"
    result = AskResult(
        answer="",
        images=[encoded],
        image_caption=caption,
        sources=[chosen.page_url] if chosen.page_url else [],
        used_search=True,
        search_state=SearchState.USED,
    )
    context.remember(
        user_input.group_id,
        user_input.user_id,
        question=query,
        answer=caption,
        search_query=query,
        image_urls=[chosen.content_url],
    )
    return result


def _history_prompt(history: list[context.Turn]) -> str:
    return "最近对话（只用于理解追问）：\n" + context.build_context_text(history)


def _is_follow_up(text: str) -> bool:
    return any(word in text for word in _FOLLOW_UP) and len(text) <= 30


def _prepend_status(answer: str, status: str) -> str:
    return f"{status}\n\n{answer}" if answer else status
