"""海龟汤 judge 质量对比：仅包含有意义的候选模型。

- 生产模型 + 同生态备选
- ping 不通的模型静默跳过，不出现在报告中

用法：
    uv run --no-sync python scripts/eval_judge_compare.py
    uv run --no-sync python scripts/eval_judge_compare.py --tags F1
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
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

from openai import AsyncOpenAI  # noqa: E402

from src.plugins.games.turtle_soup.prompts import build_judge_system_prompt  # noqa: E402
from src.settings import get_settings  # noqa: E402

GOLDEN_PATH = _ROOT / "tests" / "eval" / "turtle_soup" / "golden_judge.jsonl"
PRODUCTION_JUDGE_MODEL = "LongCat-Flash-Chat"

PROVIDERS = {
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "longcat": "https://api.longcat.chat/openai",
}


@dataclass(frozen=True)
class ModelCandidate:
    provider: str
    model: str
    label: str


def meaningful_candidates() -> list[ModelCandidate]:
    """仅纳入可能上生产的模型；老模型 / 已知不可用的不在此列。"""
    return [
        ModelCandidate("longcat", PRODUCTION_JUDGE_MODEL, "生产 judge"),
        ModelCandidate("longcat", "LongCat-Flash-Lite", "查资料 / judge 备选"),
        ModelCandidate("zhipu", "glm-4-flash-250414", "智谱出题/兜底"),
    ]


@dataclass
class GoldenCase:
    id: str
    tags: list[str]
    puzzle: dict
    question: str
    expected_type: str
    acceptable: list[str]


@dataclass
class ModelScore:
    candidate: ModelCandidate
    strict_acc: float = 0.0
    soft_acc: float = 0.0
    f1_soft: float = 0.0
    latency_p50: int = 0
    ping_ms: int = 0
    failures: list[str] = field(default_factory=list)


def get_client(provider: str) -> AsyncOpenAI | None:
    settings = get_settings()
    key_map = {
        "zhipu": "zhipu_api_key",
        "longcat": "longcat_api_key",
    }
    if provider not in key_map or provider not in PROVIDERS:
        return None
    api_key = getattr(settings, key_map[provider], "") or ""
    if not api_key:
        return None
    return AsyncOpenAI(base_url=PROVIDERS[provider], api_key=api_key, timeout=45.0)


def load_cases(limit: int | None, tag_filter: str | None) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        for line in f:
            raw = json.loads(line.strip())
            tags = list(raw.get("tags") or [])
            if tag_filter and tag_filter not in tags:
                continue
            exp = raw["expected"]
            cases.append(
                GoldenCase(
                    id=raw["id"],
                    tags=tags,
                    puzzle=dict(raw["puzzle"]),
                    question=raw["question"],
                    expected_type=str(exp["type"]),
                    acceptable=[str(x) for x in exp.get("acceptable") or []],
                )
            )
    if limit:
        cases = cases[:limit]
    return cases


def score(actual: str, expected: str, acceptable: list[str]) -> float:
    if actual == expected or actual in acceptable or expected in acceptable:
        return 1.0
    if actual in ("yes", "key") and expected in ("yes", "key"):
        return 0.7
    return 0.0


async def ping(client: AsyncOpenAI, model: str) -> tuple[bool, int]:
    start = time.monotonic()
    try:
        await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=8,
        )
        return True, int((time.monotonic() - start) * 1000)
    except Exception:  # noqa: BLE001
        return False, int((time.monotonic() - start) * 1000)


async def judge_once(client: AsyncOpenAI, model: str, case: GoldenCase) -> tuple[str, int, bool]:
    system = build_judge_system_prompt(
        surface=case.puzzle["surface"],
        truth=case.puzzle["truth"],
        key_clues=list(case.puzzle.get("key_clues") or []),
        version="1.2",
    )
    start = time.monotonic()
    try:
        r = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"玩家问题：{case.question}"},
            ],
            max_tokens=128,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        ms = int((time.monotonic() - start) * 1000)
        data = json.loads((r.choices[0].message.content or "").strip())
        return str(data.get("type", "")), ms, True
    except Exception:  # noqa: BLE001
        return "", int((time.monotonic() - start) * 1000), False


async def eval_candidate(c: ModelCandidate, cases: list[GoldenCase]) -> ModelScore | None:
    client = get_client(c.provider)
    if client is None:
        return None

    ok, ping_ms = await ping(client, c.model)
    if not ok:
        return None

    ms = ModelScore(candidate=c, ping_ms=ping_ms)
    strict = soft_sum = 0
    f1_sum = f1_n = 0
    latencies: list[int] = []
    for case in cases:
        actual, lat, jok = await judge_once(client, c.model, case)
        latencies.append(lat)
        sc = score(actual, case.expected_type, case.acceptable) if jok else 0.0
        soft_sum += sc
        if jok and actual == case.expected_type:
            strict += 1
        if "F1" in case.tags:
            f1_sum += sc
            f1_n += 1
        if sc < 1.0:
            ms.failures.append(f"{case.id}: {actual or 'ERR'}(期望{case.expected_type})")
        await asyncio.sleep(0.2)

    n = len(cases)
    ms.strict_acc = strict / n
    ms.soft_acc = soft_sum / n
    ms.f1_soft = f1_sum / f1_n if f1_n else 0.0
    latencies.sort()
    ms.latency_p50 = latencies[len(latencies) // 2]
    return ms


def print_report(scores: list[ModelScore]) -> None:
    baseline = next((s for s in scores if s.candidate.model == PRODUCTION_JUDGE_MODEL), scores[0])

    print("\n" + "=" * 80)
    print(" 判题质量（golden · prompt v1.2 · 仅可用候选）")
    print("=" * 80)
    print(f"{'模型':<28} {'Strict':>7} {'Soft':>7} {'F1':>7} {'P50':>6}  备注")
    print("-" * 80)
    for s in scores:
        tag = "← 生产" if s.candidate.model == PRODUCTION_JUDGE_MODEL else ""
        if s.candidate.model != PRODUCTION_JUDGE_MODEL and baseline:
            d = s.soft_acc - baseline.soft_acc
            if d > 0.03:
                tag = f"↑ Soft {d:+.1%}"
            elif d < -0.03:
                tag = f"↓ Soft {d:+.1%}"
        print(
            f"{s.candidate.label:<28} {s.strict_acc:>6.1%} {s.soft_acc:>6.1%} "
            f"{s.f1_soft:>6.1%} {s.latency_p50:>5}ms  {tag}"
        )

    prod = next((s for s in scores if s.candidate.model == PRODUCTION_JUDGE_MODEL), None)
    if prod and prod.failures:
        print("\n生产模型未满分样例（前 5）:")
        for f in prod.failures[:5]:
            print(f"  · {f}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--tags", type=str, default=None)
    args = parser.parse_args()

    cases = load_cases(args.limit, args.tags)
    print(f"[compare] {len(cases)} cases · 候选 {len(meaningful_candidates())} 个")

    scores: list[ModelScore] = []
    for c in meaningful_candidates():
        result = await eval_candidate(c, cases)
        if result is not None:
            scores.append(result)

    if not scores:
        print("无可用模型（检查 Key 或网络）")
        return
    print_report(scores)


if __name__ == "__main__":
    asyncio.run(main())
