"""趣味问答题目生成器 & 题库加载器。

本模块有两类 API：

1. **运行时（游戏层调用）** —— 纯题库，无 LLM：
   - `load_bank(type_id)`：启动 / 首次调用时加载题库到内存缓存
   - `get_puzzle_from_bank(type_id, avoid)`：随机抽一道题 + 一套线索
   - `BankNotAvailableError`：题库缺失 / 为空

2. **生成期（离线脚本调用）** —— 调 LLM：
   - `generate_puzzle(type_id, avoid)`：生成完整题（answer + aliases + 1 套 clues + explanation）
   - `generate_alt_clue_set(type_id, answer, aliases, existing_clues)`：为同答案生成第 2 套线索
   - `_validate(data, type_id)`：业务层自检（字段、self-leak、重复）
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from nonebot import logger

from core import llm
from core.errors import LLMError, LLMJSONParseError

from .answer_matcher import normalize
from .config import get_config
from .prompts import (
    build_alt_clue_system_prompt,
    build_alt_clue_user_prompt,
    build_host_system_prompt,
    build_host_user_prompt,
)


class PuzzleGenerationError(Exception):
    """题目生成失败（LLM 多次重试仍无法产出合法题目）。"""


class BankNotAvailableError(Exception):
    """题库文件缺失或为空。运行时出题失败的硬错误。"""


@dataclass
class TriviaPuzzle:
    """运行时出题后交给游戏层的完整题（仅含选中的那一套线索）。"""
    type_id: str
    answer: str
    aliases: list[str] = field(default_factory=list)
    clues: list[str] = field(default_factory=list)
    explanation: str = ""


@dataclass
class BankEntry:
    """题库中每一条题目（含多套线索）。"""
    answer: str
    aliases: list[str] = field(default_factory=list)
    clue_sets: list[list[str]] = field(default_factory=list)  # 每套 5 条
    explanation: str = ""
    difficulty: str = "easy"
    source: str = ""


# -------------------- 题库路径 / 加载 --------------------
_BANK_DIR = Path(__file__).resolve().parents[4] / "seeds" / "trivia_bank"
_bank_cache: dict[str, list[BankEntry]] = {}


def _bank_path(type_id: str) -> Path:
    return _BANK_DIR / f"{type_id}.json"


def load_bank(type_id: str, *, reload: bool = False) -> list[BankEntry]:
    """加载指定类型的题库到进程缓存。reload=True 时强制重读。"""
    if not reload and type_id in _bank_cache:
        return _bank_cache[type_id]

    path = _bank_path(type_id)
    if not path.exists():
        raise BankNotAvailableError(
            f"题库文件不存在: {path}。请先运行 scripts/generate_trivia_bank.py 生成。"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BankNotAvailableError(f"题库 JSON 解析失败 {path}: {e}") from e

    if not isinstance(raw, list) or not raw:
        raise BankNotAvailableError(f"题库为空或格式错误: {path}")

    entries: list[BankEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        answer = item.get("answer")
        clue_sets = item.get("clue_sets")
        if not isinstance(answer, str) or not isinstance(clue_sets, list) or not clue_sets:
            continue
        entries.append(
            BankEntry(
                answer=answer.strip(),
                aliases=[a.strip() for a in item.get("aliases", []) if isinstance(a, str) and a.strip()],
                clue_sets=[[c.strip() for c in cs if isinstance(c, str)] for cs in clue_sets if isinstance(cs, list)],
                explanation=(item.get("explanation") or "").strip(),
                difficulty=(item.get("difficulty") or "easy"),
                source=(item.get("source") or ""),
            )
        )

    if not entries:
        raise BankNotAvailableError(f"题库有效条目为 0: {path}")

    _bank_cache[type_id] = entries
    logger.info(f"[trivia] bank loaded {type_id}: {len(entries)} entries from {path}")
    return entries


def get_puzzle_from_bank(
    type_id: str,
    *,
    avoid: list[str] | None = None,
) -> TriviaPuzzle:
    """运行时出题：从题库随机抽一道，再从该题的 clue_sets 里随机抽一套。

    avoid: 本局已出过的答案+别名，归一化后用于排除；全空则降级为允许重复抽取
    （§6.3 池空策略 A：允许跨局重复 + 本局超配时回退）。
    """
    entries = load_bank(type_id)  # 可能抛 BankNotAvailableError

    avoid_norms: frozenset[str] = frozenset(
        n for n in (normalize(a) for a in (avoid or []) if isinstance(a, str)) if n
    )

    # 先尝试按 avoid 过滤
    def _is_avoided(entry: BankEntry) -> bool:
        if not avoid_norms:
            return False
        if normalize(entry.answer) in avoid_norms:
            return True
        for a in entry.aliases:
            an = normalize(a)
            if an and an in avoid_norms:
                return True
        return False

    candidates = [e for e in entries if not _is_avoided(e)]
    if not candidates:
        # 本局 avoid 把题库撸光了（极少发生，仅当单类型连出超过题库容量题数时）
        # 策略：降级为整个题库（允许同答案再出一次）
        logger.warning(
            f"[trivia] bank pool exhausted by avoid for type={type_id}, "
            f"falling back to full bank (avoid ignored)"
        )
        candidates = entries

    entry = random.choice(candidates)
    clue_set = random.choice(entry.clue_sets) if entry.clue_sets else []
    return TriviaPuzzle(
        type_id=type_id,
        answer=entry.answer,
        aliases=list(entry.aliases),
        clues=list(clue_set),
        explanation=entry.explanation,
    )


# ---------- 自检 ----------
def _validate(
    data: dict,
    expected_type: str,
    *,
    avoid_norms: frozenset[str] = frozenset(),
) -> tuple[bool, str]:
    """校验 LLM 输出。返回 (是否通过, 失败原因)。

    avoid_norms: 已归一化的禁用答案/别名集合。LLM 如果再出一样的（即使换了表述
    但归一化相同），直接判失败触发重试。
    """
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

    # 查重：归一化后的 answer 或任一 alias 命中禁用集合都算重复
    if avoid_norms:
        if answer_norm and answer_norm in avoid_norms:
            return False, f"answer {answer!r} duplicates previous puzzle"
        for alias in aliases:
            alias_norm = normalize(alias)
            if alias_norm and alias_norm in avoid_norms:
                return False, f"alias {alias!r} duplicates previous puzzle"

    return True, ""


def _validate_alt_clues(
    answer: str,
    aliases: list[str],
    clues: list[str],
    existing_clues: list[str] | None,
) -> tuple[bool, str]:
    """对"第 2 套线索"单独做校验（字段更少，但要排除与第 1 套高度雷同）。"""
    cfg = get_config()
    if not isinstance(clues, list) or len(clues) != cfg.max_clues_per_puzzle:
        return False, f"clues must be {cfg.max_clues_per_puzzle}, got {len(clues) if isinstance(clues, list) else 'N/A'}"
    for i, c in enumerate(clues):
        if not isinstance(c, str) or not c.strip():
            return False, f"clue {i} empty"

    # self-leak 复用
    answer_norm = normalize(answer)
    for i, c in enumerate(clues):
        if answer_norm and answer_norm in normalize(c):
            return False, f"answer leaked in alt clue {i}"
    for alias in aliases:
        alias_norm = normalize(alias)
        if len(alias_norm) < 2:
            continue
        for i, c in enumerate(clues):
            if alias_norm in normalize(c):
                return False, f"alias {alias!r} leaked in alt clue {i}"

    # 不允许任一新线索与旧线索归一化后完全相同
    if existing_clues:
        old_norms = {normalize(c) for c in existing_clues}
        for i, c in enumerate(clues):
            if normalize(c) in old_norms:
                return False, f"alt clue {i} duplicates existing clue"

    return True, ""


# ---------- 生成（LLM）——仅离线脚本调用 ----------
async def generate_puzzle(
    type_id: str,
    *,
    retries: int | None = None,
    avoid: list[str] | None = None,
) -> TriviaPuzzle:
    """【离线生成期】调 LLM 生成一道完整题目（1 套线索）。失败会重试；全失败抛 PuzzleGenerationError。

    avoid: 已出过的答案/别名列表，会被：
      1. 注入 user prompt 让 LLM 主动避开
      2. 归一化后加入 validation 黑名单，LLM 若仍重复则判失败触发重试

    重试时，**每次失败的答案+别名也会追加进 avoid**，防止连续试同款易自泄露的
    答案（e.g. 哈利·波特/孙悟空/宙斯 这种"名字=作品名"的人物）。
    """
    cfg = get_config()
    retries = retries if retries is not None else cfg.llm_retry_times

    # 累计的 avoid 列表：起始于调用方传入的历史 + 每次失败动态追加
    rolling_avoid: list[str] = list(avoid or [])

    last_err: str = ""
    for attempt in range(1, retries + 1):
        avoid_norms: frozenset[str] = frozenset(
            n for n in (normalize(a) for a in rolling_avoid if isinstance(a, str)) if n
        )

        try:
            resp = await llm.chat(
                messages=[
                    llm.LLMMessage(role="system", content=build_host_system_prompt(type_id)),
                    llm.LLMMessage(
                        role="user",
                        content=build_host_user_prompt(type_id, avoid=rolling_avoid),
                    ),
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

        ok, reason = _validate(data, type_id, avoid_norms=avoid_norms)
        if not ok:
            last_err = reason
            logger.warning(f"[trivia] gen attempt {attempt} validation failed: {reason}")
            failed_ans = data.get("answer")
            if isinstance(failed_ans, str) and failed_ans.strip():
                rolling_avoid.append(failed_ans.strip())
            for a in data.get("aliases", []) or []:
                if isinstance(a, str) and a.strip():
                    rolling_avoid.append(a.strip())
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


async def generate_alt_clue_set(
    type_id: str,
    answer: str,
    aliases: list[str],
    existing_clues: list[str],
    *,
    retries: int | None = None,
) -> list[str]:
    """【离线生成期】为已有的 answer 生成一套**不同角度**的线索（用于题库的第 2 套）。

    返回 5 条线索的列表。失败抛 PuzzleGenerationError。
    """
    cfg = get_config()
    retries = retries if retries is not None else cfg.llm_retry_times

    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            resp = await llm.chat(
                messages=[
                    llm.LLMMessage(role="system", content=build_alt_clue_system_prompt(type_id)),
                    llm.LLMMessage(
                        role="user",
                        content=build_alt_clue_user_prompt(
                            type_id, answer=answer, aliases=aliases, existing_clues=existing_clues
                        ),
                    ),
                ],
                scene="trivia_host",
                json_mode=True,
            )
        except LLMError as e:
            last_err = f"llm error: {e}"
            logger.warning(f"[trivia] alt clue attempt {attempt} llm error: {e}")
            continue

        try:
            data = resp.json()
        except LLMJSONParseError as e:
            last_err = f"json parse: {e}"
            continue

        clues = data.get("clues") if isinstance(data, dict) else None
        if not isinstance(clues, list):
            last_err = "clues not list"
            logger.warning(f"[trivia] alt clue attempt {attempt} clues not list")
            continue
        clues = [c.strip() for c in clues if isinstance(c, str)]

        ok, reason = _validate_alt_clues(answer, aliases, clues, existing_clues)
        if not ok:
            last_err = reason
            logger.warning(f"[trivia] alt clue attempt {attempt} validation failed: {reason}")
            continue

        return clues

    raise PuzzleGenerationError(
        f"alt clue generation failed after {retries} attempts: {last_err}"
    )

