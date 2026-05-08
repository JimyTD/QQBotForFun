"""Core · scheduler

对 apscheduler 的薄封装 + 会话级回合计时器。

- schedule_once(delay, callback)
- schedule_cron(cron, callback)
- cancel(job_id | tag)
- start_turn_timer(session_id, seconds, on_timeout)
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from nonebot import logger

try:  # pragma: no cover - optional at import time
    from nonebot_plugin_apscheduler import scheduler
except Exception:  # noqa: BLE001
    scheduler = None  # type: ignore[assignment]


_tag_index: dict[str, set[str]] = {}  # tag -> job_ids
_turn_timers: dict[str, set[asyncio.Task[Any]]] = {}  # session_id -> tasks


def _ensure_scheduler() -> Any:
    if scheduler is None:
        raise RuntimeError("apscheduler is not available; nonebot_plugin_apscheduler not loaded")
    return scheduler


async def schedule_once(
    delay: float,
    callback: Callable[..., Awaitable[Any]],
    *,
    tag: str | None = None,
    **kwargs: Any,
) -> str:
    sched = _ensure_scheduler()
    job_id = f"once_{uuid.uuid4().hex[:10]}"

    async def _wrap() -> None:
        try:
            await callback(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[scheduler] once job error ({job_id}): {e}")

    from datetime import datetime, timedelta

    run_time = datetime.now() + timedelta(seconds=delay)
    sched.add_job(
        _wrap,
        "date",
        id=job_id,
        run_date=run_time,
        misfire_grace_time=300,  # 5 分钟容忍窗口
    )

    if tag:
        _tag_index.setdefault(tag, set()).add(job_id)
    return job_id


async def schedule_cron(
    cron: str,
    callback: Callable[..., Awaitable[Any]],
    *,
    tag: str | None = None,
    **kwargs: Any,
) -> str:
    sched = _ensure_scheduler()
    job_id = f"cron_{uuid.uuid4().hex[:10]}"
    parts = cron.split()
    if len(parts) != 5:
        raise ValueError(f"cron must be 5 fields, got: {cron!r}")
    minute, hour, day, month, day_of_week = parts

    async def _wrap() -> None:
        try:
            await callback(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[scheduler] cron job error ({job_id}): {e}")

    sched.add_job(
        _wrap,
        "cron",
        id=job_id,
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        misfire_grace_time=300,  # 5 分钟容忍窗口
    )
    if tag:
        _tag_index.setdefault(tag, set()).add(job_id)
    return job_id


async def cancel(job_id_or_tag: str) -> int:
    sched = _ensure_scheduler()
    count = 0
    # 按 tag 取消
    if job_id_or_tag in _tag_index:
        for jid in list(_tag_index[job_id_or_tag]):
            try:
                sched.remove_job(jid)
                count += 1
            except Exception:  # noqa: BLE001
                pass
        _tag_index.pop(job_id_or_tag, None)
        return count
    # 按 job_id 取消
    try:
        sched.remove_job(job_id_or_tag)
        return 1
    except Exception:  # noqa: BLE001
        return 0


async def start_turn_timer(
    session_id: str,
    seconds: float,
    on_timeout: Callable[[], Awaitable[Any]],
) -> None:
    """会话级回合计时器。session 结束时自动清理。"""

    async def _run() -> None:
        try:
            await asyncio.sleep(seconds)
            await on_timeout()
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[scheduler] turn_timer error session={session_id}: {e}")

    task = asyncio.create_task(_run())
    _turn_timers.setdefault(session_id, set()).add(task)

    def _on_done(t: asyncio.Task[Any]) -> None:
        _turn_timers.get(session_id, set()).discard(t)

    task.add_done_callback(_on_done)


async def cancel_session_timers(session_id: str) -> None:
    tasks = _turn_timers.pop(session_id, set())
    for t in tasks:
        t.cancel()
