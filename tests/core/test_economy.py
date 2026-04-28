"""economy 模块测试。"""

from __future__ import annotations

import pytest

from core import economy
from core.errors import InsufficientFundsError


async def test_initial_balance_is_zero() -> None:
    assert await economy.balance(1001) == 0


async def test_add_and_balance() -> None:
    await economy.add(1001, 100, reason="test")
    assert await economy.balance(1001) == 100


async def test_deduct_ok() -> None:
    await economy.add(1001, 100, reason="init")
    await economy.deduct(1001, 30, reason="spend")
    assert await economy.balance(1001) == 70


async def test_deduct_insufficient_raises() -> None:
    await economy.add(1001, 50, reason="init")
    with pytest.raises(InsufficientFundsError):
        await economy.deduct(1001, 100, reason="overspend")
    # 余额未变
    assert await economy.balance(1001) == 50


async def test_transfer() -> None:
    await economy.add(1001, 100, reason="init")
    await economy.transfer(1001, 1002, 30, reason="gift")
    assert await economy.balance(1001) == 70
    assert await economy.balance(1002) == 30


async def test_items() -> None:
    await economy.add_item(1001, "hint", 3)
    assert await economy.has_item(1001, "hint", 2)
    await economy.remove_item(1001, "hint", 2)
    assert not await economy.has_item(1001, "hint", 2)
    assert await economy.has_item(1001, "hint", 1)
    inv = await economy.list_items(1001)
    assert inv == {"hint": 1}
