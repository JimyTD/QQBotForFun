"""海龟汤题库服务：抽题 / LLM 生成 / 兜底 / 淘汰。"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from nonebot import logger
from sqlalchemy import func, select

from core import llm
from core.errors import LLMError, LLMJSONParseError
from core.storage import get_session

from .config import get_config
from .models import SoupPuzzle
from .prompts import (
    CATEGORIES,
    HOST_USER,
    build_host_system_prompt,
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


# ------------------------------------------------------------------
# "最近一局"记忆：group_id -> (puzzle_id, end_unix_ts)
# 用于支持 /汤 烂题 在对局结束后的短窗口内删除刚玩的那题
# CLI 统一使用 group_id=0
# ------------------------------------------------------------------
_last_puzzle_by_group: dict[int, tuple[int, float]] = {}


def record_last_puzzle(group_id: int, puzzle_id: int) -> None:
    """游戏结束时（on_end）调用，记录最近一局刚玩的题。"""
    _last_puzzle_by_group[group_id] = (puzzle_id, time.time())


def get_last_puzzle(group_id: int) -> tuple[int, float] | None:
    """查询该 group 最近一局的 (puzzle_id, end_ts)；无记录返回 None。"""
    return _last_puzzle_by_group.get(group_id)


def clear_last_puzzle(group_id: int) -> None:
    """烂题删完后清掉记忆，避免重复操作。"""
    _last_puzzle_by_group.pop(group_id, None)


async def mark_bad_by_group(group_id: int) -> tuple[bool, str]:
    """玩家触发 /汤 烂题 时调用。

    返回 (是否成功, 用户可见的提示文本)。
    规则：
    - 必须有最近一局记录
    - 距本局结束 <= mark_bad_window_seconds
    - builtin 题不允许淘汰（有特权）
    - 成功则硬删该 puzzle 行
    """
    cfg = get_config()
    record = get_last_puzzle(group_id)
    if record is None:
        return False, "当前没有可评价的题（上一局结束时间过久或无上一局）"

    puzzle_id, end_ts = record
    elapsed = time.time() - end_ts
    if elapsed > cfg.mark_bad_window_seconds:
        clear_last_puzzle(group_id)
        return False, (
            f"距上局结束已过 {int(elapsed)}s，超过 {cfg.mark_bad_window_seconds}s 窗口"
        )

    async with get_session() as sess:
        row = await sess.get(SoupPuzzle, puzzle_id)
        if row is None:
            clear_last_puzzle(group_id)
            return False, "上一局的题已不存在（可能已被他人删除）"
        if row.source == "builtin":
            return False, f"《{row.title}》是种子精品题，不允许淘汰"
        title = row.title
        await sess.delete(row)

    clear_last_puzzle(group_id)
    logger.info(f"[soup] puzzle #{puzzle_id} 《{title}》 marked as bad, deleted")
    return True, f"已淘汰《{title}》（id={puzzle_id}）"


async def _enforce_llm_generated_cap(cap: int) -> None:
    """入库前确保 llm_generated 总数严格小于 cap，超限则 FIFO 删最老的。

    builtin 永不删。
    """
    async with get_session() as sess:
        current = (
            await sess.execute(
                select(func.count(SoupPuzzle.id)).where(
                    SoupPuzzle.source == "llm_generated"
                )
            )
        ).scalar_one()
        if current < cap:
            return

        # 需要删 (current - cap + 1) 条最老的 llm_generated
        to_delete = current - cap + 1
        old_rows = (
            await sess.execute(
                select(SoupPuzzle)
                .where(SoupPuzzle.source == "llm_generated")
                .order_by(SoupPuzzle.created_at.asc())
                .limit(to_delete)
            )
        ).scalars().all()
        for r in old_rows:
            logger.info(
                f"[soup] cap={cap} reached, evicting oldest llm_generated "
                f"#{r.id} 《{r.title}》 (play_count={r.play_count})"
            )
            await sess.delete(r)





async def obtain_puzzle(mode: str | None = None) -> PuzzleData:
    """根据 mode / 配置获取一道汤。

    mode 取值：
    - "library"  强制走题库（不调 LLM）
    - "llm"      强制调 LLM 生成（失败才退题库）
    - None / 其他  遵循配置（prefer_llm_generation + 30% LLM 概率）
    """
    cfg = get_config()

    if mode == "library":
        return await _pick_from_library()

    if mode == "llm":
        generated = await _try_generate_via_llm(cfg.llm_retry_times)
        if generated is not None:
            return generated
        logger.warning("[soup] LLM generation failed, fallback to library")
        return await _pick_from_library()

    # 遵循配置
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
    # v2.0：每次生成前随机指定 category 和 difficulty，消除 LLM 的"日常锚定"倾向
    target_category = random.choice(CATEGORIES)
    target_difficulty = random.randint(1, 5)
    system_prompt = build_host_system_prompt(target_category, target_difficulty)
    logger.info(
        f"[soup] generating puzzle category={target_category} difficulty={target_difficulty}"
    )

    for attempt in range(1, retry_times + 1):
        try:
            resp = await llm.chat(
                messages=[
                    llm.LLMMessage(role="system", content=system_prompt),
                    llm.LLMMessage(role="user", content=HOST_USER),
                ],
                scene="turtle_soup_host",
                json_mode=True,
            )
            data = resp.json()
            title = str(data.get("title", "无题")).strip()
            # 容错：清洗 LLM 偶尔带进来的"标题："前缀
            for prefix in ("标题：", "标题:", "题目：", "题目:"):
                if title.startswith(prefix):
                    title = title[len(prefix):].strip()
            if not title:
                title = "无题"
            # 容错：LLM 偶尔会改写 category，兜底仍使用代码层指定的 target_category
            category = str(data.get("category", target_category)).strip() or target_category
            if category not in CATEGORIES:
                logger.warning(
                    f"[soup] LLM returned unknown category={category!r}, "
                    f"falling back to target={target_category}"
                )
                category = target_category
            surface = str(data.get("surface", "")).strip()
            truth = str(data.get("truth", "")).strip()
            clues = data.get("key_clues", [])
            # 难度 LLM 偶尔也会改写；容错到 1-5 之间，超出则用 target_difficulty
            try:
                difficulty = int(data.get("difficulty", target_difficulty))
                if difficulty < 1 or difficulty > 5:
                    difficulty = target_difficulty
            except (TypeError, ValueError):
                difficulty = target_difficulty
            if not surface or not truth or not isinstance(clues, list) or len(clues) == 0:
                raise ValueError("missing required fields in generated puzzle")

            # 入库前先做 cap 淘汰（builtin 不受影响）
            await _enforce_llm_generated_cap(get_config().llm_generated_cap)

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
