"""深度对比测试：glm-4-flashx vs glm-4-flash-250414

测试维度：
1. 海龟汤判定（多种问题类型：yes/no/irrelevant/key/claim）
2. 海龟汤出题能力（JSON 结构化 + 创意质量）
3. 趣味问答出题
4. 延迟稳定性（5 轮取中位数）

用法：
    uv run --no-sync python scripts/compare_models.py
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Windows UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from openai import AsyncOpenAI  # noqa: E402
from src.settings import get_settings  # noqa: E402

# ============ 配置 ============
MODELS = ["glm-4-flashx", "glm-4-flash-250414"]


def get_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key=settings.zhipu_api_key,
        timeout=30.0,
    )


# ============ 测试用例 ============

# 海龟汤判定场景
JUDGE_SYSTEM = """你是海龟汤汤主，根据以下信息判定玩家问题。

【汤面】深夜的咖啡馆里，陈默点了两杯美式。他只喝了一杯，然后对着第二杯哭了整整一小时，最后笑着离开了。
【汤底】陈默的父亲生前最爱这家咖啡馆的美式，每年父亲忌日他都会来店里点两杯——一杯自己喝，一杯放在对面，仿佛父亲还坐在那里。今年他在店里翻看着手机里父亲生前拍的照片，想起小时候父亲总偷偷把糖分给他，忍不住哭了很久。哭完后他意识到自己已经能笑着回忆父亲的温柔了，于是释怀地笑着离开。
【关键线索】
  1. 陈默的父亲已经去世
  2. 今天是父亲的忌日
  3. 第二杯咖啡是点给已故父亲的
  4. 陈默在怀念父亲并完成情绪释怀

玩家提问后，你需要判定 type：
- yes: 问题的答案是肯定的
- no: 问题的答案是否定的
- irrelevant: 问题与故事无关或不重要
- key: 问题直接触及了关键线索
- claim_detected: 玩家试图猜测完整真相

只输出 JSON: {"type":"...","hint":"一句简短提示"}"""

# 测试问题及预期判定
JUDGE_CASES = [
    ("陈默是个男的吗？", "irrelevant", "与故事核心无关"),
    ("第二杯咖啡是给别人的吗？", "yes", "是的但不够具体"),
    ("陈默的父亲还活着吗？", "key", "直接触及关键线索#1"),
    ("他是不是失恋了才哭的？", "no", "不是失恋"),
    ("陈默是在喝毒药吗？", "no", "荒谬的猜测"),
    ("我猜陈默的父亲去世了，今天是忌日，第二杯是给父亲的", "claim_detected", "玩家猜出了真相"),
    ("他最后笑着离开是因为释怀了吗？", "key", "触及关键线索#4"),
]

# 海龟汤出题 prompt
GENERATE_SOUP_SYSTEM = """你是一个海龟汤出题专家。请生成一道海龟汤题目。

要求：
1. 汤面要有悬念和戏剧性
2. 汤底要合理但出人意料
3. 关键线索 3-5 条，从易到难
4. 难度 1-5

只输出 JSON:
{
  "title": "标题",
  "category": "温情/悬疑/日常/奇幻",
  "difficulty": 3,
  "surface": "汤面文字",
  "truth": "汤底真相",
  "key_clues": ["线索1", "线索2", "线索3"]
}"""

# 趣味问答出题 prompt
TRIVIA_SYSTEM = """你是一个趣味问答出题专家。请生成一道趣味知识问答。

要求：
1. 题目有趣但不太难
2. 答案简短明确
3. 提供 2-4 个答案别名（不同说法）
4. 提供 3-5 条递进式提示线索
5. 一句话趣味讲解

