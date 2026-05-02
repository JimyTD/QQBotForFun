"""/吃什么 等命令处理器。

触发方式：
    /吃什么
    /今天吃什么
    /eat
    /food

行为：从 food_items 表随机抽一道菜，返回文字卡片 + 图片（若存在）。
单次命令，无状态，不涉及经济/对局/排行。
"""

from __future__ import annotations

import base64
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.matcher import Matcher
from nonebot.rule import to_me

from core import render
from src.plugins.tools.food.storage import pick_random


# 项目根目录，用于把 image_path 的相对路径转绝对路径
_ROOT = Path(__file__).resolve().parents[4]  # src/plugins/tools/food/commands.py -> 回到根


_cmd = on_command(
    "吃什么",
    aliases={"今天吃什么", "eat", "food"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_cmd.handle()
async def _(matcher: Matcher) -> None:
    food = await pick_random()
    if food is None:
        await matcher.finish(
            "🍽 菜单还是空的。请管理员先跑 `uv run python scripts/seed_foods.py` 导入种子。"
        )
        return

    # 文字卡片
    card = render.text_card(
        f"🍱 今天吃：{food.name}",
        [food.description],
        emoji="🍱",
    )

    # 组装消息：文字 + 图片（如果有）
    msg = Message(card)
    if food.image_path:
        abs_path = _ROOT / food.image_path
        if abs_path.exists():
            # 用 base64 发送图片（避免 NapCat 容器无法访问 Bot 容器的文件）
            b64 = base64.b64encode(abs_path.read_bytes()).decode()
            msg += MessageSegment.image(f"base64://{b64}")

    await matcher.finish(msg)
