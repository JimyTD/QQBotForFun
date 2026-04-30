"""海龟汤烂题淘汰 & cap 机制单元测试。"""

from __future__ import annotations

import time

from src.plugins.games.turtle_soup import puzzle_service as ps
from src.plugins.games.turtle_soup.models import SoupPuzzle


# ------------------------------------------------------------------
# 最近一局记忆
# ------------------------------------------------------------------
def test_record_and_get_last_puzzle() -> None:
    ps.clear_last_puzzle(9999)
    assert ps.get_last_puzzle(9999) is None
    ps.record_last_puzzle(9999, 42)
    rec = ps.get_last_puzzle(9999)
    assert rec is not None
    pid, ts = rec
    assert pid == 42
    assert time.time() - ts < 1.0


def test_clear_last_puzzle() -> None:
    ps.record_last_puzzle(9998, 1)
    ps.clear_last_puzzle(9998)
    assert ps.get_last_puzzle(9998) is None


# ------------------------------------------------------------------
# mark_bad_by_group：窗口过期拒绝
# ------------------------------------------------------------------
async def test_mark_bad_no_record() -> None:
    ps.clear_last_puzzle(5000)
    ok, msg = await ps.mark_bad_by_group(5000)
    assert ok is False
    assert "没有可评价" in msg or "无上一局" in msg


async def test_mark_bad_window_expired() -> None:
    # 伪造一条超过窗口的记录
    ps._last_puzzle_by_group[5001] = (1, time.time() - 999999)
    ok, msg = await ps.mark_bad_by_group(5001)
    assert ok is False
    assert "窗口" in msg or "已过" in msg


# ------------------------------------------------------------------
# cap 强制淘汰
# ------------------------------------------------------------------
async def test_enforce_cap_noop_when_under_limit() -> None:
    """未到上限时不应删任何东西。"""
    from sqlalchemy import select, func
    from core.storage import init_db, get_session

    await init_db()
    async with get_session() as sess:
        before = (
            await sess.execute(
                select(func.count(SoupPuzzle.id)).where(
                    SoupPuzzle.source == "llm_generated"
                )
            )
        ).scalar_one()

    # cap 设得极大，触发不了
    await ps._enforce_llm_generated_cap(1_000_000)

    async with get_session() as sess:
        after = (
            await sess.execute(
                select(func.count(SoupPuzzle.id)).where(
                    SoupPuzzle.source == "llm_generated"
                )
            )
        ).scalar_one()

    assert before == after


# ------------------------------------------------------------------
# mark_bad builtin 特权：不允许淘汰
# ------------------------------------------------------------------
async def test_mark_bad_rejects_builtin() -> None:
    from core.storage import get_session, init_db

    await init_db()
    # 预先塞一条 builtin 题目作为测试对象
    async with get_session() as sess:
        builtin_row = SoupPuzzle(
            title="测试-builtin特权题",
            category="日常",
            surface="这是一个测试汤面",
            truth="这是一个测试汤底",
            key_clues=["线索1", "线索2"],
            difficulty=3,
            source="builtin",
        )
        sess.add(builtin_row)
        await sess.flush()
        builtin_id = builtin_row.id

    ps.record_last_puzzle(5002, builtin_id)
    ok, msg = await ps.mark_bad_by_group(5002)
    assert ok is False
    assert "种子" in msg or "builtin" in msg.lower() or "精品" in msg

    # 清理：验证 builtin 确实还在（没被删）
    async with get_session() as sess:
        still_exists = await sess.get(SoupPuzzle, builtin_id)
        assert still_exists is not None, "builtin 题不应被淘汰"
