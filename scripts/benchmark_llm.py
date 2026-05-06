"""LLM 模型可用性 & 延迟 & 稳定性测试

针对我们的供应商（智谱 / 龙猫）的多个模型，做三轮调用：
1. 简单 chat（"你好"）
2. JSON 判定场景（模拟 turtle_soup_judge）
3. 并发 3 次（模拟高频率场景看是否限速）

输出每个模型：
- 可用 / 不可用 + 错误码
- 平均延迟
- JSON 输出能力
- 是否触发 429 / 1302 / 1305

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

# Windows UTF-8
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


# ============ 测试矩阵 ============
@dataclass
class ModelSpec:
    provider: str       # zhipu / longcat
    model: str
    note: str = ""


MODELS: list[ModelSpec] = [
    # --- 智谱 ---
    ModelSpec("zhipu", "glm-4-flash", "老版永久免费，额度宽松"),
    ModelSpec("zhipu", "glm-4-flashx", "flash 增强版（当前主力）"),
    ModelSpec("zhipu", "glm-4-flash-250414", "2025-04 新版 flash，免费"),
    ModelSpec("zhipu", "glm-4.5-flash", "2026 年中版本"),
    ModelSpec("zhipu", "glm-4.7-flash", "2026-01 新版，30B 免费"),
    # --- 龙猫（美团） ---
    ModelSpec("longcat", "LongCat-Flash-Chat", "通用对话，500万tokens/天免费"),
    ModelSpec("longcat", "LongCat-Flash-Lite", "轻量MoE，5000万tokens/天免费"),
]


# ============ 简单 API 配置 ============
PROVIDERS = {
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
    },
    "longcat": {
        "base_url": "https://api.longcat.chat/openai",
    },
}


def get_client(provider: str) -> AsyncOpenAI:
    settings = get_settings()
    key_map = {
        "zhipu": "zhipu_api_key",
        "longcat": "longcat_api_key",
    }
    key_attr = key_map[provider]
    api_key = getattr(settings, key_attr, "") or ""
    return AsyncOpenAI(
        base_url=PROVIDERS[provider]["base_url"],
        api_key=api_key,
        timeout=30.0,
    )


# ============ 三类测试 ============
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
        msg = str(e)
        # 提取关键错误码
        for code in ("1301", "1302", "1303", "1304", "1305", "429", "401", "404", "400", "500", "503"):
            if code in msg:
                msg = f"[{code}] " + msg.split("'message':")[-1].split("'}")[0].strip(" '") if "'message'" in msg else f"[{code}] " + msg[:100]
                break
        else:
            msg = msg[:100]
        return Result(ok=False, latency_ms=latency, error=msg)


@dataclass
class ModelReport:
    spec: ModelSpec
    simple: Result = field(default_factory=Result)
    judge: Result = field(default_factory=Result)
    concurrent: list[Result] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.simple.ok:
            return "❌ 不可用"
        if not self.judge.ok:
            return "⚠️ 仅基础"
        ok_count = sum(1 for r in self.concurrent if r.ok)
        total = len(self.concurrent)
        if ok_count == total:
            return "✅ 稳定"
        if ok_count >= total // 2:
            return f"🟡 限速 ({ok_count}/{total})"
        return f"🔴 严重限速 ({ok_count}/{total})"

    @property
    def avg_latency(self) -> int:
        lats = [r.latency_ms for r in [self.simple, self.judge, *self.concurrent] if r.ok]
        return sum(lats) // len(lats) if lats else 0


async def test_model(spec: ModelSpec) -> ModelReport:
    print(f"\n  [test] {spec.provider:12} / {spec.model}")
    client = get_client(spec.provider)
    report = ModelReport(spec=spec)

    # 第 1 轮：简单
    report.simple = await call_once(client, spec.model, SIMPLE_MESSAGES)
    tag = "✓" if report.simple.ok else "✗"
    print(f"    [1] simple : {tag} {report.simple.latency_ms}ms "
          f"{report.simple.error or report.simple.content_sample[:50]}")
    if not report.simple.ok:
        return report

    # 第 2 轮：JSON 判定
    report.judge = await call_once(client, spec.model, JUDGE_MESSAGES, json_mode=True)
    tag = "✓" if report.judge.ok else "✗"
    print(f"    [2] judge  : {tag} {report.judge.latency_ms}ms "
          f"{report.judge.error or report.judge.content_sample[:50]}")

    # 第 3 轮：并发 3 次
    tasks = [call_once(client, spec.model, SIMPLE_MESSAGES) for _ in range(3)]
    report.concurrent = await asyncio.gather(*tasks)
    oks = sum(1 for r in report.concurrent if r.ok)
    print(f"    [3] concur : {oks}/3 ok")
    for i, r in enumerate(report.concurrent, 1):
        tag = "✓" if r.ok else "✗"
        print(f"          #{i} {tag} {r.latency_ms}ms {r.error[:60] if not r.ok else ''}")

    return report


# ============ 主流程 ============
async def main() -> None:
    print("=" * 70)
    print(" LLM 模型可用性全面测试")
    print("=" * 70)

    reports: list[ModelReport] = []
    for spec in MODELS:
        try:
            r = await test_model(spec)
            reports.append(r)
        except Exception as e:  # noqa: BLE001
            print(f"  [CRASH] {spec.model}: {e}")

    # 汇总表
    print("\n" + "=" * 70)
    print(" 汇总")
    print("=" * 70)
    header = f"{'状态':<14} {'供应商':<13} {'模型':<35} {'平均延迟':>8}  说明"
    print(header)
    print("-" * 100)
    for r in reports:
        print(
            f"{r.status:<14} "
            f"{r.spec.provider:<13} "
            f"{r.spec.model:<35} "
            f"{r.avg_latency:>6}ms  "
            f"{r.spec.note}"
        )

    # 推荐
    print("\n" + "=" * 70)
    print(" 推荐配置")
    print("=" * 70)
    stable = [r for r in reports if r.status.startswith("✅")]
    if not stable:
        print("  ⚠️ 没有 ✅ 稳定的模型，请检查 key / 网络")
    else:
        stable.sort(key=lambda r: r.avg_latency)
        print(f"  最快稳定模型: {stable[0].spec.provider} / {stable[0].spec.model} ({stable[0].avg_latency}ms)")
        print("  可用稳定模型（按延迟升序）:")
        for r in stable:
            print(f"    - {r.spec.provider:12} / {r.spec.model:35} {r.avg_latency:>5}ms")


if __name__ == "__main__":
    asyncio.run(main())
