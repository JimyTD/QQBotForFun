"""海龟汤题库服务：抽题 / LLM 生成 / 兜底。"""

from __future__ import annotations

import random
from dataclasses import dataclass

from nonebot import logger
from sqlalchemy import func, select

from core import llm
from core.errors import LLMError, LLMJSONParseError
from core.storage import get_session

from .config import get_config
from .models import SoupPuzzle
from .prompts import (
    HOST_SYSTEM,
    HOST_USER,
)


@dataclass
class PuzzleData:
    id: int
    title: str
    category: str
    surface: str
    truth: str
    key_clues: list[str]
    difficulty: int
    source: str


async def obtain_puzzle() -> PuzzleData:
    """根据配置选择来源获取一道汤。
    1. prefer_llm_generation=True 则先尝试 LLM 生成，失败退题库；
    2. 否则 70% 题库 + 30% LLM。
    """
    cfg = get_config()
    if cfg.prefer_llm_generation:
        generated = await _try_generate_via_llm(cfg.llm_retry_times)
        if generated is not None:
            return generated
        logger.warning("[soup] LLM generation failed after retries, fallback to library")
        return await _pick_from_library()

    if random.random() < 0.3:
        generated = await _try_generate_via_llm(cfg.llm_retry_times)
        if generated is not None:
            return generated
    return await _pick_from_library()


async def _pick_from_library() -> PuzzleData:
    async with get_session() as sess:
        # 统计总数
        total = (await sess.execute(select(func.count(SoupPuzzle.id)))).scalar_one()
        if not total:
            raise RuntimeError(
                "题库为空，且 LLM 生成失败。请先运行 `python scripts/seed_turtle_soup.py`。"
            )
        # 按 play_count 反向加权抽取：play_count 少的更容易被选
        # 简化版：随机 id 跳读，多抽几次挑 play_count 较小的
        candidates: list[SoupPuzzle] = []
        for _ in range(5):
            offset = random.randint(0, total - 1)
            row = (
                await sess.execute(select(SoupPuzzle).offset(offset).limit(1))
            ).scalar_one_or_none()
            if row is not None:
                candidates.append(row)
        if not candidates:
            row = (await sess.execute(select(SoupPuzzle).limit(1))).scalar_one()
            candidates = [row]
        chosen = min(candidates, key=lambda r: r.play_count)

        # 回写 play_count
        chosen.play_count += 1
        await sess.flush()

        return PuzzleData(
            id=chosen.id,
            title=chosen.title,
            category=chosen.category,
            surface=chosen.surface,
            truth=chosen.truth,
            key_clues=list(chosen.key_clues or []),
            difficulty=chosen.difficulty,
            source=chosen.source,
        )


async def _try_generate_via_llm(retry_times: int) -> PuzzleData | None:
    for attempt in range(1, retry_times + 1):
        try:
            resp = await llm.chat(
                messages=[
                    llm.LLMMessage(role="system", content=HOST_SYSTEM),
                    llm.LLMMessage(role="user", content=HOST_USER),
                ],
                scene="turtle_soup_host",
                json_mode=True,
            )
            data = resp.json()
            title = str(data.get("title", "无题")).strip()
            category = str(data.get("category", "日常")).strip() or "日常"
            surface = str(data.get("surface", "")).strip()
            truth = str(data.get("truth", "")).strip()
            clues = data.get("key_clues", [])
            difficulty = int(data.get("difficulty", 3))
            if not surface or not truth or not isinstance(clues, list) or len(clues) == 0:
                raise ValueError("missing required fields in generated puzzle")

            # 入库
            async with get_session() as sess:
                row = SoupPuzzle(
                    title=title,
                    category=category,
                    surface=surface,
                    truth=truth,
                    key_clues=[str(c) for c in clues],
                    difficulty=difficulty,
                    source="llm_generated",
                    play_count=1,
                )
                sess.add(row)
                await sess.flush()
                return PuzzleData(
                    id=row.id,
                    title=row.title,
                    category=row.category,
                    surface=row.surface,
                    truth=row.truth,
                    key_clues=list(row.key_clues),
                    difficulty=row.difficulty,
                    source=row.source,
                )
        except (LLMError, LLMJSONParseError, ValueError) as e:
            logger.warning(f"[soup] LLM generate attempt {attempt} failed: {e}")
    return None


async def mark_win(puzzle_id: int) -> None:
    async with get_session() as sess:
        row = await sess.get(SoupPuzzle, puzzle_id)
        if row:
            row.win_count += 1
