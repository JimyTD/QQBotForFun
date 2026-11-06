"""OneBot 消息段提取。"""

from __future__ import annotations

from nonebot.adapters.onebot.v11 import Message, MessageSegment


def image_sources(
    message: Message | MessageSegment | None,
) -> tuple[list[str], list[str]]:
    if message is None:
        return [], []
    segments = [message] if isinstance(message, MessageSegment) else list(message)
    urls: list[str] = []
    files: list[str] = []
    for seg in segments:
        if seg.type != "image":
            continue
        data = seg.data or {}
        url = str(data.get("url") or "").strip()
        file = str(data.get("file") or "").strip()
        if not url and file.startswith(("http://", "https://")):
            url = file
        if url.startswith(("http://", "https://")):
            urls.append(url)
            continue
        if file:
            files.append(file)
    return urls[:2], files[:2]


def image_urls(message: Message | MessageSegment | None) -> list[str]:
    return image_sources(message)[0]


def plain_text(message: Message | MessageSegment | None) -> str:
    if message is None:
        return ""
    if isinstance(message, MessageSegment):
        return str(message.data.get("text", "")) if message.type == "text" else ""
    return message.extract_plain_text().strip()
