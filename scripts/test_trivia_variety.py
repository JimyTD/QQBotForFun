"""趣味问答 v1 出题策略验收脚本。

功能：
- 跑 N 轮 LLM 生成（默认 12 轮 = 每类 2 道）
- 不入库、不算得分，只验证 prompt 产出质量
- 把每道题的详情连同统计摘要落到 docs/test-runs/ 下的 Markdown 流水文件
- 支持 force_type（只跑某一类的若干道，便于定向调优）

用法：
    python scripts/test_trivia_variety.py              # 默认 12 轮，6 类轮询
    python scripts/test_trivia_variety.py 18           # 18 轮
    python scripts/test_trivia_variety.py 5 idiom      # 5 轮，只跑成语

与 docs/test-runs/README.md 的约定保持一致。
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from core import llm  # noqa: E402
from src.plugins.games.trivia.answer_matcher import normalize  # noqa: E402
from src.plugins.games.trivia.prompts import (  # noqa: E402
    TRIVIA_HOST_PROMPT_VERSION,
    TYPE_IDS,
    TYPE_STYLE_GUIDES,
)
from src.plugins.games.trivia.puzzle_generator import (  # noqa: E402
    PuzzleGenerationError,
    generate_puzzle,
)


# ========== 单轮生成 ==========
async def run_one(idx: int, total: int, type_id: str) -> dict:
    type_info = TYPE_STYLE_GUIDES[type_id]
    print(f"[{idx}/{total}] generating type={type_id} ({type_info['name']}) ...")
    t0 = time.perf_counter()
    record: dict = {
        "idx": idx,
        "type_id": type_id,
        "type_name": type_info["name"],
        "ok": False,
        "error": None,
        "latency_ms": None,
        "puzzle": None,
        "warnings": [],
    }
    try:
        puzzle = await generate_puzzle(type_id)
    except PuzzleGenerationError as e:
        record["error"] = f"PuzzleGenerationError: {e}"
        record["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        print(f"  -> FAILED: {e}")
        return record
    except Exception as e:  # noqa: BLE001
        record["error"] = f"{type(e).__name__}: {e}"
        record["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        print(f"  -> UNEXPECTED ERR: {e}")
        return record

    record["ok"] = True
    record["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    record["puzzle"] = {
        "answer": puzzle.answer,
        "aliases": list(puzzle.aliases),
        "clues": list(puzzle.clues),
        "explanation": puzzle.explanation,
    }

    # 生成期自检之外的"可疑项"（不算失败，只是提示值得人工看一眼）
    warnings: list[str] = []
    if len(puzzle.aliases) < 2:
        warnings.append(f"aliases 只给了 {len(puzzle.aliases)} 个（建议 2-5 个）")
    if not puzzle.explanation:
        warnings.append("explanation 为空")
    elif len(puzzle.explanation) < 10:
        warnings.append(f"explanation 过短（{len(puzzle.explanation)} 字）")
    # 线索递进性的土办法：最后一条平均字数 > 第一条，通常代表"越说越具体"
    if puzzle.clues:
        first_len = len(puzzle.clues[0])
        last_len = len(puzzle.clues[-1])
        if last_len < first_len - 10:
            warnings.append(f"⚠️ 最后一条线索比第一条明显更短（{last_len} vs {first_len}），可能递进性有问题")
    # 线索重复性：完全一致或高度重叠
    norm_clues = [normalize(c) for c in puzzle.clues]
    if len(set(norm_clues)) < len(norm_clues):
        warnings.append("⚠️ 有完全重复的线索")
    record["warnings"] = warnings

    print(f"  -> OK in {record['latency_ms']}ms: {puzzle.answer} ({len(puzzle.aliases)} 别名)")
    if warnings:
        for w in warnings:
            print(f"     · {w}")
    return record


# ========== Markdown 渲染 ==========
def render_markdown(records: list[dict], total_elapsed_s: float) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ok_records = [r for r in records if r["ok"]]
    fail_records = [r for r in records if not r["ok"]]

    # 统计
    type_counter = Counter(r["type_id"] for r in records)
    warn_count = sum(1 for r in ok_records if r["warnings"])
    avg_latency = (
        sum(r["latency_ms"] for r in ok_records) / len(ok_records)
        if ok_records else 0
    )

    lines: list[str] = []
    lines.append(f"# 趣味问答 v{TRIVIA_HOST_PROMPT_VERSION} 出题策略验收流水")
    lines.append("")
    lines.append(f"- 运行时间：{now}")
    lines.append(f"- 总耗时：{total_elapsed_s:.1f}s")
    lines.append(f"- HOST Prompt 版本：`{TRIVIA_HOST_PROMPT_VERSION}`")
    lines.append(f"- 样本数：{len(records)}（成功 {len(ok_records)} / 失败 {len(fail_records)}）")
    lines.append(f"- 成功样本平均耗时：{avg_latency:.0f}ms")
    lines.append(f"- 带「可疑项」警告的样本：{warn_count}/{len(ok_records)}")
    lines.append("")

    lines.append("## 1. 分布概览")
    lines.append("")
    lines.append("**各类型数量：**")
    lines.append("")
    for tid in TYPE_IDS:
        info = TYPE_STYLE_GUIDES[tid]
        lines.append(f"- {info['emoji']} {info['name']} (`{tid}`)：{type_counter.get(tid, 0)}")
    lines.append("")

    lines.append("## 2. 每题详情")
    lines.append("")
    for r in records:
        idx = r["idx"]
        tname = r["type_name"]
        tid = r["type_id"]
        lat = r["latency_ms"]
        if not r["ok"]:
            lines.append(f"### 第 {idx} 题 · 【{tname} / {tid}】❌ 失败")
            lines.append("")
            lines.append(f"- 耗时：{lat}ms")
            lines.append(f"- 错误：`{r['error']}`")
            lines.append("")
            continue

        p = r["puzzle"]
        warn = r["warnings"]
        warn_tag = " ⚠️" if warn else ""
        lines.append(f"### 第 {idx} 题 · 【{tname}】· 《{p['answer']}》{warn_tag}")
        lines.append("")
        lines.append(f"- 耗时：{lat}ms")
        lines.append(f"- **答案**：{p['answer']}")
        lines.append(f"- **别名**（{len(p['aliases'])} 个）：{ '、'.join(p['aliases']) }")
        lines.append("")
        lines.append("**5 条线索（从难到易）：**")
        lines.append("")
        for i, c in enumerate(p["clues"], 1):
            lines.append(f"{i}. {c}")
        lines.append("")
        lines.append(f"**讲解**：{p['explanation']}")
        if warn:
            lines.append("")
            lines.append("**可疑项（人工判断）：**")
            for w in warn:
                lines.append(f"- {w}")
        lines.append("")

    lines.append("## 3. 结论（待人工填写）")
    lines.append("")
    lines.append("- [ ] **线索梯度**：5 条线索是否真的从难到易？有没有第 1 条就剧透的？")
    lines.append("- [ ] **答案明确性**：每个答案是否唯一、无歧义？（比如「白菜」是否该叫「大白菜」）")
    lines.append("- [ ] **别名齐全度**：需要英文名的类型（国家/城市/动物）是否都给了？")
    lines.append("- [ ] **线索信息量**：有没有「废话线索」（「它是很棒的 X」这种）？")
    lines.append("- [ ] **国家/城市**：是否都在常见知名范围（避免瑙鲁/列支敦士登这种小国）？")
    lines.append("- [ ] **人物**：真人为主；虚构只限神话/经典文学（孙悟空/福尔摩斯），没有现代动漫游戏 IP？")
    lines.append("- [ ] **成语**：是否都有典故（完璧归赵/刻舟求剑类），而不是纯描述性（一丝不苟）？")
    lines.append("- [ ] **泄露检测**：自检是否都通过了？如有可疑再人工扫一眼每条线索。")
    lines.append("- [ ] **讲解质量**：是否提供了有价值的小知识，而不是抄一遍答案？")
    lines.append("- [ ] **失败/异常**：多少道生成失败？是重试后仍失败还是首次就挂？")
    lines.append("")
    return "\n".join(lines)


# ========== 主流程 ==========
def _plan_types(count: int, force_type: str | None) -> list[str]:
    """生成本次跑的类型序列。"""
    if force_type:
        return [force_type] * count
    # 轮询 6 类：保证每类大致均匀
    plan: list[str] = []
    for i in range(count):
        plan.append(TYPE_IDS[i % len(TYPE_IDS)])
    return plan


async def main(count: int, force_type: str | None = None) -> None:
    llm.init()
    t0 = time.perf_counter()
    plan = _plan_types(count, force_type)
    records: list[dict] = []
    for i, tid in enumerate(plan, 1):
        rec = await run_one(i, count, tid)
        records.append(rec)
    total_elapsed = time.perf_counter() - t0

    out_dir = _ROOT / "docs" / "test-runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y%m%d")
    tag_suffix = f"-{force_type}" if force_type else ""
    out_file = out_dir / f"{date_tag}-trivia-lines-v{TRIVIA_HOST_PROMPT_VERSION}{tag_suffix}.md"
    # 避免同日覆盖
    if out_file.exists():
        time_tag = datetime.now().strftime("%H%M%S")
        out_file = out_dir / (
            f"{date_tag}-{time_tag}-trivia-lines-v{TRIVIA_HOST_PROMPT_VERSION}{tag_suffix}.md"
        )
    out_file.write_text(render_markdown(records, total_elapsed), encoding="utf-8")
    print(f"\n[test] done. wrote {out_file}")
    print(
        f"[test] total elapsed: {total_elapsed:.1f}s, "
        f"ok={sum(1 for r in records if r['ok'])}/{len(records)}"
    )


if __name__ == "__main__":
    # 用法：python scripts/test_trivia_variety.py [count] [type]
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    forced = sys.argv[2] if len(sys.argv) > 2 else None
    if forced and forced not in TYPE_IDS:
        print(f"invalid type: {forced}, must be one of {TYPE_IDS}")
        sys.exit(1)
    asyncio.run(main(n, forced))
