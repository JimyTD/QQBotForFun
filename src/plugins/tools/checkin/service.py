"""每日签到核心业务逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from nonebot import logger

from core import economy

from .storage import get_checkin_record, upsert_checkin

# 北京时间 UTC+8
_CST = timezone(timedelta(hours=8))

# ---------- 奖励配置 ----------
# 基础奖励
BASE_COIN = 10
BASE_SCORE = 1

# 连续签到里程碑奖励（替代当天基础奖励）
MILESTONE_REWARDS: dict[int, tuple[int, int]] = {
    # streak -> (coin, score)
    7: (20, 3),
    14: (20, 3),
    21: (20, 3),
    30: (50, 5),
}

# 连续签到满 30 天后循环重置
STREAK_CYCLE = 30


def calc_reward(streak: int) -> tuple[int, int]:
    """根据连续签到天数计算奖励。

    返回 (coin, score)。里程碑日替代基础奖励（不叠加）。
    """
    if streak in MILESTONE_REWARDS:
        return MILESTONE_REWARDS[streak]
    return (BASE_COIN, BASE_SCORE)


def _today_cst() -> date:
    """获取北京时间的今天日期。"""
    return datetime.now(tz=_CST).date()


@dataclass(frozen=True)
class CheckinResult:
    """签到结果。"""

    already_done: bool          # 今天是否已签过
    streak: int                 # 当前连续天数
    total_checkins: int         # 历史总签到次数
    coin: int = 0               # 本次获得的 coin
    score: int = 0              # 本次获得的 score
    coin_balance: int = 0       # 签到后 coin 余额
    score_balance: int = 0      # 签到后 score 余额
    is_milestone: bool = False  # 是否命中里程碑


async def do_checkin(qq_id: int) -> CheckinResult:
    """执行签到。

    - 今天已签过 → 返回 already_done=True
    - 未签过 → 计算连续天数、发放奖励、更新记录
    """
    today = _today_cst()
    record = await get_checkin_record(qq_id)

    # 已签过
    if record is not None and record.last_checkin_date == today:
        return CheckinResult(
            already_done=True,
            streak=record.streak,
            total_checkins=record.total_checkins,
        )

    # 计算连续天数
    if record is not None:
        yesterday = today - timedelta(days=1)
        if record.last_checkin_date == yesterday:
            # 连续签到，满 30 天循环
            new_streak = (record.streak % STREAK_CYCLE) + 1
        else:
            # 断签
            new_streak = 1
        new_total = record.total_checkins + 1
    else:
        # 首次签到
        new_streak = 1
        new_total = 1

    # 计算奖励
    coin, score = calc_reward(new_streak)
    is_milestone = new_streak in MILESTONE_REWARDS

    # 入账
    try:
        await economy.add(qq_id, coin, reason=f"checkin:day{new_streak}", currency="coin")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[checkin] coin add failed: qq={qq_id} err={e}")

    try:
        await economy.add(qq_id, score, reason=f"checkin:day{new_streak}", currency="score")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[checkin] score add failed: qq={qq_id} err={e}")

    # 更新签到记录
    await upsert_checkin(qq_id, today, new_streak, new_total)

    # 查询最新余额
    coin_balance = await economy.balance(qq_id, "coin")
    score_balance = await economy.balance(qq_id, "score")

    return CheckinResult(
        already_done=False,
        streak=new_streak,
        total_checkins=new_total,
        coin=coin,
        score=score,
        coin_balance=coin_balance,
        score_balance=score_balance,
        is_milestone=is_milestone,
    )
