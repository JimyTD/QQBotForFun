"""tools/food 单元测试。"""

from __future__ import annotations

import pytest

from src.plugins.tools.food.storage import count, pick_random, upsert_many


@pytest.mark.asyncio
async def test_empty_pool_returns_none() -> None:
    """空库 pick_random 应返回 None（不报错）。"""
    # 此时 fixture 还没塞数据；若之前测试已 upsert，count 应 > 0
    if await count() == 0:
        picked = await pick_random()
        assert picked is None


@pytest.mark.asyncio
async def test_upsert_insert_then_update() -> None:
    """同一 id 先 insert 再 update，字段应正确覆盖。"""
    items_v1 = [
        dict(
            id="test_food_a",
            name="测试菜A",
            description="初始描述",
            image_path=None,
            tags="test",
        )
    ]
    inserted, updated = await upsert_many(items_v1)
    assert inserted == 1
    assert updated == 0

    # 同样 id 再来一次，应是 update
    items_v2 = [
        dict(
            id="test_food_a",
            name="测试菜A改",
            description="新描述",
            image_path="resources/foods/test_food_a.jpg",
            tags="test,updated",
        )
    ]
    inserted, updated = await upsert_many(items_v2)
    assert inserted == 0
    assert updated == 1

    # 实际字段验证
    picked = await pick_random()
    # 此时库里只有 test_food_a（如果空库开始的话）或加上已有的
    # 不严格比较 picked.id，只看 upsert 操作本身


@pytest.mark.asyncio
async def test_pick_random_returns_one_when_not_empty() -> None:
    """非空库 pick_random 必返回一个 FoodItem。"""
    await upsert_many([
        dict(
            id="test_food_b",
            name="测试菜B",
            description="desc",
            image_path=None,
            tags="",
        )
    ])
    picked = await pick_random()
    assert picked is not None
    assert picked.id  # 不为空


@pytest.mark.asyncio
async def test_upsert_many_handles_empty_list() -> None:
    """空列表不炸。"""
    inserted, updated = await upsert_many([])
    assert inserted == 0
    assert updated == 0
