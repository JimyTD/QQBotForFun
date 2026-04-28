"""Core · user

用户信息：昵称、头像、群成员列表。包含轻量内存缓存。
"""

from __future__ import annotations

import asyncio
import time

from nonebot import get_bot, logger
from sqlalchemy import select

from core._models_common import UserRecord
from core.errors import GameError
from core.storage import get_session
from core.types import GroupInfo, User

# ---------- 缓存 ----------
_NICK_TTL = 60.0
_MEMBERS_TTL = 300.0

_nick_cache: dict[tuple[int, int | None], tuple[float, str]] = {}
_group_info_cache: dict[int, tuple[float, GroupInfo]] = {}
_members_cache: dict[int, tuple[float, list[User]]] = {}
_lock = asyncio.Lock()


def _now() -> float:
    return time.monotonic()


async def get(qq_id: int, group_id: int | None = None) -> User:
    """获取单个用户信息。group_id 提供时会返回群昵称。"""
    key = (qq_id, group_id)
    cached = _nick_cache.get(key)
    if cached and _now() - cached[0] < _NICK_TTL:
        return User(qq_id=qq_id, nickname=cached[1], group_id=group_id)

    nickname = await _fetch_nickname(qq_id, group_id)
    _nick_cache[key] = (_now(), nickname)

    # 顺手更新 DB（异步、失败不影响主流程）
    asyncio.create_task(_upsert_user(qq_id, nickname))

    return User(qq_id=qq_id, nickname=nickname, group_id=group_id)


async def get_many(qq_ids: list[int], group_id: int | None = None) -> list[User]:
    return [await get(q, group_id) for q in qq_ids]


async def get_group_info(group_id: int) -> GroupInfo:
    cached = _group_info_cache.get(group_id)
    if cached and _now() - cached[0] < _MEMBERS_TTL:
        return cached[1]

    try:
        bot = get_bot()
        info: dict = await bot.call_api("get_group_info", group_id=group_id)  # type: ignore[attr-defined]
        gi = GroupInfo(
            group_id=group_id,
            name=info.get("group_name", str(group_id)),
            member_count=int(info.get("member_count", 0)),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"get_group_info failed for {group_id}: {e}")
        gi = GroupInfo(group_id=group_id, name=str(group_id), member_count=0)
    _group_info_cache[group_id] = (_now(), gi)
    return gi


async def get_group_members(group_id: int, *, force_refresh: bool = False) -> list[User]:
    if not force_refresh:
        cached = _members_cache.get(group_id)
        if cached and _now() - cached[0] < _MEMBERS_TTL:
            return cached[1]

    try:
        bot = get_bot()
        data: list[dict] = await bot.call_api(  # type: ignore[attr-defined]
            "get_group_member_list", group_id=group_id
        )
        users = [
            User(
                qq_id=int(m["user_id"]),
                nickname=(m.get("card") or m.get("nickname") or str(m["user_id"])),
                group_id=group_id,
            )
            for m in data
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"get_group_members failed for {group_id}: {e}")
        users = []
    _members_cache[group_id] = (_now(), users)
    return users


async def invalidate(qq_id: int | None = None, group_id: int | None = None) -> None:
    """手动失效缓存。"""
    async with _lock:
        if qq_id is None and group_id is None:
            _nick_cache.clear()
            _group_info_cache.clear()
            _members_cache.clear()
            return
        if group_id is not None:
            _group_info_cache.pop(group_id, None)
            _members_cache.pop(group_id, None)
        to_del = [
            k for k in _nick_cache
            if (qq_id is not None and k[0] == qq_id) or (group_id is not None and k[1] == group_id)
        ]
        for k in to_del:
            _nick_cache.pop(k, None)


# ---------- 内部 ----------
async def _fetch_nickname(qq_id: int, group_id: int | None) -> str:
    try:
        bot = get_bot()
        if group_id is not None:
            info: dict = await bot.call_api(  # type: ignore[attr-defined]
                "get_group_member_info",
                group_id=group_id,
                user_id=qq_id,
                no_cache=False,
            )
            return info.get("card") or info.get("nickname") or str(qq_id)
        info = await bot.call_api("get_stranger_info", user_id=qq_id)  # type: ignore[attr-defined]
        return info.get("nickname", str(qq_id))
    except GameError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.debug(f"fetch_nickname fallback for {qq_id}: {e}")
        return str(qq_id)


async def _upsert_user(qq_id: int, nickname: str) -> None:
    try:
        async with get_session() as sess:
            existing = await sess.get(UserRecord, qq_id)
            if existing is None:
                sess.add(UserRecord(qq_id=qq_id, nickname=nickname))
            elif existing.nickname != nickname:
                existing.nickname = nickname
    except Exception as e:  # noqa: BLE001
        logger.debug(f"_upsert_user failed: {e}")


# keep for future
_ = select
