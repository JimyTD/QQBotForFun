"""使用 LLM 批量生成海龟汤题目并入库。

用法：
    python scripts/generate_soup_with_llm.py [count]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from core import llm  # noqa: E402
from core.storage import get_session, init_db  # noqa: E402
from src.plugins.games.turtle_soup.models import SoupPuzzle  # noqa: E402
from src.plugins.games.turtle_soup.prompts import HOST_SYSTEM, HOST_USER  # noqa: E402


async def generate_one() -> dict | None:
    try:
        resp = await llm.chat(
            messages=[
                llm.LLMMessage(role="system", content=HOST_SYSTEM),
                llm.LLMMessage(role="user", content=HOST_USER),
            ],
            scene="turtle_soup_host",
            json_mode=True,
        )
        return resp.json()
    except Exception as e:  # noqa: BLE001
        print(f"[gen] failed: {e}")
        return None


async def main(count: int) -> None:
    llm.init()
    await init_db()
    added = 0
    for i in range(count):
        print(f"[gen] ({i + 1}/{count}) generating...")
        data = await generate_one()
        if data is None:
            continue
        try:
            async with get_session() as sess:
                sess.add(
                    SoupPuzzle(
                        title=str(data.get("title", f"未命名-{i + 1}")),
                        category=str(data.get("category", "日常")),
                        surface=str(data["surface"]),
                        truth=str(data["truth"]),
                        key_clues=[str(c) for c in data.get("key_clues", [])],
                        difficulty=int(data.get("difficulty", 3)),
                        source="llm_generated",
                    )
                )
            added += 1
            print(f"[gen]   OK: {data.get('title')}")
        except Exception as e:  # noqa: BLE001
            print(f"[gen]   FAIL insert: {e!r}")
    print(f"[gen] done. added={added}/{count}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    asyncio.run(main(n))
