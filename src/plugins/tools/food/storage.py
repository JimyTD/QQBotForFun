"""food_items 表的 CRUD 封装。"""

from __future__ import annotations

from sqlalchemy import func, select

from core.storage import get_session
from src.plugins.tools.food.models import FoodItem


async def pick_random() -> FoodItem | None:
    """随机抽一道菜。库为空返回 None。"""
    async with get_session() as s:
        # SQLite / PostgreSQL 都支持 func.random()
        stmt = select(FoodItem).order_by(func.random()).limit(1)
        result = await s.execute(stmt)
        return result.scalar_one_or_none()


async def count() -> int:
    """菜品总数。"""
    async with get_session() as s:
        stmt = select(func.count()).select_from(FoodItem)
        result = await s.execute(stmt)
        return int(result.scalar_one() or 0)


async def upsert_many(items: list[dict]) -> tuple[int, int]:
    """批量 upsert。返回 (inserted, updated)。

    Args:
        items: 每条是 {id, name, description, image_path, tags}
    """
    inserted = 0
    updated = 0
    async with get_session() as s:
        for data in items:
            existing = await s.get(FoodItem, data["id"])
            if existing is None:
                s.add(FoodItem(**data))
                inserted += 1
            else:
                # 覆盖式更新（name / description / image_path / tags）
                for k in ("name", "description", "image_path", "tags"):
                    if k in data:
                        setattr(existing, k, data[k])
                updated += 1
        await s.commit()
    return inserted, updated
