"""工作提醒 · 定时调度逻辑。

核心机制：
- 每天 00:05（工作日）执行 _plan_today()
- 对每个时段窗口 roll 概率，命中则在窗口内随机选时间注册一次性任务
- 触发时发送随机内容到所有已启用的群
"""

from __future__ import annotations

import base64
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment

# ======================== 时区 ========================

CST = timezone(timedelta(hours=8))  # 北京时间


def _now() -> datetime:
    """返回北京时间当前时刻。"""
    return datetime.now(CST)


def _today() -> date:
    """返回北京时间今天日期。"""
    return _now().date()

# ======================== 配置 ========================

_ROOT = Path(__file__).resolve().parents[4]  # src/plugins/tools/reminder -> 项目根

WINDOWS: dict[str, dict[str, Any]] = {
    "morning": {
        "start": time(10, 0),
        "end": time(11, 30),
        "probability": 0.6,
    },
    "afternoon": {
        "start": time(14, 30),
        "end": time(16, 30),
        "probability": 0.5,
    },
    "offwork": {
        "start": time(19, 0),
        "end": time(21, 0),
        "probability": 0.7,
    },
}


# ======================== 内容池 ========================

class ContentItem:
    """内容条目：text 或 image。"""

    def __init__(self, type_: str, *, msg: str = "", category: str = "") -> None:
        self.type = type_
        self.msg = msg
        self.category = category


CONTENT_POOL: dict[str, list[ContentItem]] = {
    "morning": [
        ContentItem("text", msg="🧘 已经坐了快 2 小时了，站起来活动活动吧~"),
        ContentItem("text", msg="💪 久坐伤身，起来扭扭脖子！"),
        ContentItem("text", msg="☕ 去接杯水顺便走走？"),
        ContentItem("text", msg="🦴 脖子还好吗？转转头看看窗外"),
        ContentItem("text", msg="🚶 起来走两步，坐太久血液不循环"),
        ContentItem("image", category="stand"),
    ],
    "afternoon": [
        ContentItem("text", msg="☕ 下午茶时间！喝点东西提提神"),
        ContentItem("text", msg="🧘 坐了一下午了，起来动一动"),
        ContentItem("text", msg="👀 看看远处让眼睛休息一下"),
        ContentItem("text", msg="🍵 喝口水，下午继续冲"),
        ContentItem("image", category="afternoon"),
    ],
    "offwork": [
        ContentItem("text", msg="🏃 下班啦！准时下班快乐每一天~"),
        ContentItem("text", msg="🌆 该走了该走了，明天再卷也不迟"),
        ContentItem("text", msg="💼 记得关电脑，别等保安赶人"),
        ContentItem("text", msg="🎉 恭喜你又摸了一天鱼！"),
        ContentItem("text", msg="⏰ 准时下班是对公司最起码的尊重"),
        ContentItem("text", msg="🚪 都这个点了还不走？"),
        ContentItem("image", category="offwork"),
    ],
}


# ======================== 图片缓存 ========================

_image_cache: dict[str, list[Path]] = {}


def load_image_cache() -> None:
    """启动时扫描图片文件，避免定时触发时做同步 IO。"""
    categories = {
        "stand": "resources/reminders/stand_*",
        "afternoon": "resources/reminders/afternoon_*",
        "offwork": "resources/reminders/offwork_*",
    }
    for cat, pattern in categories.items():
        files = [p for p in _ROOT.glob(pattern) if p.is_file()]
        _image_cache[cat] = files
        logger.info(f"[reminder] image cache: {cat} = {len(files)} files")


# ======================== 调度 ========================

# 今日已规划标记，防止重复规划
_planned_date: date | None = None


async def plan_today() -> None:
    """为今天所有窗口规划发送时间。仅工作日执行。"""
    global _planned_date
    today = _today()

    if today.weekday() >= 5:  # 周末不发
        logger.debug("[reminder] weekend, skip planning")
        return

    _planned_date = today
    now = _now()
    planned_count = 0

    for slot_name, config in WINDOWS.items():
        # 在窗口内随机选一个分钟
        start_min = config["start"].hour * 60 + config["start"].minute
        end_min = config["end"].hour * 60 + config["end"].minute
        chosen_min = random.randint(start_min, end_min - 1)
        trigger_time = datetime.combine(today, time(chosen_min // 60, chosen_min % 60), tzinfo=CST)

        # 跳过已过去的时间（用于 bot 中途启动补偿场景）
        if trigger_time <= now:
            logger.debug(f"[reminder] {slot_name} skipped (time already passed: {trigger_time:%H:%M})")
            continue

        # 注册一次性定时任务
        delay_seconds = (trigger_time - now).total_seconds()
        from core.scheduler import schedule_once

        await schedule_once(
            delay_seconds,
            _send_reminder,
            tag="reminder_daily",
            slot=slot_name,
        )
        planned_count += 1
        logger.info(f"[reminder] planned {slot_name} at {trigger_time:%H:%M}")

    logger.info(f"[reminder] today planned {planned_count} reminders")


async def _send_reminder(slot: str) -> None:
    """一次性定时任务触发回调。"""
    from .storage import get_enabled_groups_by_mode

    # 1. 查询启用的群（按模式分组）
    groups_by_mode = await get_enabled_groups_by_mode()
    always_groups = groups_by_mode.get("always", [])
    random_groups = groups_by_mode.get("random", [])

    # 对 random 模式的群做概率判定
    probability = WINDOWS.get(slot, {}).get("probability", 0.5)
    active_random = [g for g in random_groups if random.random() <= probability]

    target_groups = always_groups + active_random
    if not target_groups:
        logger.debug(f"[reminder] {slot} triggered but no target groups")
        return

    # 2. 随机选内容
    pool = CONTENT_POOL.get(slot)
    if not pool:
        return
    item = random.choice(pool)

    # 3. 构造消息
    msg: str | Message
    if item.type == "text":
        msg = item.msg
    elif item.type == "image":
        images = _image_cache.get(item.category, [])
        if images:
            img_path = random.choice(images)
            try:
                b64 = base64.b64encode(img_path.read_bytes()).decode()
                msg = Message(MessageSegment.image(f"base64://{b64}"))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[reminder] failed to read image {img_path}: {e}")
                return
        else:
            logger.warning(f"[reminder] no images for category={item.category}, skipping")
            return
    else:
        return

    # 4. 群发（静默失败）
    from core.session import broadcast

    for group_id in target_groups:
        try:
            await broadcast(int(group_id), msg)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[reminder] send failed group={group_id}: {e}")

    logger.info(f"[reminder] sent {slot} to {len(target_groups)} groups (always={len(always_groups)}, random={len(active_random)})")


def is_planned_today() -> bool:
    """检查今天是否已规划。"""
    return _planned_date == _today()
