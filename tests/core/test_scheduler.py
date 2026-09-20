"""scheduler 测试。

重点锁一条线上事故：**整局超时回调不能被它自己的清理动作取消掉**。
"""

from __future__ import annotations

import asyncio

from core import scheduler


async def test_timeout_callback_survives_its_own_cancel_session_timers() -> None:
    """超时回调里调 `cancel_session_timers(sid)` 不能把回调自己 cancel 掉。

    真实事故（海龟汤 session EF8WHU：09-18 07:53 开局，09-19 07:53 超时）：
    超时回调最终会走到 `GameRunner.end()`，而 end() 的第一步清理就是
    `cancel_session_timers(session_id)` —— 登记表里恰好登记着**正在执行回调
    的这个 task 自己**，等于自己 cancel 自己。之后的第一个真挂起点（写 DB）
    就抛 CancelledError：

    - `game_session` 停在 `status='active'`，永远不落 ended；
    - `_runner_by_group` 没摘 → 该群被永久占死（开任何游戏都提示"本群已有
      进行中的 xxx"，`@我 提示` 却还能正常反应，因为 session 侧路由已先注销）；
    - CancelledError 被 `except asyncio.CancelledError: pass` 静默吞掉，
      日志里一行都没有，只能重启 bot 才能恢复。
    """
    sid = "TIMEOUTSELFCANCEL"
    reached = asyncio.Event()

    async def _on_timeout() -> None:
        # 模拟 end() 的清理动作：取消本 session 的所有计时器（含自己）
        await scheduler.cancel_session_timers(sid)
        # 真挂起点：被自己取消的话，这里就会抛 CancelledError 直接终止
        await asyncio.sleep(0)
        reached.set()

    await scheduler.start_turn_timer(sid, 0.01, _on_timeout)

    await asyncio.wait_for(reached.wait(), timeout=2.0)


async def test_external_cancel_still_stops_the_timer() -> None:
    """外部取消必须仍然有效 —— 修复的是"不取消自己"，不是"取消失效"。"""
    sid = "TIMEOUTEXTERNAL"
    fired = asyncio.Event()

    async def _on_timeout() -> None:
        fired.set()

    await scheduler.start_turn_timer(sid, 30, _on_timeout)
    await scheduler.cancel_session_timers(sid)
    await asyncio.sleep(0.05)

    assert not fired.is_set(), "被取消的计时器仍然触发了回调"
