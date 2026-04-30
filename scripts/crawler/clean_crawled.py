"""海龟汤原始题目清洗脚本。

作用：
  读取 scripts/crawler/raw/ 下预先筛选过的 JSON 候选文件，
  调用 LLM 为每题补全 key_clues / category / difficulty 并做轻度润色改写。

输入格式：JSON 数组，每项至少含 title / surface / truth：
  [
    {"title": "...", "surface": "...", "truth": "..."},
    ...
  ]

输出：写到同目录下的 `<basename>.cleaned.json`，格式对齐 seeds/turtle_soup.json：
  [
    {
      "title": "...",
      "category": "日常/悬疑/温情/奇幻",
      "difficulty": 1-5,
      "surface": "...",
      "truth": "...",
      "key_clues": ["...", "..."]
    },
    ...
  ]

幂等：若输出文件已存在，默认跳过已清洗的 title；加 --force 强制覆盖。

用法：
    uv run python scripts/crawler/clean_crawled.py scripts/crawler/raw/preselected.json
    uv run python scripts/crawler/clean_crawled.py scripts/crawler/raw/preselected.json --force
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from core import llm  # noqa: E402
from core.errors import LLMError, LLMJSONParseError  # noqa: E402


CATEGORIES = ["日常", "悬疑", "温情", "奇幻"]


CLEAN_SYSTEM = """你是一个海龟汤题目**格式化工具**，不是作家。

我会给你一道从网上搜集的原始海龟汤题目（含 title / surface / truth 三部分）。
你的任务**只是**：把它套入我们的标准 schema，**不做任何润色、重写、美化、升级**。

════════════════════════════════════════
【硬性规则：原文保留】
════════════════════════════════════════

1. **title**：**原样输出**，一个字都不要改
   - 即使你觉得"影子"这种标题太短、不够吸引人，也要保留"影子"
   - 不要加"之谜"、"之夜"、"的秘密"这种后缀
   - 不要换成四字短语

2. **surface**：**原样输出**原文
   - 只允许修正：明显错别字、网络废字（如"hhh"）、缺失的标点
   - 不要替换词汇（"惊叫"不要改成"惊呼"）
   - 不要调整语气（口语不要改成书面语）
   - **绝对不要**把 truth 里的细节提前到 surface（会破坏谜题）
   - 若原文超过 180 字才允许轻度压缩；≤180 字时一个字都不改

3. **truth**：**原样输出**原文
   - 同上，只做错别字/标点修正
   - 保留生活细节、口语感、叙事节奏
   - **绝对不要**做摘要式总结
   - 若原文超过 500 字才允许压缩；≤500 字时一字不改

════════════════════════════════════════
【你要做的：补三个元数据字段】
════════════════════════════════════════

4. **category**：从 日常 / 悬疑 / 温情 / 奇幻 中选一个
   - 日常：生活反差、无死亡无凶案的轻松故事
   - 悬疑：有凶案、失踪、反转的谜团
   - 温情：情感内核（亲情/思念/遗憾）
   - 奇幻：表面超自然但有现实解释

5. **difficulty**：1-5
   - 1 入门（一句话汤面、汤底也简单直给）
   - 2 简单（1 个反转）
   - 3 中等（有一定推理深度）
   - 4 困难（多层因果或关键细节藏得深）
   - 5 地狱（需要跨域联想或多次反转）

6. **key_clues**：3-5 条短语
   - 每条对应 truth 里的一个**具体关键事实**
   - 要具体、可判定；不要抽象（"有人死了"、"真相被揭露"这种不要）
   - 好例："陈默的父亲已经去世" / "今天是父亲忌日" / "第二杯咖啡是点给已故父亲的"
   - 坏例："神秘事件" / "爱的代价" / "出乎意料的真相"

════════════════════════════════════════
【输出格式】
════════════════════════════════════════

只输出 JSON，无多余文字：
{{
  "title": "<原标题，一字不改>",
  "category": "日常 | 悬疑 | 温情 | 奇幻",
  "difficulty": 1-5,
  "surface": "<原汤面，一字不改（除非明显错字）>",
  "truth": "<原汤底，一字不改（除非明显错字）>",
  "key_clues": ["线索1", "线索2", "线索3"]
}}

