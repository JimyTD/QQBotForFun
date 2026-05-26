"""海龟汤 canonical facts 离线蒸馏脚本。

从 seeds/turtle_soup.json 读取谜面，调用 LLM 提炼 canonical_facts 与 surface_gloss，
写入 seeds/turtle_soup_facts.json（按 title 索引，支持断点续跑）。

用法：
    python scripts/enrich_soup_facts.py
    python scripts/enrich_soup_facts.py --limit 5
    python scripts/enrich_soup_facts.py --title "午夜的第二杯咖啡"
    python scripts/enrich_soup_facts.py --dry-run
    python scripts/enrich_soup_facts.py --force
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from core import llm  # noqa: E402
from core.errors import LLMError, LLMJSONParseError  # noqa: E402

SEEDS_PATH = _ROOT / "seeds" / "turtle_soup.json"
FACTS_PATH = _ROOT / "seeds" / "turtle_soup_facts.json"

SYSTEM_PROMPT = """你是海龟汤谜题的事实提炼助手。根据给定的汤面、汤底与关键线索，输出结构化 JSON。

要求：
1. canonical_facts：5-8 条，用平实中文陈述汤底中的核心事实；每条独立、可判定、不含修辞或剧透式悬念。
2. surface_gloss：一段（3-5 句），说明汤面给人的表面印象 vs 真相之间的落差，帮助判题者理解玩家可能被什么误导。

只输出 JSON，格式严格为：
{"canonical_facts": ["事实1", "事实2", ...], "surface_gloss": "..."}"""

USER_TEMPLATE = """请为以下海龟汤谜题提炼 canonical_facts 与 surface_gloss。

【汤面】
{surface}

【汤底】
{truth}

【关键线索】
{key_clues}"""


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.stem + "_", suffix=".tmp", dir=str(path.parent)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def load_puzzles(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_facts(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"expected dict in {path}, got {type(data).__name__}")
    return data


def _format_key_clues(clues: list[str]) -> str:
    if not clues:
        return "（无）"
    return "\n".join(f"- {c}" for c in clues)


def _validate_distill(data: dict) -> dict:
    facts = data.get("canonical_facts")
    gloss = data.get("surface_gloss")
    if not isinstance(facts, list) or not facts:
        raise LLMJSONParseError("canonical_facts must be a non-empty list")
    if not all(isinstance(x, str) and x.strip() for x in facts):
        raise LLMJSONParseError("canonical_facts items must be non-empty strings")
    if not isinstance(gloss, str) or not gloss.strip():
        raise LLMJSONParseError("surface_gloss must be a non-empty string")
    cleaned_facts = [str(x).strip() for x in facts]
    if not (5 <= len(cleaned_facts) <= 8):
        print(
            f"  [warn] canonical_facts count={len(cleaned_facts)} (expected 5-8), keeping anyway"
        )
    return {
        "canonical_facts": cleaned_facts,
        "surface_gloss": gloss.strip(),
    }


async def distill_one(puzzle: dict, *, scene: str) -> dict:
    user_content = USER_TEMPLATE.format(
        surface=puzzle["surface"].strip(),
        truth=puzzle["truth"].strip(),
        key_clues=_format_key_clues(list(puzzle.get("key_clues") or [])),
    )
    resp = await llm.chat(
        messages=[
            llm.LLMMessage(role="system", content=SYSTEM_PROMPT),
            llm.LLMMessage(role="user", content=user_content),
        ],
        scene=scene,
        json_mode=True,
    )
    return _validate_distill(resp.json())


async def main() -> None:
    parser = argparse.ArgumentParser(description="离线蒸馏海龟汤 canonical facts")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="最多处理 N 道谜题（在过滤与跳过已有之后计数）",
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help='只处理指定标题，如 "午夜的第二杯咖啡"',
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖输出文件中已存在的标题",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印待处理列表，不调用 LLM、不写文件",
    )
    parser.add_argument(
        "--scene",
        type=str,
        default="turtle_soup_host",
        help="LLM 场景名（默认 turtle_soup_host）",
    )
    args = parser.parse_args()

    if not SEEDS_PATH.exists():
        print(f"seed file not found: {SEEDS_PATH}", file=sys.stderr)
        sys.exit(1)

    puzzles = load_puzzles(SEEDS_PATH)
    facts = load_facts(FACTS_PATH)

    if args.title:
        puzzles = [p for p in puzzles if p.get("title") == args.title]
        if not puzzles:
            print(f"no puzzle with title={args.title!r}", file=sys.stderr)
            sys.exit(1)

    pending: list[dict] = []
    skipped = 0
    for puzzle in puzzles:
        title = str(puzzle["title"])
        if title in facts and not args.force:
            skipped += 1
            continue
        pending.append(puzzle)
        if args.limit is not None and len(pending) >= args.limit:
            break

    print(
        f"[enrich] seeds={len(load_puzzles(SEEDS_PATH))} "
        f"existing_facts={len(facts)} skipped={skipped} pending={len(pending)}"
    )

    if not pending:
        print("[enrich] nothing to do.")
        return

    for puzzle in pending:
        title = str(puzzle["title"])
        print(f"  - {title}")

    if args.dry_run:
        print("[enrich] dry-run: no LLM calls, no writes.")
        return

    llm.init()
    ok = 0
    failed = 0
    for puzzle in pending:
        title = str(puzzle["title"])
        print(f"[enrich] distilling: {title}")
        try:
            result = await distill_one(puzzle, scene=args.scene)
            facts[title] = result
            _atomic_write(FACTS_PATH, facts)
            ok += 1
            print(
                f"  -> ok ({len(result['canonical_facts'])} facts, "
                f"gloss {len(result['surface_gloss'])} chars)"
            )
        except (LLMError, LLMJSONParseError, ValueError) as e:
            failed += 1
            print(f"  -> FAILED: {type(e).__name__}: {e}", file=sys.stderr)

    print(f"[enrich] done. ok={ok} failed={failed} total_facts={len(facts)}")


if __name__ == "__main__":
    asyncio.run(main())