只输出 JSON:
{
  "question": "问题",
  "answer": "标准答案",
  "aliases": ["别名1", "别名2"],
  "clues": ["线索1(最模糊)", "线索2", "线索3(最明显)"],
  "explanation": "趣味讲解"
}"""


@dataclass
class TestResult:
    model: str
    test_name: str
    latency_ms: int
    content: str
    success: bool
    score: float = 0.0  # 0-1 质量评分
    note: str = ""


async def call_model(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    *,
    json_mode: bool = False,
    max_tokens: int = 256,
    temperature: float = 0.1,
) -> tuple[int, str, bool]:
    """返回 (延迟ms, 内容, 是否成功)"""
    start = time.monotonic()
    try:
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        completion = await client.chat.completions.create(**kwargs)
        latency = int((time.monotonic() - start) * 1000)
        content = (completion.choices[0].message.content or "").strip()
        return latency, content, True
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        return latency, str(e)[:200], False


def validate_json(content: str) -> tuple[bool, dict | None]:
    """尝试解析 JSON"""
    try:
        data = json.loads(content)
        return True, data
    except (json.JSONDecodeError, ValueError):
        return False, None


async def test_judge(client: AsyncOpenAI, model: str) -> list[TestResult]:
    """测试判定能力"""
    results = []
    for question, expected_type, desc in JUDGE_CASES:
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": question},
        ]
        latency, content, ok = await call_model(client, model, messages, json_mode=True)

        score = 0.0
        note = ""
        if ok:
            valid, data = validate_json(content)
            if valid and data:
                actual_type = data.get("type", "")
                if actual_type == expected_type:
                    score = 1.0
                    note = f"✓ {actual_type}"
                elif actual_type in ("yes", "key") and expected_type in ("yes", "key"):
                    # yes 和 key 有时边界模糊，给 0.7 分
                    score = 0.7
                    note = f"~ {actual_type}(期望{expected_type})"
                else:
                    score = 0.0
                    note = f"✗ {actual_type}(期望{expected_type})"
            else:
                note = "✗ JSON解析失败"
        else:
            note = f"✗ 调用失败"

        results.append(TestResult(
            model=model,
            test_name=f"判定: {question[:15]}...",
            latency_ms=latency,
            content=content[:80],
            success=ok,
            score=score,
            note=note,
        ))
        # 避免限速
        await asyncio.sleep(0.3)

    return results


async def test_generate_soup(client: AsyncOpenAI, model: str) -> TestResult:
    """测试出题能力"""
    messages = [
        {"role": "system", "content": GENERATE_SOUP_SYSTEM},
        {"role": "user", "content": "请出一道难度为3的温情类海龟汤"},
    ]
    latency, content, ok = await call_model(
        client, model, messages, json_mode=True, max_tokens=2048, temperature=0.9
    )

    score = 0.0
    note = ""
    if ok:
        valid, data = validate_json(content)
        if valid and data:
            # 评分：结构完整性
            required_keys = {"title", "category", "difficulty", "surface", "truth", "key_clues"}
            present = required_keys & set(data.keys())
            struct_score = len(present) / len(required_keys)

            # 内容质量：汤面长度、汤底长度、线索数量
            surface_len = len(data.get("surface", ""))
            truth_len = len(data.get("truth", ""))
            clues_count = len(data.get("key_clues", []))

            quality_score = min(1.0, (
                (0.3 if 30 < surface_len < 200 else 0.1) +
                (0.3 if 50 < truth_len < 500 else 0.1) +
                (0.4 if 3 <= clues_count <= 5 else 0.2)
            ))

            score = struct_score * 0.5 + quality_score * 0.5
            note = f"结构{struct_score:.0%} 质量{quality_score:.0%} 线索{clues_count}条 汤面{surface_len}字"
        else:
            note = "✗ JSON解析失败"
    else:
        note = "✗ 调用失败"

    return TestResult(
        model=model,
        test_name="出题: 海龟汤",
        latency_ms=latency,
        content=content[:120],
        success=ok,
        score=score,
        note=note,
    )


async def test_generate_trivia(client: AsyncOpenAI, model: str) -> TestResult:
    """测试趣味问答出题"""
    messages = [
        {"role": "system", "content": TRIVIA_SYSTEM},
        {"role": "user", "content": "请出一道关于动物的趣味问答"},
    ]
    latency, content, ok = await call_model(
        client, model, messages, json_mode=True, max_tokens=1024, temperature=0.9
    )

    score = 0.0
    note = ""
    if ok:
        valid, data = validate_json(content)
        if valid and data:
            required_keys = {"question", "answer", "aliases", "clues", "explanation"}
            present = required_keys & set(data.keys())
            struct_score = len(present) / len(required_keys)

            aliases_count = len(data.get("aliases", []))
            clues_count = len(data.get("clues", []))
            has_explanation = bool(data.get("explanation", "").strip())

            quality_score = min(1.0, (
                (0.3 if aliases_count >= 2 else 0.1) +
                (0.4 if 3 <= clues_count <= 5 else 0.2) +
                (0.3 if has_explanation else 0.0)
            ))

            score = struct_score * 0.5 + quality_score * 0.5
            note = f"结构{struct_score:.0%} 别名{aliases_count} 线索{clues_count} 讲解{'✓' if has_explanation else '✗'}"
        else:
            note = "✗ JSON解析失败"
    else:
        note = "✗ 调用失败"

    return TestResult(
        model=model,
        test_name="出题: 趣味问答",
        latency_ms=latency,
        content=content[:120],
        success=ok,
        score=score,
        note=note,
    )


async def test_latency_stability(client: AsyncOpenAI, model: str, rounds: int = 5) -> TestResult:
    """延迟稳定性测试"""
    latencies = []
    for _ in range(rounds):
        latency, _, ok = await call_model(
            client, model,
            [{"role": "user", "content": "你好"}],
            max_tokens=32,
        )
        if ok:
            latencies.append(latency)
        await asyncio.sleep(0.5)

    if not latencies:
        return TestResult(model=model, test_name="延迟稳定性", latency_ms=0,
                          content="", success=False, note="全部失败")

    avg = sum(latencies) // len(latencies)
    median = sorted(latencies)[len(latencies) // 2]
    spread = max(latencies) - min(latencies)
    stability = max(0, 1.0 - spread / (avg + 1))  # 波动越小分越高

    return TestResult(
        model=model,
        test_name="延迟稳定性",
        latency_ms=median,
        content=f"各轮: {latencies}",
        success=True,
        score=stability,
        note=f"中位{median}ms 均值{avg}ms 波动{spread}ms 稳定度{stability:.0%}",
    )


# ============ 主流程 ============
async def main() -> None:
    print("=" * 75)
    print(" 深度对比: glm-4-flashx vs glm-4-flash-250414")
    print("=" * 75)

    client = get_client()
    all_results: dict[str, list[TestResult]] = {m: [] for m in MODELS}

    for model in MODELS:
        print(f"\n{'─' * 75}")
        print(f" 测试模型: {model}")
        print(f"{'─' * 75}")

        # 1. 判定测试
        print("\n  [1/4] 海龟汤判定（7 道题）...")
        judge_results = await test_judge(client, model)
        all_results[model].extend(judge_results)
        for r in judge_results:
            print(f"    {r.note:30} {r.latency_ms:>5}ms")

        # 2. 出题测试
        print("\n  [2/4] 海龟汤出题...")
        soup_result = await test_generate_soup(client, model)
        all_results[model].append(soup_result)
        print(f"    {soup_result.note:50} {soup_result.latency_ms:>5}ms")

        # 3. 趣味问答出题
        print("\n  [3/4] 趣味问答出题...")
        trivia_result = await test_generate_trivia(client, model)
        all_results[model].append(trivia_result)
        print(f"    {trivia_result.note:50} {trivia_result.latency_ms:>5}ms")

        # 4. 延迟稳定性
        print("\n  [4/4] 延迟稳定性（5轮）...")
        latency_result = await test_latency_stability(client, model)
        all_results[model].append(latency_result)
        print(f"    {latency_result.note}")

        # 模型间间隔，避免限速
        await asyncio.sleep(1.0)

    # ============ 汇总 ============
    print("\n" + "=" * 75)
    print(" 综合对比")
    print("=" * 75)

    print(f"\n{'维度':<20} {'glm-4-flashx':>18} {'glm-4-flash-250414':>20}")
    print("-" * 60)

    for model in MODELS:
        results = all_results[model]

    # 按维度汇总
    for dim_name, filter_fn in [
        ("判定准确率", lambda r: "判定" in r.test_name),
        ("出题质量(汤)", lambda r: r.test_name == "出题: 海龟汤"),
        ("出题质量(问答)", lambda r: r.test_name == "出题: 趣味问答"),
        ("延迟稳定性", lambda r: r.test_name == "延迟稳定性"),
    ]:
        scores = []
        latencies = []
        for model in MODELS:
            matched = [r for r in all_results[model] if filter_fn(r)]
            if matched:
                avg_score = sum(r.score for r in matched) / len(matched)
                avg_lat = sum(r.latency_ms for r in matched) / len(matched)
                scores.append(avg_score)
                latencies.append(int(avg_lat))
            else:
                scores.append(0)
                latencies.append(0)

        s1, s2 = scores
        l1, l2 = latencies
        winner = "←" if s1 > s2 else ("→" if s2 > s1 else "=")
        print(f"{dim_name:<20} {s1:>6.0%} ({l1}ms) {winner:^5} {s2:>6.0%} ({l2}ms)")

    # 总分
    print("-" * 60)
    for model in MODELS:
        results = all_results[model]
        total_score = sum(r.score for r in results) / len(results) if results else 0
        avg_latency = sum(r.latency_ms for r in results if r.success) / max(1, sum(1 for r in results if r.success))
        print(f"  {model:30} 总分: {total_score:.0%}  平均延迟: {int(avg_latency)}ms")

    print("\n" + "=" * 75)
    print(" 结论")
    print("=" * 75)
    # 自动判断
    base_results = all_results[MODELS[0]]
    new_results = all_results[MODELS[1]]
    base_score = sum(r.score for r in base_results) / len(base_results) if base_results else 0
    new_score = sum(r.score for r in new_results) / len(new_results) if new_results else 0
    base_lat = sum(r.latency_ms for r in base_results if r.success) / max(1, sum(1 for r in base_results if r.success))
    new_lat = sum(r.latency_ms for r in new_results if r.success) / max(1, sum(1 for r in new_results if r.success))

    print(f"\n  {MODELS[0]:30} : 质量 {base_score:.0%}, 延迟 {int(base_lat)}ms")
    print(f"  {MODELS[1]:30} : 质量 {new_score:.0%}, 延迟 {int(new_lat)}ms")

    if new_score >= base_score and new_lat <= base_lat * 2:
        print(f"\n  → {MODELS[1]} 质量 ≥ 基准且延迟可接受，值得替换！")
    elif new_score >= base_score * 0.9 and new_lat <= base_lat * 1.5:
        print(f"\n  → {MODELS[1]} 质量接近基准且延迟合理，可以考虑替换。")
    elif new_score > base_score:
        print(f"\n  → {MODELS[1]} 质量更好但延迟高 {new_lat/base_lat:.1f}x，视场景决定。")
    else:
        print(f"\n  → {MODELS[0]} 综合更优，建议维持现状。")


if __name__ == "__main__":
    asyncio.run(main())
