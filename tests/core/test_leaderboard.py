"""economy 榜单相关 helper 的测试：top_balances / rank_of / count_in_leaderboard。"""

from __future__ import annotations

import pytest

from core import economy


async def _seed(pairs: list[tuple[int, int]], *, currency: str = "score") -> None:
    """批量写入 (qq_id, balance)。"""
    for qq_id, bal in pairs:
        if bal > 0:
            await economy.add(qq_id, bal, reason="seed", currency=currency)


async def test_top_balances_empty() -> None:
    assert await economy.top_balances("score", limit=10) == []


async def test_top_balances_basic_order() -> None:
    await _seed(
        [
            (1001, 50),
            (1002, 120),
            (1003, 30),
            (1004, 200),
            (1005, 90),
        ]
    )
    top = await economy.top_balances("score", limit=3)
    assert [e.qq_id for e in top] == [1004, 1002, 1005]
    assert [e.rank for e in top] == [1, 2, 3]
    assert [e.balance for e in top] == [200, 120, 90]


async def test_top_balances_currency_isolation() -> None:
    await _seed([(1, 100), (2, 200)], currency="score")
    await _seed([(1, 500), (2, 10)], currency="coin")

    top_score = await economy.top_balances("score", limit=10)
    assert [(e.qq_id, e.balance) for e in top_score] == [(2, 200), (1, 100)]

    top_coin = await economy.top_balances("coin", limit=10)
    assert [(e.qq_id, e.balance) for e in top_coin] == [(1, 500), (2, 10)]


async def test_top_balances_excludes_zero() -> None:
    await economy.add(1, 10, reason="+10", currency="score")
    await economy.add(2, 10, reason="+10", currency="score")
    await economy.deduct(2, 10, reason="-10", currency="score")  # 归零

    top = await economy.top_balances("score", limit=10)
    assert [e.qq_id for e in top] == [1]


async def test_top_balances_tie_breaker_qq_asc() -> None:
    # 并列时应按 qq_id 升序（稳定展示）
    await _seed([(2002, 100), (1001, 100), (3003, 100)])
    top = await economy.top_balances("score", limit=10)
    assert [e.qq_id for e in top] == [1001, 2002, 3003]


async def test_top_balances_limit_zero_returns_empty() -> None:
    await _seed([(1, 10)])
    assert await economy.top_balances("score", limit=0) == []


async def test_rank_of_not_on_board() -> None:
    await _seed([(1, 10)])
    rank, bal = await economy.rank_of(9999, "score")
    assert rank is None
    assert bal == 0


async def test_rank_of_standard_competition_ranking() -> None:
    # 标准竞赛排名：100, 100, 50 → 排名 1, 1, 3
    await _seed([(1001, 100), (1002, 100), (1003, 50)])

    r1, b1 = await economy.rank_of(1001, "score")
    r2, b2 = await economy.rank_of(1002, "score")
    r3, b3 = await economy.rank_of(1003, "score")

    assert (r1, b1) == (1, 100)
    assert (r2, b2) == (1, 100)
    assert (r3, b3) == (3, 50)


async def test_count_in_leaderboard() -> None:
    await _seed([(1, 10), (2, 20), (3, 0)])
    # qq=3 因 balance=0 不入榜
    assert await economy.count_in_leaderboard("score") == 2
    assert await economy.count_in_leaderboard("coin") == 0


async def test_score_is_registered_by_default() -> None:
    assert economy.is_registered("score")
    assert economy.is_registered("coin")
    assert economy.is_registered("ticket")


# ---------- among (群内榜) ----------

async def test_top_balances_among_filters_to_subset() -> None:
    await _seed([(1001, 200), (1002, 150), (1003, 100), (1004, 50)])
    group_members = {1001, 1003, 1004}

    top = await economy.top_balances("score", limit=10, among=group_members)
    assert [e.qq_id for e in top] == [1001, 1003, 1004]
    assert [e.rank for e in top] == [1, 2, 3]
    # 1002 不在群内，被排除


async def test_top_balances_among_empty_set() -> None:
    await _seed([(1, 100)])
    top = await economy.top_balances("score", limit=10, among=set())
    assert top == []


async def test_top_balances_among_none_is_global() -> None:
    await _seed([(1001, 100), (1002, 200)])
    top_global = await economy.top_balances("score", limit=10, among=None)
    assert len(top_global) == 2


async def test_rank_of_among_filters() -> None:
    await _seed([(1001, 200), (1002, 150), (1003, 100)])
    group_members = {1001, 1003}

    rank, bal = await economy.rank_of(1003, "score", among=group_members)
    assert rank == 2
    assert bal == 100

    rank, bal = await economy.rank_of(1002, "score", among=group_members)
    assert rank is None


async def test_count_in_leaderboard_among() -> None:
    await _seed([(1, 100), (2, 200), (3, 50)])
    assert await economy.count_in_leaderboard("score", among={1, 3}) == 2
    assert await economy.count_in_leaderboard("score", among={9999}) == 0
