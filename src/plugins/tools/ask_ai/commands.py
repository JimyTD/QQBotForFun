"""AI 问答命令入口：文字、图片、引用和图片交付。"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from core import render
from src.plugins.tools.ask_ai import context
from src.plugins.tools.ask_ai.intent import classify
from src.plugins.tools.ask_ai.message import image_urls, plain_text
from src.plugins.tools.ask_ai.models import AskResult, AssistantInput, SearchState, TaskKind
from src.plugins.tools.ask_ai.orchestrator import answer

_cmd = on_command(
    "AI问答",
    aliases={
        "AI问答",
        "ai问答",
        "问AI",
        "问ai",
        "ai",
        "AI",
        "查资料",
        "搜索",
        "搜一下",
        "search",
    },
    rule=to_me(),
    priority=3,
    block=True,
)

_HELP = [
    "用法：@我 AI问答 你的问题",
    "也可以直接发图后问：@我 AI问答 这是什么",
    "",
    "示例：",
    "  @我 AI问答 解释一下量子纠缠",
    "  @我 AI问答 今天有什么科技新闻",
    "  @我 AI问答 找一张少女前线2奇塔的图",
    "  @我 AI问答 这张截图里的报错怎么解决",
    "",
    "追问：继续 / 第二点展开 / 换一张",
    "清空：@我 AI问答 清空",
]


async def _quoted(bot: Bot, event: MessageEvent) -> Message | None:
    reply = getattr(event, "reply", None)
    if reply is None:
        return None
    message = getattr(reply, "message", None)
    if message is not None:
        return message
    message_id = getattr(reply, "message_id", None)
    if message_id is None:
        return None
    try:
        data = await bot.get_msg(message_id=int(message_id))
    except Exception:  # noqa: BLE001
        return None
    raw = data.get("message") if isinstance(data, dict) else None
    return raw if isinstance(raw, Message) else None


@_cmd.handle()
async def _handle(
    matcher: Matcher,
    bot: Bot,
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    raw_text = plain_text(args)
    input_images = image_urls(args)
    quoted = await _quoted(bot, event)
    quoted_text = plain_text(quoted)
    quoted_images = image_urls(quoted)
    if quoted_images:
        input_images = (input_images + quoted_images)[:2]
    text = raw_text or quoted_text

    user_id = int(event.user_id)
    group_id = int(event.group_id) if isinstance(event, GroupMessageEvent) else None

    if text in ("清空", "清除", "重置") and not input_images:
        context.clear(group_id, user_id)
        await matcher.finish("🧠 当前对话上下文已清空。")
        return

    if not text and not input_images:
        await matcher.finish(render.text_card("AI 问答", _HELP, emoji="🤖"))
        return

    kind = classify(text, has_image=bool(input_images))
    status = _status_for(kind)
    await matcher.send(status)

    result = await answer(
        AssistantInput(
            text=text,
            image_urls=input_images,
            quoted_text=quoted_text,
            group_id=group_id,
            user_id=user_id,
            message_id=str(getattr(event, "message_id", "") or ""),
        )
    )
    await _deliver(matcher, result)


def _status_for(kind: TaskKind) -> str:
    return {
        TaskKind.WEB_SEARCH: "🔎 AI 正在查资料…",
        TaskKind.IMAGE_SEARCH: "🖼️ AI 正在找图…",
        TaskKind.IMAGE_UNDERSTAND: "👀 AI 正在看图…",
    }.get(kind, "💭 AI 正在思考…")


async def _deliver(matcher: Matcher, result: AskResult) -> None:
    if result.images:
        msg = Message(result.image_caption or "给你找了一张图。")
        for image in result.images:
            msg += MessageSegment.image(image)
        if result.sources:
            msg += Message("\n来源：" + "；".join(result.sources[:2]))
        await matcher.finish(msg)
        return

    if not result.answer:
        reason = {
            "search_not_configured": "联网搜索尚未配置，暂时不能查资料。",
            "vision_unavailable": "图片理解服务暂时不可用。",
            "llm_unavailable": "AI 暂时不可用，请稍后再试。",
        }.get(result.error, "AI 暂时没想好怎么回答，请换个问法试试。")
        await matcher.finish("⚠️ " + reason)
        return

    body = [result.answer]
    if result.sources:
        body.extend(["", "📎 来源"])
        body.extend(result.sources)
    footer: list[str] = []
    if result.search_state == SearchState.FAILED:
        footer.append("本次未取得可用的联网结果")
    if result.truncated:
        footer.append("回答达到长度上限，可继续追问细节")
    await matcher.finish(render.text_card("AI 问答", body, emoji="🤖", footer=footer))
