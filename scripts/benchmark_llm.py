"""LLM 生产模型 ping 测试。

仅测 config/llm.yaml 中在用的候选模型。
不可用或明显淘汰的模型不在此列表，避免无效对比。

用法：
    uv run --no-sync python scripts/benchmark_llm.py
"""

from __future__ import annotations

import asyncio
import io
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

from src.settings import get_settings  # noqa: E402


@dataclass
class ModelSpec:
    provider: str
    model: str
    role: str


def production_models() -> list[ModelSpec]:
    """与 llm.yaml 对齐的生产模型。"""
    return [
        ModelSpec("longcat", "LongCat-Flash-Chat", "海龟汤 judge/claim"),
        ModelSpec("longcat", "LongCat-Flash-Lite", "查资料 / 高额度"),
        ModelSpec("zhipu", "glm-4-flash-250414", "出题 / 兜底"),
    ]


PROVIDERS = {
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "longcat": "https://api.longcat.chat/openai",
}


def get_client(provider: str) -> AsyncOpenAI | None:
    settings = get_settings()
    key_map = {
        "zhipu": "zhipu_api_key",
        "longcat": "longcat_api_key",
    }
    api_key = getattr(settings, key_map[provider], "") or ""
    if not api_key or provider not in PROVIDERS:
        return None
    return AsyncOpenAI(base_url=PROVIDERS[provider], api_key=api_key, timeout=30.0)


SIMPLE_MESSAGES = [{"role": "user", "content": "你好"}]

JUDGE_SYSTEM = """你是海龟汤汤主，根据以下信息判定玩家问题。

【汤面】深夜咖啡馆，陈默点了两杯美式，只喝一杯，对着第二杯哭了一小时后笑着离开。
【汤底】陈默的父亲去世了，今天是忌日，第二杯咖啡是点给已故父亲的。
【关键线索】
  1. 陈默的父亲已经去世
  2. 今天是父亲的忌日

判定 type: yes / no / irrelevant / key / claim_detected。
只输出 JSON: {"type":"...","hint":"..."}"""

JUDGE_MESSAGES = [
    {"role": "system", "content": JUDGE_SYSTEM},
    {"role": "user", "content": "陈默的父亲已经去世了吗？"},
]


@dataclass
class Result:
    ok: bool = False
    latency_ms: int = 0
    error: str = ""
    content_sample: str = ""


async def call_once(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, str]],
    *,
    json_mode: bool = False,
) -> Result:
    start = time.monotonic()
    try:
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": 128,
            "temperature": 0.1,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        completion = await client.chat.completions.create(**kwargs)
        latency = int((time.monotonic() - start) * 1000)
        content = (completion.choices[0].message.content or "").strip()
        return Result(ok=True, latency_ms=latency, content_sample=content[:80])
    except Exception as e:  # noqa: BLE001
        latency = int((time.monotonic() - start) * 1000)
        return Result(ok=False, latency_ms=latency, error=str(e)[:100])


@dataclass
class ModelReport:
    spec: ModelSpec
    simple: Result = field(default_factory=Result)
    judge: Result = field(default_factory=Result)
    concurrent: list[Result] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.simple.ok and self.judge.ok and all(r.ok for r in self.concurrent)

    @property
    def avg_latency(self) -> int:
        lats = [r.latency_ms for r in [self.simple, self.judge, *self.concurrent] if r.ok]
        return sum(lats) // len(lats) if lats else 0


async def test_model(spec: ModelSpec) -> ModelReport | None:
    client = get_client(spec.provider)
    if client is None:
        return None

    report = ModelReport(spec=spec)
    report.simple = await call_once(client, spec.model, SIMPLE_MESSAGES)
    if not report.simple.ok:
        return None

    report.judge = await call_once(client, spec.model, JUDGE_MESSAGES, json_mode=True)
    if not report.judge.ok:
        return None

    report.concurrent = list(await asyncio.gather(*[
        call_once(client, spec.model, SIMPLE_MESSAGES) for _ in range(3)
    ]))
    if not all(r.ok for r in report.concurrent):
        return None

    print(f"  ✓ {spec.provider}/{spec.model} ({spec.role}) avg={report.avg_latency}ms")
    return report


async def main() -> None:
    print("=" * 60)
    print(" LLM 生产模型 ping（仅可用模型会出现在汇总）")
    print("=" * 60)

    reports: list[ModelReport] = []
    for spec in production_models():
        r = await test_model(spec)
        if r is not None:
            reports.append(r)

    print("\n" + "=" * 60)
    print(" 汇总")
    print("=" * 60)
    if not reports:
        print("  无可用模型，请检查 API Key / 网络")
        return

    reports.sort(key=lambda r: r.avg_latency)
    print(f"{'延迟':>8}  {'模型':<28}  {'用途'}")
    print("-" * 60)
    for r in reports:
        print(f"{r.avg_latency:>6}ms  {r.spec.model:<28}  {r.spec.role}")


if __name__ == "__main__":
    asyncio.run(main())
