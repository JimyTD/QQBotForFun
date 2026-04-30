"""把 seeds/foods.json 导入 food_items 表。

用法：
    uv run python scripts/seed_foods.py

行为：
  - 已存在的 id 做字段更新
  - 不存在的 id 新增
  - 不在 seed 里的老记录保留不动（所以不会误删）
  - 如果 resources/foods/<id>.jpg 不存在，image_path 存空字符串
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

SEED_FILE = _ROOT / "seeds" / "foods.json"
FOOD_IMG_DIR = _ROOT / "resources" / "foods"


async def main() -> int:
    from core.storage import init_db
    # 导入模型让它注册到 metadata
    from src.plugins.tools.food.storage import count, upsert_many  # noqa: E402

    if not SEED_FILE.exists():
        print(f"seed file not found: {SEED_FILE}", file=sys.stderr)
        return 1

    await init_db()

    raw = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        print("foods.json must be a list", file=sys.stderr)
        return 1

    items: list[dict] = []
    missing_images: list[str] = []
    for entry in raw:
        fid = entry["id"]
        img_rel = f"resources/foods/{fid}.jpg"
        img_abs = _ROOT / img_rel
        if img_abs.exists():
            image_path = img_rel
        else:
            image_path = None
            missing_images.append(fid)

        items.append(
            dict(
                id=fid,
                name=entry["name"],
                description=entry["description"],
                image_path=image_path,
                tags=entry.get("tags", ""),
            )
        )

    inserted, updated = await upsert_many(items)
    total = await count()

    print(f"seed done: +{inserted} inserted, ~{updated} updated, total={total}")
    if missing_images:
        print(f"  ⚠ {len(missing_images)} items without image: {missing_images[:5]}...")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
