"""趣味问答题库离线批量生成脚本。

职责：
1. 对给定类型，调 LLM 生成完整题（answer + aliases + 第 1 套 clues + explanation）
2. 对每道题再调 LLM 生成第 2 套线索（角度不同于第 1 套）
3. 两套都通过自检 + 去重后，原子写入 seeds/trivia_bank/<type>.json
4. 支持断点续传（--resume）：读取已有题库，仅补足到 target_count

用法：
    # 生成 country 类 80 道
    uv run python scripts/generate_trivia_bank.py --type country --count 80

    # 断点续传
    uv run python scripts/generate_trivia_bank.py --type country --count 80 --resume

    # 批量全量（按 trivia-bank.md §3.2 的默认配额）
    uv run python scripts/generate_trivia_bank.py --all

    # 调试：只跑 5 道
    uv run python scripts/generate_trivia_bank.py --type country --count 5

参考：docs/games/trivia-bank.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.plugins.games.trivia.answer_matcher import normalize  # noqa: E402
from src.plugins.games.trivia.prompts import TYPE_IDS  # noqa: E402
from src.plugins.games.trivia.puzzle_generator import (  # noqa: E402
    PuzzleGenerationError,
    _BANK_DIR,
    generate_alt_clue_set,
    generate_puzzle,
)

# ------------------------------------------------------------------
# 日志
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
# 屏蔽 generator 模块 WARNING（失败重试打得太多）
logging.getLogger("src.plugins.games.trivia.puzzle_generator").setLevel(logging.ERROR)
log = logging.getLogger("gen_bank")


# ------------------------------------------------------------------
# §3.2 默认配额
# ------------------------------------------------------------------
DEFAULT_QUOTAS: dict[str, int] = {
    "country": 80,
    "city": 120,
    "food": 120,
    "person": 100,
    "animal": 80,
    "idiom": 80,
}

# 两次 LLM 调用之间的 sleep（秒），避免智谱限流
CALL_GAP_SECS = 0.2
# 每道题生成失败的最大容忍次数（一题失败太多就放弃往下走）
PER_PUZZLE_MAX_FAILURES = 8
# 每批次向 LLM 注入的 avoid 上限（避免 prompt 爆长）
AVOID_WINDOW = 30


# ------------------------------------------------------------------
# 文件 IO（原子写）
# ------------------------------------------------------------------
def _bank_path(type_id: str) -> Path:
    return _BANK_DIR / f"{type_id}.json"


def _rejected_path(type_id: str) -> Path:
    return _BANK_DIR / f"{type_id}_rejected.json"


def _load_existing(type_id: str) -> list[dict]:
    path = _bank_path(type_id)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.warning(f"[{type_id}] 已有 {path.name} 解析失败（{e}），视为空重建")
        return []
    return raw if isinstance(raw, list) else []


def _atomic_write(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # tempfile 必须和 target 在同一盘符
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.stem + "_", suffix=".tmp", dir=str(path.parent)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _append_rejected(type_id: str, entry: dict) -> None:
    path = _rejected_path(type_id)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raw = []
        except json.JSONDecodeError:
            raw = []
    else:
        raw = []
    raw.append(entry)
    _atomic_write(path, raw)


# ------------------------------------------------------------------
# 核心：单题生成
# ------------------------------------------------------------------
# 可疑的"绰号式答案"关键词 —— 生成脚本额外过滤
_SUSPICIOUS_ANSWER_SUFFIXES = (
    "之国", "之都", "之乡", "之城", "之岛", "之邦", "之王国", "王国",
    "Land", "City of", "Country of", "Home of",
)


def _looks_like_nickname(answer: str) -> bool:
    """粗略识别答案是否看着像诗意绰号而不是主名称。"""
    if not answer:
        return False
    # "冰原之国"、"枫叶之国"、"东方之珠" 之类
    for suf in _SUSPICIOUS_ANSWER_SUFFIXES:
        if answer.endswith(suf) and len(answer) > len(suf):
            return True
    return False


def _collect_avoid(existing: list[dict]) -> list[str]:
    """从已有题库收集所有 answer+aliases 用作 avoid。"""
    used: list[str] = []
    for item in existing:
        if not isinstance(item, dict):
            continue
        ans = item.get("answer")
        if isinstance(ans, str) and ans.strip():
            used.append(ans.strip())
        for a in item.get("aliases", []) or []:
            if isinstance(a, str) and a.strip():
                used.append(a.strip())
    return used


def _build_source_tag() -> str:
    return f"llm_gen_{datetime.now().strftime('%Y-%m-%d')}"


async def _generate_one_entry(
    type_id: str,
    avoid: list[str],
    clue_sets_count: int,
) -> dict | None:
    """生成一道完整题（含 N 套线索）。成功返回 entry dict，失败返回 None。"""
    # 1. 先生成完整题（answer + aliases + 第 1 套 clues + explanation）
    try:
        puzzle = await generate_puzzle(type_id, avoid=avoid[-AVOID_WINDOW:])
    except PuzzleGenerationError as e:
        log.warning(f"[{type_id}] 第 1 套生成失败: {e}")
        return None

    # 绰号过滤：LLM 偶尔会把答案写成"冰原之国"，真正主名放 aliases，体验会坑
    if _looks_like_nickname(puzzle.answer):
        log.warning(
            f"[{type_id}] 答案「{puzzle.answer}」看着像绰号（而非主名），拒绝"
        )
        return None

    clue_sets: list[list[str]] = [puzzle.clues]

    # 2. 追加第 2..N 套线索（每套独立的 LLM 调用）
    for i in range(clue_sets_count - 1):
        await asyncio.sleep(CALL_GAP_SECS)
        # 把已有的所有线索都当作"需要避开的"一起传给 alt 生成
        existing_flat: list[str] = []
        for cs in clue_sets:
            existing_flat.extend(cs)
        try:
            alt = await generate_alt_clue_set(
                type_id,
                answer=puzzle.answer,
                aliases=puzzle.aliases,
                existing_clues=existing_flat,
            )
        except PuzzleGenerationError as e:
            log.warning(
                f"[{type_id}] 答案「{puzzle.answer}」第 {i + 2} 套线索失败: {e}，跳过该题"
            )
            return None
        clue_sets.append(alt)

    return {
        "answer": puzzle.answer,
        "aliases": puzzle.aliases,
        "clue_sets": clue_sets,
        "explanation": puzzle.explanation,
        "difficulty": "easy",
        "source": _build_source_tag(),
    }


async def generate_for_type(
    type_id: str,
    target_count: int,
    *,
    clue_sets: int = 2,
    resume: bool = False,
) -> None:
    if type_id not in TYPE_IDS:
        log.error(f"未知类型: {type_id}（合法: {TYPE_IDS}）")
        return

    bank_path = _bank_path(type_id)
    existing: list[dict] = _load_existing(type_id) if resume else []
    if resume and existing:
        log.info(f"[{type_id}] 断点续传：已有 {len(existing)} 道，目标 {target_count}")
    else:
        existing = []
        log.info(f"[{type_id}] 从零开始：目标 {target_count} 道")

    llm_calls_total = 0
    rejected_count = 0
    consecutive_failures = 0
    start_ts = datetime.now()

    while len(existing) < target_count:
        current = len(existing)
        avoid = _collect_avoid(existing)
        log.info(
            f"[{type_id}] 进度 {current}/{target_count}  "
            f"avoid={len(avoid)}  已拒={rejected_count}"
        )

        await asyncio.sleep(CALL_GAP_SECS)
        entry = await _generate_one_entry(type_id, avoid, clue_sets)
        llm_calls_total += clue_sets  # 粗估（含重试失败的）

        if entry is None:
            consecutive_failures += 1
            rejected_count += 1
            if consecutive_failures >= PER_PUZZLE_MAX_FAILURES:
                log.error(
                    f"[{type_id}] 连续 {PER_PUZZLE_MAX_FAILURES} 次失败，"
                    f"可能答案池已耗尽或 LLM 出题不稳。提前停止。"
                )
                break
            continue

        # 再次重查：有没有和已有重复（generate_puzzle 内 avoid 是归一化后的，但可能漏，双保险）
        ans_norm = normalize(entry["answer"])
        dup = False
        for old in existing:
            if normalize(old.get("answer", "")) == ans_norm:
                dup = True
                break
            for a in old.get("aliases", []) or []:
                if normalize(a) == ans_norm:
                    dup = True
                    break
            if dup:
                break
        if dup:
            log.warning(
                f"[{type_id}] 答案「{entry['answer']}」与已有重复（generate 层漏过），跳过"
            )
            rejected_count += 1
            _append_rejected(type_id, {**entry, "_rejected_reason": "dup_after_gen"})
            continue

        consecutive_failures = 0
        existing.append(entry)
        _atomic_write(bank_path, existing)
        log.info(
            f"[{type_id}] ✓ 「{entry['answer']}」入库，"
            f"clue_sets={len(entry['clue_sets'])}×{len(entry['clue_sets'][0])}"
        )

    elapsed = (datetime.now() - start_ts).total_seconds()
    log.info(
        f"[{type_id}] 收工：{len(existing)}/{target_count}  "
        f"用时 {elapsed / 60:.1f} 分钟  LLM 估算调用 {llm_calls_total}+  "
        f"拒绝 {rejected_count}  文件 {bank_path.name}"
    )


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
async def main() -> None:
    parser = argparse.ArgumentParser(description="离线批量生成趣味问答题库")
    parser.add_argument("--type", choices=TYPE_IDS, help="要生成的类型")
    parser.add_argument("--count", type=int, help="目标题数（不指定则用默认配额）")
    parser.add_argument(
        "--clue-sets",
        type=int,
        default=2,
        help="每道题生成多少套线索（默认 2）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="断点续传：读取已有题库，补足到目标数",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="按默认配额批量跑所有类型",
    )
    args = parser.parse_args()

    if args.all:
        for tid, cnt in DEFAULT_QUOTAS.items():
            await generate_for_type(
                tid, cnt, clue_sets=args.clue_sets, resume=args.resume
            )
        return

    if not args.type:
        parser.error("--type 必填（或用 --all）")
    count = args.count if args.count is not None else DEFAULT_QUOTAS.get(args.type, 50)
    await generate_for_type(args.type, count, clue_sets=args.clue_sets, resume=args.resume)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("中断退出。已生成的题目已写入文件，下次可用 --resume 续传。")
