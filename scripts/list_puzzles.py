"""查看题库所有题目。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import select  # noqa: E402

from core.storage import get_session, init_db  # noqa: E402
from src.plugins.games.turtle_soup.models import SoupPuzzle  # noqa: E402


async def main() -> None:
    await init_db()
    async with get_session() as sess:
        rows = (await sess.execute(select(SoupPuzzle).order_by(SoupPuzzle.id))).scalars().all()
        print(f"[puzzles] total: {len(rows)}\n")
        for r in rows:
            stars = "*" * r.difficulty + "-" * (5 - r.difficulty)
            print(f"#{r.id}  {r.title}")
            print(f"  category={r.category}  difficulty={stars}  source={r.source}")
            print(f"  play={r.play_count}  win={r.win_count}")
            print(f"  [surface] {r.surface}")
            print(f"  [truth]   {r.truth[:80]}...")
            print(f"  [clues]   {r.key_clues}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
