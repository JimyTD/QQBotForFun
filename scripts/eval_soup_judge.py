"""海龟汤 judge 质量评测：baseline (v1.2) vs optimized (v1.3 + facts)。

用法：
    uv run --no-sync python scripts/eval_soup_judge.py
    uv run --no-sync python scripts/eval_soup_judge.py --runs 2
    uv run --no-sync python scripts/eval_soup_judge.py --mode baseline
    uv run --no-sync python scripts/eval_soup_judge.py --limit 5

读取 tests/eval/turtle_soup/golden_judge.jsonl，调用真实 LLM（scene=turtle_soup_judge）。
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from core import llm  # noqa: E402
from src.plugins.games.turtle_soup.prompts import build_judge_system_prompt  # noqa: E402
from src.plugins.games.turtle_soup.puzzle_service import facts_for_title  # noqa: E402

GOLDEN_PATH = _ROOT / "tests" / "eval" / "turtle_soup" / "golden_judge.jsonl"


@dataclass
class GoldenCase:
    id: str
    tags: list[str]
    puzzle: dict
    question: str
    expected_type: str
    acceptable: list[str]
    rationale: str


@dataclass
class CaseResult:
    case_id: str
    expected: str
    actual: str
    score: float
    ok: bool
    note: str


@dataclass
class ModeReport:
    name: str
    strict_acc: float = 0.0
    soft_acc: float = 0.0
    json_valid_rate: float = 0.0
    tag_scores: dict[str, float] = field(default_factory=dict)
    failures: list[CaseResult] = field(default_factory=list)
    latency_ms_p50: int = 0


def load_golden(path: Path, limit: int | None) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            exp = raw["expected"]
            cases.append(
                GoldenCase(
                    id=raw["id"],
                    tags=list(raw.get("tags") or []),
                    puzzle=dict(raw["puzzle"]),
                    question=raw["question"],
                    expected_type=str(exp["type"]),
                    acceptable=[str(x) for x in exp.get("acceptable") or []],
                    rationale=str(raw.get("rationale") or ""),
                )
            )
    if limit is not None:
        cases = cases[:limit]
    return cases


def score_verdict(actual: str, expected: str, acceptable: list[str]) -> tuple[float, bool]:
    if actual == expected:
        return 1.0, True
    if actual in acceptable or expected in acceptable:
        return 1.0, True
    if actual in ("yes", "key") and expected in ("yes", "key"):
        return 0.7, False
    return 0.0, False


def resolve_facts(puzzle: dict) -> tuple[list[str] | None, str | None]:
    facts = puzzle.get("canonical_facts")
    gloss = puzzle.get("surface_gloss")
    if facts or gloss:
        f_list = [str(x) for x in facts] if isinstance(facts, list) else []
        g = str(gloss).strip() if gloss else ""
        return (f_list or None), (g or None)
    title = str(puzzle.get("title") or "")
    if title:
        f_list, g = facts_for_title(title)
        return (f_list or None), (g or None)
    return None, None


async def run_case(
    case: GoldenCase,
    *,
    version: str,
    use_facts: bool,
) -> tuple[CaseResult, int, bool]:
    facts, gloss = (None, None)
    if use_facts:
        facts, gloss = resolve_facts(case.puzzle)

    system = build_judge_system_prompt(
        surface=case.puzzle["surface"],
        truth=case.puzzle["truth"],
        key_clues=list(case.puzzle.get("key_clues") or []),
        canonical_facts=facts,
        surface_gloss=gloss,
        version=version,
    )
    start = time.monotonic()
    json_ok = False
    actual = ""
    try:
        resp = await llm.chat(
            messages=[
                llm.LLMMessage(role="system", content=system),
                llm.LLMMessage(role="user", content=f"玩家问题：{case.question}"),
            ],
            scene="turtle_soup_judge",
            json_mode=True,
        )
        latency = int((time.monotonic() - start) * 1000)
        data = resp.json()
        actual = str(data.get("type", ""))
        json_ok = bool(actual)
    except Exception as e:  # noqa: BLE001
        latency = int((time.monotonic() - start) * 1000)
        return (
            CaseResult(case.id, case.expected_type, "", 0.0, False, f"error: {e}"),
            latency,
            False,
        )

    sc, ok = score_verdict(actual, case.expected_type, case.acceptable)
    note = actual if ok else f"{actual}(期望{case.expected_type})"
    return (
        CaseResult(case.id, case.expected_type, actual, sc, ok, note),
        latency,
        json_ok,
    )


async def eval_mode(
    name: str,
    cases: list[GoldenCase],
    *,
    version: str,
    use_facts: bool,
    runs: int,
) -> ModeReport:
    report = ModeReport(name=name)
    tag_totals: dict[str, list[float]] = defaultdict(list)
    latencies: list[int] = []
    strict_hits = 0
    soft_sum = 0.0
    json_ok_count = 0
    total = 0

    for case in cases:
        run_scores: list[float] = []
        last_result: CaseResult | None = None
        for _ in range(runs):
            result, latency, json_ok = await run_case(
                case, version=version, use_facts=use_facts
            )
            last_result = result
            latencies.append(latency)
            run_scores.append(result.score)
            if json_ok:
                json_ok_count += 1
            await asyncio.sleep(0.25)

        assert last_result is not None
        avg = sum(run_scores) / len(run_scores)
        soft_sum += avg
        total += 1
        if last_result.actual == case.expected_type:
            strict_hits += 1
        for tag in case.tags:
            tag_totals[tag].append(avg)
        if avg < 1.0 and last_result is not None:
            report.failures.append(last_result)

    report.strict_acc = strict_hits / total if total else 0.0
    report.soft_acc = soft_sum / total if total else 0.0
    report.json_valid_rate = json_ok_count / (total * runs) if total else 0.0
    report.tag_scores = {
        tag: sum(vals) / len(vals) for tag, vals in sorted(tag_totals.items())
    }
    if latencies:
        latencies.sort()
        report.latency_ms_p50 = latencies[len(latencies) // 2]
    return report


def print_report(report: ModeReport) -> None:
    print(f"\n{'=' * 60}")
    print(f"模式: {report.name}")
    print(f"  Strict Acc : {report.strict_acc:.1%}")
    print(f"  Soft Acc   : {report.soft_acc:.1%}")
    print(f"  JSON Valid : {report.json_valid_rate:.1%}")
    print(f"  Latency P50: {report.latency_ms_p50} ms")
    if report.tag_scores:
        print("  按 tag:")
        for tag, sc in report.tag_scores.items():
            print(f"    {tag:12s} {sc:.1%}")
    if report.failures:
        print(f"  未满分 ({len(report.failures)}):")
        for f in report.failures[:8]:
            print(f"    - {f.case_id}: {f.note}")
        if len(report.failures) > 8:
            print(f"    ... 另有 {len(report.failures) - 8} 条")


def print_comparison(reports: list[ModeReport]) -> None:
    print(f"\n{'=' * 60}")
    print("对比摘要")
    print(f"{'模式':<28} {'Strict':>8} {'Soft':>8} {'F1 tag':>8}")
    print("-" * 60)
    for r in reports:
        f1 = r.tag_scores.get("F1", 0.0)
        print(f"{r.name:<28} {r.strict_acc:>7.1%} {r.soft_acc:>7.1%} {f1:>7.1%}")
    if len(reports) >= 2:
        base, opt = reports[0], reports[-1]
        print("-" * 60)
        print(
            f"Δ (optimized - baseline)  "
            f"Strict {opt.strict_acc - base.strict_acc:+.1%}  "
            f"Soft {opt.soft_acc - base.soft_acc:+.1%}  "
            f"F1 {opt.tag_scores.get('F1', 0) - base.tag_scores.get('F1', 0):+.1%}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="海龟汤 judge eval")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条 case")
    parser.add_argument("--runs", type=int, default=1, help="每条 case 重复次数")
    parser.add_argument(
        "--mode",
        choices=("all", "baseline", "v1.3", "v1.3+facts"),
        default="all",
        help="评测模式",
    )
    args = parser.parse_args()

    if not GOLDEN_PATH.exists():
        print(f"golden file not found: {GOLDEN_PATH}", file=sys.stderr)
        sys.exit(1)

    cases = load_golden(GOLDEN_PATH, args.limit)
    print(f"[eval] loaded {len(cases)} cases from {GOLDEN_PATH.name}")

    llm.init()

    reports: list[ModeReport] = []
    modes: list[tuple[str, str, bool]] = []
    if args.mode in ("all", "baseline"):
        modes.append(("baseline (v1.2)", "1.2", False))
    if args.mode in ("all", "v1.3"):
        modes.append(("v1.3 prompt only", "1.3", False))
    if args.mode in ("all", "v1.3+facts"):
        modes.append(("v1.3 + facts (prod)", "1.3", True))

    for name, version, use_facts in modes:
        print(f"\n[eval] running {name} ...")
        reports.append(
            await eval_mode(
                name,
                cases,
                version=version,
                use_facts=use_facts,
                runs=args.runs,
            )
        )
        print_report(reports[-1])

    if len(reports) >= 2:
        print_comparison(reports)


if __name__ == "__main__":
    asyncio.run(main())
