"""趣味问答题目生成器。

职责：
1. 调 LLM 生成题目
2. 做业务层自检（字段、答案不泄露、别名非空、5 条线索等）
3. 失败重试，全失败抛 PuzzleGenerationError
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nonebot import logger

from core import llm
from core.errors import LLMError, LLMJSONParseError

from .answer_matcher import normalize
from .config import get_config
from .prompts import (
    build_host_system_prompt,
    build_host_user_prompt,
)


class PuzzleGenerationError(Exception):
    """题目生成失败（LLM 多次重试仍无法产出合法题目）。"""


@dataclass
class TriviaPuzzle:
    type_id: str
    answer: str
    aliases: list[str] = field(default_factory=list)
    clues: list[str] = field(default_factory=list)
    explanation: str = ""


# ---------- 自检 ----------
def _validate(data: dict, expected_type: str) -> tuple[bool, str]:
    """校验 LLM 输出。返回 (是否通过, 失败原因)。"""
    cfg = get_config()

    # 字段齐全
    for key in ("answer", "aliases", "clues", "explanation"):
        if key not in data:
            return False, f"missing field: {key}"

    answer = data["answer"]
    aliases = data["aliases"]
    clues = data["clues"]
    explanation = data["explanation"]

    if not isinstance(answer, str) or not answer.strip():
        return False, "answer must be non-empty string"
    if len(answer) > 20:
        return False, f"answer too long: {len(answer)}"

    if not isinstance(aliases, list) or len(aliases) == 0:
        return False, "aliases must be non-empty list"
    # 剔除与 answer 完全相同的别名
    aliases = [a for a in aliases if isinstance(a, str) and a.strip() and a.strip() != answer.strip()]
    if not aliases:
        return False, "aliases empty after dedup with answer"
    data["aliases"] = aliases

    if not isinstance(clues, list):
        return False, "clues must be list"
    if len(clues) != cfg.max_clues_per_puzzle:
        return False, f"clues must be {cfg.max_clues_per_puzzle}, got {len(clues)}"
    for i, c in enumerate(clues):
        if not isinstance(c, str) or not c.strip():
            return False, f"clue {i} empty"

    if not isinstance(explanation, str):
        return False, "explanation must be string"

    # 关键自检：答案不能出现在线索里（归一化后的子串判定）
    answer_norm = normalize(answer)
    for i, c in enumerate(clues):
        if answer_norm and answer_norm in normalize(c):
            return False, f"answer leaked in clue {i}: {c[:30]!r}"

    # 别名也不能泄露在线索里（但只检查长度 >= 2 的别名，避免 "A" 这种单字误伤）
    for alias in aliases:
        alias_norm = normalize(alias)
        if len(alias_norm) < 2:
            continue
        for i, c in enumerate(clues):
            if alias_norm in normalize(c):
                return False, f"alias {alias!r} leaked in clue {i}"

    return True, ""


# ---------- 生成 ----------
async def generate_puzzle(
    type_id: str,
    *,
    retries: int | None = None,
) -> TriviaPuzzle:
    """生成一道指定类型的题目。失败会重试；全失败抛 PuzzleGenerationError。"""
    cfg = get_config()
    retries = retries if retries is not None else cfg.llm_retry_times

    last_err: str = ""
    for attempt in range(1, retries + 1):
        try:
            resp = await llm.chat(
                messages=[
                    llm.LLMMessage(role="system", content=build_host_system_prompt(type_id)),
                    llm.LLMMessage(role="user", content=build_host_user_prompt(type_id)),
                ],
                scene="trivia_host",
                json_mode=True,
            )
        except LLMError as e:
            last_err = f"llm error: {e}"
            logger.warning(f"[trivia] gen attempt {attempt} llm error: {e}")
            continue

        try:
            data = resp.json()
        except LLMJSONParseError as e:
            last_err = f"json parse: {e}"
            logger.warning(f"[trivia] gen attempt {attempt} json parse: {e}")
            continue

        ok, reason = _validate(data, type_id)
        if not ok:
            last_err = reason
            logger.warning(f"[trivia] gen attempt {attempt} validation failed: {reason}")
            continue

        return TriviaPuzzle(
            type_id=type_id,
            answer=data["answer"].strip(),
            aliases=[a.strip() for a in data["aliases"]],
            clues=[c.strip() for c in data["clues"]],
            explanation=data["explanation"].strip(),
        )

    raise PuzzleGenerationError(
        f"generate failed after {retries} attempts: {last_err}"
    )
