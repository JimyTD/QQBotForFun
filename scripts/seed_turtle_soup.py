"""Seed 海龟汤题库。

用法：
    python scripts/seed_turtle_soup.py

幂等：按 title 去重。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# 确保项目根和 src 都在 sys.path
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import select  # noqa: E402

from core.storage import get_session, init_db  # noqa: E402
from src.plugins.games.turtle_soup.models import SoupPuzzle  # noqa: E402


async def main(path: Path) -> None:
    await init_db()

    with open(path, encoding="utf-8") as f:
        items = json.load(f)

    added = 0
    skipped = 0
    async with get_session() as sess:
        for item in items:
            title = str(item["title"])
            existing = (
                await sess.execute(select(SoupPuzzle).where(SoupPuzzle.title == title))
            ).scalar_one_or_none()
            if existing is not None:
                skipped += 1
                continue
            sess.add(
                SoupPuzzle(
                    title=title,
                    category=item.get("category", "日常"),
                    surface=item["surface"],
                    truth=item["truth"],
                    key_clues=list(item.get("key_clues", [])),
                    difficulty=int(item.get("difficulty", 3)),
                    source="builtin",
                )
            )
            added += 1

    print(f"[seed] done. added={added} skipped={skipped} (total in file: {len(items)})")


if __name__ == "__main__":
    seed_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("seeds/turtle_soup.json")
    if not seed_path.exists():
        print(f"seed file not found: {seed_path}", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(seed_path))
