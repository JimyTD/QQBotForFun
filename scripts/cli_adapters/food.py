"""CLI 测试器对接 "今天吃什么" 小工具。

注意：严格讲 food 不是游戏（无对局、无状态机），只是为了复用 play_cli.py
的统一入口 UI，把它包装成一个 "伪游戏"：只有一个 default 模式、一次性执行。

CLI 特殊行为（来自 docs/tools/food.md §5）：
- 不显示真图片（终端不支持），只在末尾提示图片路径
- 其余文案/抽菜结果与 Bot 完全一致
"""

from __future__ import annotations

from pathlib import Path

from cli_adapters.base import C, GameMode, box, info


_ROOT = Path(__file__).resolve().parents[2]


class FoodCLIAdapter:
    """一次性命令的 CLI 包装。"""

    game_name = "🍱 今天吃什么"

    # 只有一个 default 模式（伪造，为了满足 play_cli.py 的"选模式"流程）
    MODES: list[GameMode] = [
        GameMode(
            id="default",
            name="随便来一个",
            description="从库里随机抽一道菜",
            aliases=("随便", "any", "default"),
        ),
    ]

    def __init__(self, *, debug: bool = False) -> None:
        self.debug = debug
        self._picked = None  # 准备阶段就抽好，play() 只负责展示

    async def start(self, mode_id: str) -> None:
        """抽菜（等同于 bot 侧 /吃什么 命令触发时的行为）。"""
        # 延迟 import 避免 seed / 纯测试环境踩 NoneBot
        from src.plugins.tools.food.storage import pick_random

        self._picked = await pick_random()
        if self._picked is None:
            raise RuntimeError(
                "菜单空空如也。请先跑：uv run python scripts/seed_foods.py"
            )

    async def play(self) -> None:
        """展示结果，立即结束。"""
        food = self._picked
        assert food is not None  # start() 保证

        # 与 Bot 端展示对齐：标题 + 描述 + (图片或路径)
        body = food.description
        if food.image_path:
            abs_path = _ROOT / food.image_path
            if abs_path.exists():
                body += (
                    f"\n\n{C.DIM}📷 图片: {food.image_path} "
                    f"(CLI 不显示真图，Bot 端会发图){C.R}"
                )
            else:
                body += f"\n\n{C.DIM}📷 图片缺失: {food.image_path}{C.R}"
        else:
            body += f"\n\n{C.DIM}（这道菜暂无图片）{C.R}"

        box(f"🍱 今天吃：{food.name}", body, color=C.YEL)
        info("打开包装，请享用。")
