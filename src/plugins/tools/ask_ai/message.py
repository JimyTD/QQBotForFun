"""OneBot 消息段提取。"""

from __future__ import annotations

from nonebot.adapters.onebot.v11 import Message, MessageSegment


def image_urls(message: Message | MessageSegment | None) -> list[str]:
    if message is None:
        return []
    segments = [message] if isinstance(message, MessageSegment) else list(message)
    urls: list[str] = []
    for seg in segments:
        if seg.type != "image":
            continue
        data = seg.data or {}
        url = str(data.get("url") or data.get("file") or "").strip()
        if url.startswith(("http://", "https://")):
            urls.append(url)
    return urls[:2]


def plain_text(message: Message | MessageSegment | None) -> str:
    if message is None:
        return ""
    if isinstance(message, MessageSegment):
        return str(message.data.get("text", "")) if message.type == "text" else ""
    return message.extract_plain_text().strip()
