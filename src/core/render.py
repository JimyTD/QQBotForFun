"""Core · render

全文本 UI 排版原语。详见 docs/11-ui-style.md。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------- 常量 ----------
SEP_HEAVY = "━" * 16
SEP_LIGHT = "─" * 16
SEP_DOT = "·" * 18


# ---------- 基础原语 ----------
def title(emoji: str, text: str) -> str:
    prefix = f"{emoji} " if emoji else ""
    return f"{prefix}{text}\n{SEP_HEAVY}"


def section(text: str) -> str:
    return f"▎{text}"


def kv(label: str, value: Any, width: int = 6) -> str:
    return f"{label:<{width}}{value}"


def truncate(text: str, max_chars: int, suffix: str = "…") -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - len(suffix))] + suffix


# ---------- 卡片 ----------
def _lines(x: str | list[str]) -> list[str]:
    return [x] if isinstance(x, str) else list(x)


def text_card(
    title_text: str,
    body: str | list[str],
    *,
    emoji: str = "",
    footer: str | list[str] | None = None,
) -> str:
    parts: list[str] = [title(emoji, title_text)]
    parts.extend(_lines(body))
    if footer:
        parts.append(SEP_LIGHT)
        parts.extend(_lines(footer))
    return "\n".join(parts)


@dataclass
class MenuItem:
    emoji: str
    name: str
    subtitle: str = ""
    command: str = ""


def menu(
    title_text: str,
    items: list[MenuItem],
    *,
    emoji: str = "🎮",
    footer: str | list[str] | None = None,
) -> str:
    lines: list[str] = [title(emoji, title_text)]
    for i, it in enumerate(items):
        prefix = f"{it.emoji} " if it.emoji else ""
        lines.append(f"{prefix}{it.name}")
        if it.subtitle:
            lines.append(f"   {it.subtitle}")
        if it.command:
            lines.append(f"   {it.command}")
        if i < len(items) - 1:
            lines.append("")
    if footer:
        lines.append(SEP_LIGHT)
        lines.extend(_lines(footer))
    return "\n".join(lines)


def list_card(
    title_text: str,
    items: list[str],
    *,
    emoji: str = "",
    footer: str | list[str] | None = None,
) -> str:
    parts: list[str] = [title(emoji, title_text)]
    parts.extend(items)
    if footer:
        parts.append(SEP_LIGHT)
        parts.extend(_lines(footer))
    return "\n".join(parts)


def result(
    title_text: str,
    game_name: str,
    summary: dict[str, Any],
    *,
    emoji: str = "🏆",
    highlight: str | None = None,
    footer: str | list[str] | None = None,
) -> str:
    lines: list[str] = [title(emoji, title_text), game_name, ""]
    width = max((len(str(k)) for k in summary), default=4) + 2
    for k, v in summary.items():
        lines.append(kv(str(k) + "：", str(v), width=width))
    if highlight:
        lines.append("")
        lines.append(highlight)
    if footer:
        lines.append(SEP_LIGHT)
        lines.extend(_lines(footer))
    return "\n".join(lines)


def status_line(actor: str, action: str, response: str) -> str:
    return f"{actor} {action}\n↳ {response}"


# ---------- 分页 ----------
def paginate(items: list[str], page: int, per_page: int = 10) -> tuple[list[str], str]:
    total = max(1, (len(items) + per_page - 1) // per_page)
    page = max(1, min(page, total))
    start = (page - 1) * per_page
    chunk = items[start : start + per_page]
    return chunk, f"({page}/{total})"
