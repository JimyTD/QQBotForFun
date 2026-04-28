"""permission 模块测试。"""

from __future__ import annotations

import asyncio

import pytest

from core import permission
from core.errors import CooldownError, RateLimitedError


async def test_cooldown_basic() -> None:
    assert await permission.check_cooldown("k1") == 0
    await permission.set_cooldown("k1", 0.05)
    remain = await permission.check_cooldown("k1")
    assert remain > 0
    await asyncio.sleep(0.06)
    assert await permission.check_cooldown("k1") == 0


async def test_cooldown_decorator() -> None:
    call_count = 0

    @permission.cooldown(user=1, raise_on_block=True)
    async def do_it(*, qq_id: int) -> int:
        nonlocal call_count
        call_count += 1
        return call_count

    assert await do_it(qq_id=1001) == 1
    with pytest.raises(CooldownError):
        await do_it(qq_id=1001)
    # 不同用户不受影响
    assert await do_it(qq_id=1002) == 2


async def test_rate_limit_decorator() -> None:
    @permission.rate_limit(per_second=3, scope="user")
    async def f(*, qq_id: int) -> None:
        return None

    for _ in range(3):
        await f(qq_id=1001)
    with pytest.raises(RateLimitedError):
        await f(qq_id=1001)
