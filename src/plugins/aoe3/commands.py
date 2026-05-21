"""AoE3 Bot 端命令处理。"""

from __future__ import annotations

from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot.rule import to_me

from .formatter import (
    render_civ_units,
    render_compare,
    render_unit_card,
)
from .repository import UnitRepo

# ── 主命令 ──────────────────────────────────────────────

aoe3_cmd = on_command("aoe3", aliases={"帝国3", "aoe"}, rule=to_me(), priority=3, block=True)


@aoe3_cmd.handle()
async def _handle_aoe3(bot: Bot, event: GroupMessageEvent) -> None:
    text = event.get_plaintext().strip()
    # 去掉命令前缀
    for prefix in ("aoe3", "帝国3", "aoe"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()
            break

    if not text:
        await aoe3_cmd.finish(
            "帝国时代3百科 🏰\n"
            "用法：\n"
            "  aoe3 <兵种名> — 查属性\n"
            "  aoe3 对比 <A> <B> — 对比\n"
            "  aoe3 文明 <文明名> — 文明兵种"
        )

    repo = UnitRepo.get()

    # ── 对比 ──
    if text.startswith("对比"):
        parts = text[2:].strip().split()
        if len(parts) < 2:
            await aoe3_cmd.finish("用法：aoe3 对比 <兵种A> <兵种B>")
        a_list = repo.search(parts[0], limit=1)
        b_list = repo.search(parts[1], limit=1)
        if not a_list:
            await aoe3_cmd.finish(f"未找到「{parts[0]}」")
        if not b_list:
            await aoe3_cmd.finish(f"未找到「{parts[1]}」")
        msg = render_compare(a_list[0], b_list[0])
        await aoe3_cmd.finish(msg)

    # ── 文明 ──
    if text.startswith("文明"):
        civ = text[2:].strip()
        if not civ:
            await aoe3_cmd.finish("用法：aoe3 文明 <名称>，如：aoe3 文明 日本")
        units = repo.list_by_civ(civ)
        msg = render_civ_units(units, civ)
        await aoe3_cmd.finish(msg)

    # ── 默认：查兵种 ──
    results = repo.search(text)
    if not results:
        await aoe3_cmd.finish(f"未找到「{text}」相关兵种。")

    unit = results[0]
    is_fuzzy = repo.search_is_fuzzy(text)

    # 发 icon + 文字卡片
    import asyncio
    import base64

    from nonebot import logger

    card_text = render_unit_card(unit)
    if is_fuzzy:
        name = unit.name if unit.name != unit.name_en else unit.name_en
        card_text = f"💡 未精确匹配「{text}」，为你找到最接近的：{name}\n\n" + card_text

    icon_path = repo.get_icon_path(unit)
    if icon_path:
        b64 = base64.b64encode(icon_path.read_bytes()).decode()
        rich_msg = MessageSegment.image(f"base64://{b64}") + MessageSegment.text(card_text)
        sent = False
        for attempt in range(1, 3):
            try:
                await bot.send(event, rich_msg)
                sent = True
                break
            except Exception:  # noqa: BLE001
                if attempt < 2:
                    logger.debug("[aoe3] 图片发送第 %d 次失败，重试", attempt)
                    await asyncio.sleep(1)
        if not sent:
            logger.warning("[aoe3] 图片发送失败，降级为纯文本")
            await bot.send(event, card_text)
    else:
        await bot.send(event, card_text)

    # 如果搜索到多个结果，提示
    if len(results) > 1:
        others = "、".join(
            r.name if r.name != r.name_en else r.name_en for r in results[1:4]
        )
        await aoe3_cmd.finish(f"💡 你可能还想查：{others}")
