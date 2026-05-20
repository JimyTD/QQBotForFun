"""Core · economy

跨游戏通用的货币与道具系统。
"""

from __future__ import annotations

from dataclasses import dataclass

from nonebot import logger
from sqlalchemy import func, select

from core._models_common import EconomyBalance, EconomyItem, EconomyTx
from core.errors import InsufficientFundsError
from core.storage import get_session

_registered_currencies: set[str] = {"coin", "ticket", "score"}


def register_currency(currency_id: str) -> None:
    _registered_currencies.add(currency_id)


def is_registered(currency_id: str) -> bool:
    return currency_id in _registered_currencies


# ---------- 货币 ----------
async def balance(qq_id: int, currency: str = "coin") -> int:
    async with get_session() as sess:
        stmt = select(EconomyBalance).where(
            EconomyBalance.qq_id == qq_id, EconomyBalance.currency == currency
        )
        row = (await sess.execute(stmt)).scalar_one_or_none()
        return row.balance if row else 0


async def add(qq_id: int, amount: int, *, reason: str, currency: str = "coin") -> int:
    if amount == 0:
        return await balance(qq_id, currency)
    if amount < 0:
        return await deduct(qq_id, -amount, reason=reason, currency=currency)
    return await _delta(qq_id, amount, reason=reason, currency=currency)


async def deduct(qq_id: int, amount: int, *, reason: str, currency: str = "coin") -> int:
    if amount < 0:
        raise ValueError("amount must be non-negative")
    return await _delta(qq_id, -amount, reason=reason, currency=currency, allow_negative=False)


async def transfer(from_id: int, to_id: int, amount: int, *, reason: str, currency: str = "coin") -> None:
    if amount <= 0:
        raise ValueError("amount must be positive")
    if from_id == to_id:
        return
    await deduct(from_id, amount, reason=f"transfer_out:{reason}", currency=currency)
    try:
        await add(to_id, amount, reason=f"transfer_in:{reason}", currency=currency)
    except Exception:  # noqa: BLE001
        # 回滚
        await add(from_id, amount, reason=f"transfer_rollback:{reason}", currency=currency)
        raise


