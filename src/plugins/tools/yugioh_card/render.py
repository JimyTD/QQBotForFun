"""游戏王卡片信息格式化。

将百鸽 API 返回的卡片数据格式化为文字卡片内容。
百鸽的 `types` 字段已经是格式化好的类型行，直接使用。
"""

from __future__ import annotations

from src.plugins.tools.yugioh_card.api import YugiohCard


def format_card_text(card: YugiohCard) -> list[str]:
    """格式化卡片为文字行列表（用于 render.text_card）。"""
    lines: list[str] = []

    # 类型行（百鸽已格式化，如 "[怪兽|效果] 龙/光\n[★8] 3000/2500"）
    if card.types:
        for type_line in card.types.split("\n"):
            lines.append(type_line)

    # 日文/英文名
    name_parts: list[str] = []
    if card.name_jp:
        name_parts.append(card.name_jp)
    if card.name_en:
        name_parts.append(card.name_en)
    if name_parts:
        lines.append("")
        lines.append(" / ".join(name_parts))

    lines.append("")

    # 效果/描述
    if card.description:
        lines.append(card.description)

    # 密码
    lines.append("")
    lines.append(f"密码: {card.id}")

    return lines


def format_not_found(query: str) -> list[str]:
    """查询无结果时的提示文案。"""
    return [
        f"未找到「{query}」相关的卡片。",
        "",
        "试试：",
        "· 检查卡名是否正确",
        '· 使用部分关键词（如"青眼"而非"青眼白龍"）',
        "· 用密码查询：@我 查卡 #89631139",
    ]
