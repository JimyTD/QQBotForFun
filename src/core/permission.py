"""Core · permission

冷却 / 频率限制 / 角色权限。

开发环境使用内存；生产可切 Redis。
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from functools import wraps
from typing import Any

from nonebot import logger
from sqlalchemy import delete, select

from core._models_common import AdminRole, CooldownRecord
from core.errors import CooldownError, PermissionDeniedError, RateLimitedError
from core.storage import get_session
from src.settings import get_settings


# =====================================================================
# 冷却
# =====================================================================
_cooldowns: dict[str, float] = {}  # scope_key -> expires_at (monotonic timestamp)
_cooldown_lock = asyncio.Lock()


async def check_cooldown(scope_key: str) -> float:
    """返回剩余秒数；0 表示无冷却。"""
    now = time.monotonic()
    async with _cooldown_lock:
        exp = _cooldowns.get(scope_key, 0)
        if exp <= now:
            _cooldowns.pop(scope_key, None)
            return 0.0
        return exp - now


async def set_cooldown(scope_key: str, seconds: float) -> None:
    if seconds <= 0:
        return
    async with _cooldown_lock:
        _cooldowns[scope_key] = time.monotonic() + seconds


# =====================================================================
# 频率限制
# =====================================================================
_rate_windows: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = asyncio.Lock()


async def check_rate_limit(scope_key: str, limit: int, window_seconds: float) -> bool:
    """True=放行；False=被限流。会原子地记录本次请求。"""
    now = time.monotonic()
    async with _rate_lock:
        dq = _rate_windows[scope_key]
        while dq and dq[0] < now - window_seconds:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True


# =====================================================================
# 角色权限
# =====================================================================
async def is_admin(qq_id: int) -> bool:
    settings = get_settings()
    if qq_id in settings.admin_qq_list:
        return True
    async with get_session() as sess:
        row = await sess.get(AdminRole, qq_id)
        return row is not None


async def is_owner(qq_id: int) -> bool:
    settings = get_settings()
    return bool(settings.admin_qq_list) and qq_id == settings.admin_qq_list[0]


async def grant_admin(qq_id: int, granted_by: int, role: str = "admin") -> None:
    async with get_session() as sess:
        existing = await sess.get(AdminRole, qq_id)
        if existing is None:
            sess.add(AdminRole(qq_id=qq_id, role=role, granted_by=granted_by))
        else:
            existing.role = role


async def revoke_admin(qq_id: int) -> None:
    async with get_session() as sess:
        existing = await sess.get(AdminRole, qq_id)
        if existing is not None:
            await sess.delete(existing)


# =====================================================================
# 装饰器
# =====================================================================
F = Callable[..., Awaitable[Any]]


def cooldown(
    user: float = 0,
    group: float = 0,
    *,
    key: str | None = None,
    raise_on_block: bool = True,
) -> Callable[[F], F]:
    """函数级冷却装饰器。

    Args:
        user: 用户级冷却秒数
        group: 群级冷却秒数
        key: 指定冷却 key 前缀，默认用函数名
        raise_on_block: 命中时抛 CooldownError；False 则静默返回 None
    """
    def deco(fn: F) -> F:
        prefix = key or fn.__name__

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            qq_id = kwargs.get("qq_id") or kwargs.get("user_id")
            group_id = kwargs.get("group_id")
            if user > 0 and qq_id is not None:
                remain = await check_cooldown(f"{prefix}:user:{qq_id}")
                if remain > 0:
                    if raise_on_block:
                        raise CooldownError(remain)
                    return None
            if group > 0 and group_id is not None:
                remain = await check_cooldown(f"{prefix}:group:{group_id}")
                if remain > 0:
                    if raise_on_block:
                        raise CooldownError(remain)
                    return None
            result = await fn(*args, **kwargs)
            if user > 0 and qq_id is not None:
                await set_cooldown(f"{prefix}:user:{qq_id}", user)
            if group > 0 and group_id is not None:
                await set_cooldown(f"{prefix}:group:{group_id}", group)
            return result

        return wrapper  # type: ignore[return-value]

    return deco


def rate_limit(
    per_minute: int | None = None,
    per_second: int | None = None,
    scope: str = "user",
    key: str | None = None,
) -> Callable[[F], F]:
    """频率限制装饰器。

    scope: 'user' / 'group' / 'global'
    """
    if per_minute is None and per_second is None:
        raise ValueError("must specify per_minute or per_second")
    limit = per_minute if per_minute is not None else per_second
    window = 60.0 if per_minute is not None else 1.0
    assert limit is not None

    def deco(fn: F) -> F:
        prefix = key or fn.__name__

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if scope == "global":
                sk = f"rate:{prefix}:global"
            elif scope == "group":
                gid = kwargs.get("group_id")
                sk = f"rate:{prefix}:group:{gid}"
            else:
                qid = kwargs.get("qq_id") or kwargs.get("user_id")
                sk = f"rate:{prefix}:user:{qid}"
            ok = await check_rate_limit(sk, limit, window)
            if not ok:
                raise RateLimitedError(f"rate limited: {sk}")
            return await fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return deco


def require_role(role: str = "admin") -> Callable[[F], F]:
    """要求调用者具备指定角色。

    调用时必须传入 `qq_id=` 关键字参数。
    """

    def deco(fn: F) -> F:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            qq_id = kwargs.get("qq_id") or kwargs.get("user_id")
            if qq_id is None:
                raise PermissionDeniedError("qq_id not provided for role check")
            if role == "owner":
                if not await is_owner(qq_id):
                    raise PermissionDeniedError(f"requires owner, qq={qq_id}")
            else:
                if not await is_admin(qq_id):
                    raise PermissionDeniedError(f"requires {role}, qq={qq_id}")
            return await fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return deco


# =====================================================================
# 持久化冷却（跨重启）：可选，游戏主动写入时用
# =====================================================================
async def set_persistent_cooldown(scope_key: str, seconds: float) -> None:
    expires_at = datetime.utcnow() + timedelta(seconds=seconds)
    async with get_session() as sess:
        row = (
            await sess.execute(select(CooldownRecord).where(CooldownRecord.scope_key == scope_key))
        ).scalar_one_or_none()
        if row is None:
            sess.add(CooldownRecord(scope_key=scope_key, expires_at=expires_at))
        else:
            row.expires_at = expires_at


async def check_persistent_cooldown(scope_key: str) -> float:
    async with get_session() as sess:
        row = (
            await sess.execute(select(CooldownRecord).where(CooldownRecord.scope_key == scope_key))
        ).scalar_one_or_none()
        if row is None:
            return 0.0
        remain = (row.expires_at - datetime.utcnow()).total_seconds()
        if remain <= 0:
            await sess.execute(delete(CooldownRecord).where(CooldownRecord.scope_key == scope_key))
            return 0.0
        return remain


_ = logger  # reserved
