"""CLI 测试器对接 "游戏王查卡" 小工具。

注意：严格讲 yugioh_card 不是游戏（无对局、无状态机），只是为了复用
play_cli.py 的统一入口 UI，把它包装成一个 "伪游戏"：只有一个 default 模式。

CLI 特殊行为（来自 docs/tools/yugioh-card.md §7）：
- 不显示真卡图（终端不支持），只在末尾提示图片 URL
- 其余文案与 Bot 完全一致
"""

from __future__ import annotations

from cli_adapters.base import C, GameMode, box, info, prompt


class YugiohCardCLIAdapter:
    """游戏王查卡 CLI 包装。"""

    game_name = "🃏 游戏王查卡"

    MODES: list[GameMode] = [
        GameMode(
            id="default",
            name="查卡 / 随机卡",
            description="输入卡名或密码查询游戏王卡片",
            aliases=("查卡", "ygo", "default"),
        ),
    ]

    def __init__(self, *, debug: bool = False) -> None:
        self.debug = debug

    async def start(self, mode_id: str) -> None:
        """无需初始化，直接进入交互。"""
        pass

    async def play(self) -> None:
        """交互循环：持续接受查卡请求直到用户退出。"""
        from src.plugins.tools.yugioh_card.api import (
            random_card,
            search_by_id,
            search_by_name,
        )
        from src.plugins.tools.yugioh_card.render import (
            format_card_text,
            format_not_found,
        )

        info("输入卡名搜索，#密码 精确查，'随机' 随机一张，'quit' 退出")
        print()

        while True:
            user_input = prompt("查卡> ")
            if user_input.lower() in ("quit", "exit", "q", "退出", "结束"):
                info("再见，决斗者！")
                break

            if not user_input:
                continue

            # 随机卡
            if user_input in ("随机", "随机卡", "random"):
                card = await random_card()
                if card is None:
                    print(f"{C.RED}⚠️ 随机卡片获取失败，请检查网络。{C.R}")
                    continue
                body = "\n".join(format_card_text(card))
                if card.image_url_small:
                    body += f"\n\n{C.DIM}🖼️ 卡图: {card.image_url_small}{C.R}"
                box(f"🃏 {card.name}", body, color=C.MAG)
                continue

            # 按密码查询
            if user_input.startswith("#") or user_input.startswith("＃"):
                passcode_str = user_input[1:].strip()
                try:
                    passcode = int(passcode_str)
                except ValueError:
                    print(f"{C.RED}⚠️ 密码格式不对，应为纯数字。{C.R}")
                    continue

                card = await search_by_id(passcode)
                if card is None:
                    body = "\n".join(format_not_found(user_input))
                    box("🃏 查卡", body, color=C.RED)
                    continue

                body = "\n".join(format_card_text(card))
                if card.image_url_small:
                    body += f"\n\n{C.DIM}🖼️ 卡图: {card.image_url_small}{C.R}"
                box(f"🃏 {card.name}", body, color=C.MAG)
                continue

            # 按卡名模糊搜索
            cards = await search_by_name(user_input)
            if not cards:
                body = "\n".join(format_not_found(user_input))
                box("🃏 查卡", body, color=C.RED)
                continue

            card = cards[0]
            lines = format_card_text(card)
            if len(cards) > 1:
                lines.append("")
                lines.append(
                    f"共找到 {len(cards)} 张相关卡片，已展示第 1 张。"
                )

            body = "\n".join(lines)
            if card.image_url_small:
                body += f"\n\n{C.DIM}🖼️ 卡图: {card.image_url_small}{C.R}"
            box(f"🃏 {card.name}", body, color=C.MAG)
