"""快速验证智谱 glm-4-flash（judge 场景）可用。"""

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


async def main() -> None:
    llm.init()
    resp = await llm.chat(
        messages=[
            llm.LLMMessage(
                role="system",
                content='You are a JSON generator. Output {"ok": true}',
            ),
            llm.LLMMessage(role="user", content="Say ok."),
        ],
        scene="turtle_soup_judge",
        json_mode=True,
    )
    print(f"[test] content={resp.content}")
    print(f"[test] tokens={resp.usage} latency={resp.latency_ms}ms")
    print(f"[test] json parsed = {resp.json()}")


if __name__ == "__main__":
    asyncio.run(main())
