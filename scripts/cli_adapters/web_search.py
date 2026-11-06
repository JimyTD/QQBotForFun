"""CLI 测试器对接 AI问答：与 Bot 共用同一编排逻辑。"""

from __future__ import annotations

from cli_adapters.base import C, GameMode, box, info, prompt


class WebSearchCLIAdapter:
    game_name = "🤖 AI问答"

    MODES: list[GameMode] = [
        GameMode(
            id="default",
            name="AI问答",
            description="问答、联网检索和图片搜索",
            aliases=("AI问答", "查资料", "搜索", "search", "ai", "default"),
        ),
    ]

    def __init__(self, *, debug: bool = False) -> None:
        self.debug = debug
        self._query = ""

    async def start(self, mode_id: str) -> None:
        info("输入问题（输入 quit 退出）：")
        self._query = prompt("问题> ")
        if self._query.lower() in ("quit", "exit", "q"):
            self._query = ""

    async def play(self) -> None:
        if not self._query:
            info("未输入问题，已跳过。")
            return

        from src.plugins.tools.ask_ai.models import AssistantInput
        from src.plugins.tools.ask_ai.orchestrator import answer

        info(f"AI 正在处理: {self._query} ...")
        result = await answer(AssistantInput(text=self._query))
        if result.images:
            body = result.image_caption
            if result.sources:
                body += "\n\n来源：" + "\n".join(result.sources)
            body += "\n\n（CLI 不显示图片，Bot 会发送实际图片）"
            box("🤖 AI问答", body, color=C.CYAN)
            return
        if not result.answer:
            print(f"{C.RED}{result.error or 'AI 没有返回有效回答。'}{C.R}")
            return
        body = result.answer
        if result.sources:
            body += "\n\n📎 来源：\n" + "\n".join(result.sources)
        if result.truncated:
            body += "\n\n（回答达到长度上限，可继续追问）"
        box("🤖 AI问答", body, color=C.CYAN)
