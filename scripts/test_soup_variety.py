"""海龟汤 v2.0 出题策略验证脚本（临时，验收后可删）。

功能：
- 跑 N 轮 LLM 生成（默认 8 轮），使用 v2.0 的 random category × difficulty 策略
- 不入库（跳过 _pick_from_library / mark_win 流程），只验证 prompt 产出
- 把每轮结果连同统计摘要一起落到 docs/test-runs/ 下的 Markdown 流水文件

用法：
    python scripts/test_soup_variety.py [count]
"""

from __future__ import annotations

import asyncio
import random
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
from core.errors import LLMError, LLMJSONParseError  # noqa: E402
from src.plugins.games.turtle_soup.prompts import (  # noqa: E402
    CATEGORIES,
    HOST_USER,
    TURTLE_SOUP_HOST_PROMPT_VERSION,
    build_host_system_prompt,
)


async def run_one(idx: int, total: int, forced_category: str | None = None) -> dict:
    target_category = forced_category or random.choice(CATEGORIES)
    target_difficulty = random.randint(1, 5)
    system_prompt = build_host_system_prompt(target_category, target_difficulty)

    print(f"[{idx}/{total}] generating category={target_category} difficulty={target_difficulty} ...")
    t0 = time.perf_counter()
    record: dict = {
        "idx": idx,
        "target_category": target_category,
        "target_difficulty": target_difficulty,
        "ok": False,
        "error": None,
        "latency_ms": None,
        "data": None,
    }
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
        record["ok"] = True
        record["data"] = data
        record["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        # 应用与 puzzle_service 相同的兜底逻辑
        returned_cat = str(data.get("category", "")).strip()
        record["category_mismatch"] = (returned_cat != target_category)
        try:
            returned_diff = int(data.get("difficulty", target_difficulty))
        except (TypeError, ValueError):
            returned_diff = -1
        record["difficulty_mismatch"] = (returned_diff != target_difficulty)
        record["returned_category"] = returned_cat
        record["returned_difficulty"] = returned_diff
    except (LLMError, LLMJSONParseError, Exception) as e:  # noqa: BLE001
        record["error"] = f"{type(e).__name__}: {e}"
        record["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        print(f"  -> FAILED: {record['error']}")
    else:
        title = str(record["data"].get("title", "?"))
        print(f"  -> OK in {record['latency_ms']}ms: {title}")
    return record


def render_markdown(records: list[dict], total_elapsed_s: float) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ok_records = [r for r in records if r["ok"]]
    fail_records = [r for r in records if not r["ok"]]

    # 统计
    target_cat_counter = Counter(r["target_category"] for r in records)
    target_diff_counter = Counter(r["target_difficulty"] for r in records)
    cat_mismatch = sum(1 for r in ok_records if r.get("category_mismatch"))
    diff_mismatch = sum(1 for r in ok_records if r.get("difficulty_mismatch"))

    lines: list[str] = []
    lines.append(f"# 海龟汤 v{TURTLE_SOUP_HOST_PROMPT_VERSION} 出题策略验收流水")
    lines.append("")
    lines.append(f"- 运行时间：{now}")
    lines.append(f"- 总耗时：{total_elapsed_s:.1f}s")
    lines.append(f"- HOST Prompt 版本：`{TURTLE_SOUP_HOST_PROMPT_VERSION}`")
    lines.append(f"- 样本数：{len(records)}（成功 {len(ok_records)} / 失败 {len(fail_records)}）")
    lines.append("")

    lines.append("## 1. 分布概览")
    lines.append("")
    lines.append("**目标分类分布（代码层随机指定）：**")
    lines.append("")
    for c in CATEGORIES:
        lines.append(f"- `{c}`: {target_cat_counter.get(c, 0)}")
    lines.append("")
    lines.append("**目标难度分布：**")
    lines.append("")
    for d in range(1, 6):
        lines.append(f"- `难度 {d}`: {target_diff_counter.get(d, 0)}")
    lines.append("")
    lines.append(
        f"**LLM 回写一致性**：category 不一致 {cat_mismatch}/{len(ok_records)}，"
        f"difficulty 不一致 {diff_mismatch}/{len(ok_records)}"
        f"（不一致不影响玩家，代码层会兜底回目标值）"
    )
    lines.append("")

    lines.append("## 2. 每局详情")
    lines.append("")
    for r in records:
        idx = r["idx"]
        tc = r["target_category"]
        td = r["target_difficulty"]
        lat = r["latency_ms"]
        if not r["ok"]:
            lines.append(f"### 第 {idx} 局 · 目标【{tc} / 难度 {td}】❌ 失败")
            lines.append("")
            lines.append(f"- 耗时：{lat}ms")
            lines.append(f"- 错误：`{r['error']}`")
            lines.append("")
            continue

        data = r["data"]
        title = str(data.get("title", "?"))
        ret_cat = r.get("returned_category", "?")
        ret_diff = r.get("returned_difficulty", "?")
        cat_tag = "✅" if not r.get("category_mismatch") else f"⚠️ 回写为 {ret_cat}"
        diff_tag = "✅" if not r.get("difficulty_mismatch") else f"⚠️ 回写为 {ret_diff}"
        surface = str(data.get("surface", "")).strip()
        truth = str(data.get("truth", "")).strip()
        clues = data.get("key_clues", []) or []

        lines.append(f"### 第 {idx} 局 · 目标【{tc} / 难度 {td}】 · 《{title}》")
        lines.append("")
        lines.append(f"- 耗时：{lat}ms")
        lines.append(f"- category 一致性：{cat_tag}")
        lines.append(f"- difficulty 一致性：{diff_tag}")
        lines.append(f"- 汤面长度：{len(surface)} 字；汤底长度：{len(truth)} 字；线索数：{len(clues)}")
        lines.append("")
        lines.append("**汤面**")
        lines.append("")
        lines.append("> " + surface.replace("\n", "\n> "))
        lines.append("")
        lines.append("**汤底**")
        lines.append("")
        lines.append("> " + truth.replace("\n", "\n> "))
        lines.append("")
        lines.append("**关键线索**")
        lines.append("")
        for c in clues:
            lines.append(f"- {c}")
        lines.append("")

    lines.append("## 3. 结论（待人工填写）")
    lines.append("")
    lines.append("- [ ] 4 类分布是否均匀？")
    lines.append("- [ ] 悬疑类是否真的出现了凶案 / 失踪 / 背叛 等成人向元素？")
    lines.append("- [ ] 奇幻类的汤底是否都用了现实解释（没有\"真的是鬼\"）？")
    lines.append("- [ ] 日常 / 温情类调性是否准确？")
    lines.append("- [ ] 难度分层是否与 prompt 约束一致？")
    lines.append("- [ ] 有无失败 / 格式错误 / 异常情况？")
    lines.append("")
    return "\n".join(lines)


async def main(count: int, force_category: str | None = None) -> None:
    llm.init()
    t0 = time.perf_counter()
    records: list[dict] = []
    for i in range(1, count + 1):
        rec = await run_one(i, count, forced_category=force_category)
        records.append(rec)
    total_elapsed = time.perf_counter() - t0

    out_dir = _ROOT / "docs" / "test-runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y%m%d")
    tag_suffix = f"-{force_category}" if force_category else ""
    out_file = out_dir / f"{date_tag}-turtle-soup-category-v2{tag_suffix}.md"
    # 避免同日覆盖：若已存在，加时间后缀
    if out_file.exists():
        time_tag = datetime.now().strftime("%H%M%S")
        out_file = out_dir / f"{date_tag}-{time_tag}-turtle-soup-category-v2{tag_suffix}.md"
    out_file.write_text(render_markdown(records, total_elapsed), encoding="utf-8")
    print(f"\n[test] done. wrote {out_file}")
    print(f"[test] total elapsed: {total_elapsed:.1f}s, "
          f"ok={sum(1 for r in records if r['ok'])}/{len(records)}")


if __name__ == "__main__":
    # 用法：python scripts/test_soup_variety.py [count] [category]
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    force_cat = sys.argv[2] if len(sys.argv) > 2 else None
    if force_cat and force_cat not in CATEGORIES:
        print(f"invalid category: {force_cat}, must be one of {CATEGORIES}")
        sys.exit(1)
    asyncio.run(main(n, force_cat))
