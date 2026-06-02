"""经济天气 prompt 调试脚本。

模拟多种场景，每种跑2轮，方便对比 LLM 输出质量。

用法：
    uv run --no-sync python scripts/test_finance_prompt.py
"""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

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

import os
os.environ.setdefault("APP_ENV", "dev")

from src.plugins.tools.finance.prompts import FINANCE_REPORT_SYSTEM, FINANCE_REPORT_USER

SCENARIOS = {
    "异动+宏观": (
        "【今日异动】\n"
        "- A股·沪指: 跌了2.3%（平时日均波动约0.7%，今天超出正常范围）\n"
        "  生活影响：基金和养老账户可能受影响\n"
        "- 黄金: 涨了3.1%（平时日均波动约0.9%，今天超出正常范围）\n"
        "  生活影响：避险情绪有变化，跟国际局势可能相关\n"
        "【宏观数据更新】\n"
        "- CPI月率（物价涨跌）: 最新 0.4%，前值 -0.1%\n"
        "  通俗解读：物价从跌转涨，钱包要注意了"
    ),
    "仅最大波动": (
        "【今日关注】\n"
        "- A股·创业板: 涨了2.66%，今天各品类里动得最大\n"
        "  生活影响：科技成长股波动明显"
    ),
    "仅宏观": (
        "【宏观数据更新】\n"
        "- LPR利率（房贷利率）: 最新 2.85%，前值 3.0%\n"
        "  通俗解读：贷款利率降了，房贷月供能省点"
    ),
    "多品类异动": (
        "【今日异动】\n"
        "- 原油·WTI: 跌了5.2%（平时日均波动约1.8%，今天超出正常范围）\n"
        "  生活影响：油价波动可能影响出行和物流成本\n"
        "- 汇率·美元: 涨了1.1%（平时日均波动约0.2%，今天超出正常范围）\n"
        "  生活影响：人民币汇率变了，海淘和留学费用关注下"
    ),
}


async def main() -> None:
    from core import llm
    llm.init()

    for name, data in SCENARIOS.items():
        print(f"\n{'='*60}")
        print(f" 场景: {name}")
        print(f"{'='*60}")
        print(f"[输入数据]\n{data}\n")

        for i in range(1, 3):
            try:
                resp = await llm.chat(
                    messages=[
                        llm.LLMMessage(role="system", content=FINANCE_REPORT_SYSTEM),
                        llm.LLMMessage(
                            role="user",
                            content=FINANCE_REPORT_USER.format(structured_data=data),
                        ),
                    ],
                    scene="finance_report",
                    temperature=0.7,
                    max_tokens=512,
                )
                print(f"[第{i}轮] ({len(resp.content)}字, {resp.latency_ms}ms)")
                print(resp.content.strip())
                print()
            except Exception as e:
                print(f"[第{i}轮] 失败: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
