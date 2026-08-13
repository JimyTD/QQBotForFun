"""CLI 测试器对接「ai / 查资料」。逻辑走 ask_ai.service，与 Bot 一致。"""

from __future__ import annotations

from cli_adapters.base import C, GameMode, box, info, prompt


class WebSearchCLIAdapter:
    """查资料（搜索优先）的 CLI 包装。"""

    game_name = "🔍 AI"

    MODES: list[GameMode] = [
        GameMode(
            id="default",
            name="AI / 查资料",
            description="ai 起手，后面的话按助手来答",
            aliases=("查资料", "搜索", "search", "ai", "default"),
        ),
    ]

    def __init__(self, *, debug: bool = False) -> None:
        self.debug = debug
        self._query: str = ""

    async def start(self, mode_id: str) -> None:
        info("输入你想问的问题（输入 quit 退出）：")
        self._query = prompt("问题> ")
        if self._query.lower() in ("quit", "exit", "q"):
            self._query = ""

    async def play(self) -> None:
        if not self._query:
            info("未输入问题，已跳过。")
            return

        from src.plugins.tools.ask_ai.service import answer_question

        info(f"正在查: {self._query} ...")
        result = await answer_question(self._query)
        if not result.answer:
            print(f"{C.RED}AI 没有返回有效回答。{C.R}")
            return

        body = result.answer
        if result.sources:
            body += "\n\n📎 来源：\n" + "\n".join(result.sources)
        if not result.used_search:
            body += "\n\n（未联网，仅凭已有知识）"
        box("🔍 AI", body, color=C.CYAN)
