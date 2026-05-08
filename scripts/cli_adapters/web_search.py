"""CLI 测试器对接 "查资料"（搜索优先版）。

统一入口：查资料 / 搜索 合并为一个功能。
默认先联网搜索，搜索不可用或明显不需要时 fallback 到纯 LLM。

CLI 行为与 Bot 侧完全一致（铁律）。

本地测试需要：
- Searxng 服务运行（docker compose -f docker-compose.dev.yml up -d searxng）
- 或设置环境变量 SEARXNG_URL 指向可用实例
- 若 Searxng 不可用则自动 fallback 到纯 LLM
"""

from __future__ import annotations

import re

from cli_adapters.base import C, GameMode, box, info, prompt


# 与 Bot 侧一致的跳过搜索判断
_SKIP_SEARCH_PATTERNS = re.compile(
    r"^("
    r"\d[\d\s\+\-\*\/\.\(\)]*\d"
    r"|你好|hello|hi|嗨|早|晚安|谢谢"
    r"|你是谁|你叫什么"
    r")$",
    re.IGNORECASE,
)


def _should_skip_search(question: str) -> bool:
    q = question.strip()
    if len(q) <= 3 and not any("\u4e00" <= c <= "\u9fff" for c in q):
        return True
    return bool(_SKIP_SEARCH_PATTERNS.match(q))


class WebSearchCLIAdapter:
    """查资料（搜索优先）的 CLI 包装。"""

    game_name = "🔍 查资料"

    MODES: list[GameMode] = [
        GameMode(
            id="default",
            name="查资料 / 搜索",
            description="输入问题，优先联网搜索后由 AI 总结回答",
            aliases=("查资料", "搜索", "search", "ai", "default"),
        ),
    ]

    def __init__(self, *, debug: bool = False) -> None:
        self.debug = debug
        self._query: str = ""

    async def start(self, mode_id: str) -> None:
        """获取用户问题。"""
        info("输入你想查的问题（输入 quit 退出）：")
        self._query = prompt("问题> ")
        if self._query.lower() in ("quit", "exit", "q"):
            self._query = ""

    async def play(self) -> None:
        """搜索优先 → LLM 总结。"""
        if not self._query:
            info("未输入问题，已跳过。")
            return

        from src.plugins.tools.web_search.searxng import (
            format_results_for_llm,
            format_sources_for_user,
            search,
        )
        from core import llm

        used_search = False

        # 路径 1：搜索优先
        if not _should_skip_search(self._query):
            info(f"正在搜索: {self._query} ...")
            results = await search(self._query)

            if results:
                used_search = True
                if self.debug:
                    info(f"获取到 {len(results)} 条结果")

                search_context = format_results_for_llm(results)
                user_prompt = (
                    f"用户问题：{self._query}\n\n"
                    f"以下是网络搜索结果：\n\n{search_context}\n\n"
                    "请基于以上搜索结果回答用户的问题。"
                )

                system_prompt = (
                    "你是一个群聊助手，根据搜索结果回答用户的问题。\n"
                    "要求：\n"
                    "- 基于提供的搜索结果进行总结，不要编造信息\n"
                    "- 回答简洁明了，控制在 300 字以内\n"
                    "- 如果搜索结果无法回答问题，诚实说明\n"
                    "- 不要输出 Markdown 格式，用纯文本\n"
                    "- 语气轻松友好\n"
                    "- 不需要逐条引用来源编号"
                )

                try:
                    resp = await llm.chat(
                        messages=[
                            llm.LLMMessage(role="system", content=system_prompt),
                            llm.LLMMessage(role="user", content=user_prompt),
                        ],
                        scene="web_search",
                    )
                    answer = resp.content.strip()
                except Exception as e:  # noqa: BLE001
                    if self.debug:
                        info(f"LLM 总结失败: {e}")
                    snippets = [f"• {r.title}: {r.snippet}" for r in results[:3]]
                    answer = "\n".join(snippets)

                if not answer:
                    answer = "\n".join(f"• {r.title}: {r.snippet}" for r in results[:3])

                sources = format_sources_for_user(results)
                body = answer + "\n\n📎 来源：\n" + "\n".join(sources)
                box("🔍 查资料", body, color=C.CYAN)
                return
            else:
                info("搜索无结果，改用 AI 直接回答...")

        # 路径 2：纯 LLM fallback
        if not used_search:
            info("AI 直接回答中...")

        system_prompt = (
            "你是一个群聊助手，回答用户的问题。\n"
            "要求：\n"
            "- 回答简洁明了，控制在 300 字以内\n"
            "- 如果不确定答案，诚实说明\n"
            "- 不要输出 Markdown 格式，用纯文本\n"
            "- 语气轻松友好"
        )

        try:
            resp = await llm.chat(
                messages=[
                    llm.LLMMessage(role="system", content=system_prompt),
                    llm.LLMMessage(role="user", content=self._query),
                ],
                scene="ask_ai",
            )
            answer = resp.content.strip()
        except Exception as e:  # noqa: BLE001
            print(f"{C.RED}AI 回答失败: {e}{C.R}")
            return

        if not answer:
            print(f"{C.RED}AI 没有返回有效回答。{C.R}")
            return

        box("🔍 查资料", answer, color=C.CYAN)
