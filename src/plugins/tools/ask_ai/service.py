"""AI 助手兼容入口：Bot 和 CLI 共用同一编排逻辑。"""

from __future__ import annotations

from .models import AskResult, AssistantInput
from .orchestrator import answer


async def answer_question(question: str) -> AskResult:
    """兼容旧调用点；新代码应优先传 ``AssistantInput``。"""
    return await answer(AssistantInput(text=question))


__all__ = ["AskResult", "AssistantInput", "answer", "answer_question"]