async def _delta(
    qq_id: int,
    delta: int,
    *,
    reason: str,
    currency: str,
    allow_negative: bool = True,
    ref_type: str = "",
    ref_id: str = "",
) -> int:
    async with get_session() as sess:
        stmt = select(EconomyBalance).where(
            EconomyBalance.qq_id == qq_id, EconomyBalance.currency == currency
        )
        row = (await sess.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = EconomyBalance(qq_id=qq_id, currency=currency, balance=0)
            sess.add(row)
            await sess.flush()
        new_balance = row.balance + delta
        if new_balance < 0 and not allow_negative:
            raise InsufficientFundsError(
                f"qq={qq_id} currency={currency} balance={row.balance} need={-delta}"
            )
        row.balance = new_balance
        sess.add(
            EconomyTx(
                qq_id=qq_id,
                currency=currency,
                delta=delta,
                balance_after=new_balance,
                reason=reason,
                ref_type=ref_type,
                ref_id=ref_id,
            )
        )
        logger.info(
            f"[economy] qq={qq_id} {currency} {delta:+d} -> {new_balance} ({reason})"
        )
        return new_balance


# ---------- 道具 ----------
async def add_item(qq_id: int, item_id: str, count: int = 1) -> None:
    if count <= 0:
        raise ValueError("count must be positive")
    async with get_session() as sess:
        stmt = select(EconomyItem).where(
            EconomyItem.qq_id == qq_id, EconomyItem.item_id == item_id
        )
        row = (await sess.execute(stmt)).scalar_one_or_none()
        if row is None:
            sess.add(EconomyItem(qq_id=qq_id, item_id=item_id, count=count))
        else:
            row.count += count


async def remove_item(qq_id: int, item_id: str, count: int = 1) -> None:
    if count <= 0:
        raise ValueError("count must be positive")
    async with get_session() as sess:
        stmt = select(EconomyItem).where(
            EconomyItem.qq_id == qq_id, EconomyItem.item_id == item_id
        )
        row = (await sess.execute(stmt)).scalar_one_or_none()
        if row is None or row.count < count:
            raise InsufficientFundsError(
                f"item={item_id} qq={qq_id} have={row.count if row else 0} need={count}"
            )
        row.count -= count


async def has_item(qq_id: int, item_id: str, count: int = 1) -> bool:
    async with get_session() as sess:
        stmt = select(EconomyItem).where(
            EconomyItem.qq_id == qq_id, EconomyItem.item_id == item_id
        )
        row = (await sess.execute(stmt)).scalar_one_or_none()
        return row is not None and row.count >= count


async def list_items(qq_id: int) -> dict[str, int]:
    async with get_session() as sess:
        stmt = select(EconomyItem).where(EconomyItem.qq_id == qq_id)
        rows = (await sess.execute(stmt)).scalars().all()
        return {r.item_id: r.count for r in rows if r.count > 0}


# ---------- 榜单 ----------
@dataclass(frozen=True)
class LeaderboardEntry:
    """榜单单条记录。"""

    rank: int          # 1-based 排名
    qq_id: int
    balance: int


async def top_balances(
    currency: str = "score",
    *,
    limit: int = 10,
    min_balance: int = 1,
    among: set[int] | None = None,
) -> list[LeaderboardEntry]:
    """取某货币的 TOP N。

    - 余额 < min_balance 的条目不入榜（默认剔除 0 和负数）
    - 按 balance 降序、qq_id 升序（稳定排序）
    - among: 若提供，只在这些 qq_id 中排名（用于群内榜）
    """
    if limit <= 0:
        return []
    async with get_session() as sess:
        conditions = [
            EconomyBalance.currency == currency,
            EconomyBalance.balance >= min_balance,
        ]
        if among is not None:
            conditions.append(EconomyBalance.qq_id.in_(among))
        stmt = (
            select(EconomyBalance.qq_id, EconomyBalance.balance)
            .where(*conditions)
            .order_by(EconomyBalance.balance.desc(), EconomyBalance.qq_id.asc())
            .limit(limit)
        )
        rows = (await sess.execute(stmt)).all()
        return [
            LeaderboardEntry(rank=i + 1, qq_id=int(r[0]), balance=int(r[1]))
            for i, r in enumerate(rows)
        ]


async def rank_of(
    qq_id: int,
    currency: str = "score",
    *,
    min_balance: int = 1,
    among: set[int] | None = None,
) -> tuple[int | None, int]:
    """查某人的排名。

    返回 (rank, balance)：
    - rank=None 表示未入榜（余额 < min_balance 或无记录）
    - rank 为 1-based
    并列时使用"标准竞赛排名"：并列者同名次，后面跳号（1, 2, 2, 4）。
    - among: 若提供，只在这些 qq_id 中排名（用于群内榜）
    """
    bal = await balance(qq_id, currency)
    if bal < min_balance:
        return None, bal
    if among is not None and qq_id not in among:
        return None, bal
    async with get_session() as sess:
        conditions = [
            EconomyBalance.currency == currency,
            EconomyBalance.balance > bal,
        ]
        if among is not None:
            conditions.append(EconomyBalance.qq_id.in_(among))
        stmt = select(func.count(EconomyBalance.id)).where(*conditions)
        ahead = (await sess.execute(stmt)).scalar_one()
        return int(ahead) + 1, bal


async def count_in_leaderboard(
    currency: str = "score",
    *,
    min_balance: int = 1,
    among: set[int] | None = None,
) -> int:
    """榜单总人数（余额 >= min_balance 的账户数）。"""
    async with get_session() as sess:
        conditions = [
            EconomyBalance.currency == currency,
            EconomyBalance.balance >= min_balance,
        ]
        if among is not None:
            conditions.append(EconomyBalance.qq_id.in_(among))
        stmt = select(func.count(EconomyBalance.id)).where(*conditions)
        return int((await sess.execute(stmt)).scalar_one())