记住：你是**格式化工具**，不是编辑。保留原作者的朴实感，让原文长什么样就长什么样。
"""


CLEAN_USER_TEMPLATE = """【原标题】{title}

【原汤面】
{surface}

【原汤底】
{truth}

请按系统要求整理为标准 JSON。"""


async def clean_one(item: dict) -> dict | None:
    """返回清洗后的 dict，失败返回 None。"""
    title = item.get("title", "").strip()
    surface = item.get("surface", "").strip()
    truth = item.get("truth", "").strip()
    if not surface or not truth:
        return None

    try:
        resp = await llm.chat(
            messages=[
                llm.LLMMessage(role="system", content=CLEAN_SYSTEM),
                llm.LLMMessage(
                    role="user",
                    content=CLEAN_USER_TEMPLATE.format(
                        title=title or "无题", surface=surface, truth=truth
                    ),
                ),
            ],
            scene="turtle_soup_host",
            json_mode=True,
        )
        data = resp.json()
    except (LLMError, LLMJSONParseError) as e:
        print(f"  [x] 清洗失败：{e}")
        return None

    # 基础字段校验 + 容错
    clean_title = str(data.get("title", title) or title).strip()
    for prefix in ("标题：", "标题:", "题目：", "题目:"):
        if clean_title.startswith(prefix):
            clean_title = clean_title[len(prefix):].strip()
    if not clean_title:
        clean_title = title or "无题"

    cat = str(data.get("category", "悬疑")).strip()
    if cat not in CATEGORIES:
        cat = "悬疑"

    try:
        diff = int(data.get("difficulty", 3))
        if not 1 <= diff <= 5:
            diff = 3
    except (TypeError, ValueError):
        diff = 3

    clean_surface = str(data.get("surface", surface)).strip() or surface
    clean_truth = str(data.get("truth", truth)).strip() or truth

    clues_raw = data.get("key_clues", [])
    if not isinstance(clues_raw, list) or not clues_raw:
        return None
    clues = [str(c).strip() for c in clues_raw if str(c).strip()]
    if len(clues) < 3:
        print(f"  [!] key_clues 不足 3 条：{clues}，跳过")
        return None

    return {
        "title": clean_title,
        "category": cat,
        "difficulty": diff,
        "surface": clean_surface,
        "truth": clean_truth,
        "key_clues": clues,
    }


async def main(input_path: Path, force: bool) -> None:
    items = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        print(f"[!] 输入不是 JSON 数组：{input_path}")
        sys.exit(1)

    output_path = input_path.with_suffix(".cleaned.json")
    existing_titles: set[str] = set()
    existing: list[dict] = []
    if output_path.exists() and not force:
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            existing_titles = {item["title"] for item in existing if "title" in item}
            print(f"[i] 断点续跑，已有 {len(existing_titles)} 题")
        except Exception as e:  # noqa: BLE001
            print(f"[!] 读取已有输出失败，将覆盖：{e}")

    llm.init()

    results: list[dict] = list(existing)
    skipped = 0
    failed = 0

    t0 = time.perf_counter()
    for i, item in enumerate(items, 1):
        raw_title = item.get("title", f"#{i}")
        if raw_title in existing_titles and not force:
            skipped += 1
            continue
        print(f"[{i}/{len(items)}] 清洗《{raw_title}》 ...")
        cleaned = await clean_one(item)
        if cleaned is None:
            failed += 1
            continue
        print(
            f"  -> {cleaned['category']} / 难度{cleaned['difficulty']} / "
            f"clues={len(cleaned['key_clues'])}"
        )
        results.append(cleaned)
        # 增量写盘（每一条都保存，防止 token 耗尽前的工作丢失）
        output_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    elapsed = time.perf_counter() - t0
    print(
        f"\n[done] 共 {len(items)} 题 → 成功 {len(results) - len(existing)}，"
        f"跳过 {skipped}，失败 {failed}，耗时 {elapsed:.1f}s"
    )
    print(f"[out] {output_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path, help="预筛 JSON 路径")
    p.add_argument("--force", action="store_true", help="覆盖已清洗的题目")
    args = p.parse_args()
    asyncio.run(main(args.input, args.force))
