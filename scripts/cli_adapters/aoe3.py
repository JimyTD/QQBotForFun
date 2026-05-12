"""AoE3 百科 CLI 适配器。"""

from __future__ import annotations

import sys
from pathlib import Path

from cli_adapters.base import GameCLIAdapter, GameMode, box, C, info, prompt

# 确保能 import src
_root = Path(__file__).resolve().parent.parent / "src"
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from plugins.aoe3.repository import UnitRepo  # noqa: E402
from plugins.aoe3.formatter import (  # noqa: E402
    render_unit_card,
    render_compare,
    render_counter_list,
    render_civ_units,
)


class AoE3CLIAdapter:
    """帝国时代3百科 — CLI 查询工具。"""

    game_name = "帝国时代3百科"
    MODES = [GameMode(id="default", name="兵种查询", description="查兵种属性/对比/克制/文明")]

    def __init__(self, *, debug: bool = False) -> None:
        self._debug = debug
        self._repo: UnitRepo | None = None

    async def start(self, mode_id: str) -> None:
        self._repo = UnitRepo.get()
        info(f"已加载 {len(self._repo.all_units)} 个兵种数据")

    async def play(self) -> None:
        assert self._repo is not None
        repo = self._repo

        box(
            "帝国时代3百科 🏰",
            "指令：\n"
            "  <兵种名>          — 查属性卡\n"
            "  对比 <A> <B>      — 两兵种对比\n"
            "  克制 <类型>       — 什么克制该类型\n"
            "  文明 <文明名>     — 该文明兵种列表\n"
            "  quit / exit       — 退出",
        )

        while True:
            text = prompt("\n🔍 查询").strip()
            if not text:
                continue
            if text.lower() in ("quit", "exit", "q", "退出"):
                info("再见！")
                break

            # ── 对比 ──
            if text.startswith("对比"):
                parts = text[2:].strip().split()
                if len(parts) < 2:
                    info("用法：对比 <兵种A> <兵种B>")
                    continue
                a_list = repo.search(parts[0], limit=1)
                b_list = repo.search(parts[1], limit=1)
                if not a_list:
                    info(f"未找到「{parts[0]}」")
                    continue
                if not b_list:
                    info(f"未找到「{parts[1]}」")
                    continue
                print(render_compare(a_list[0], b_list[0]))
                continue

            # ── 克制 ──
            if text.startswith("克制"):
                target = text[2:].strip()
                if not target:
                    info("用法：克制 <类型>，如：克制 骑兵")
                    continue
                results = repo.find_counters(target)
                print(render_counter_list(results, target))
                continue

            # ── 文明 ──
            if text.startswith("文明"):
                civ = text[2:].strip()
                if not civ:
                    info("用法：文明 <名称>，如：文明 日本")
                    continue
                units = repo.list_by_civ(civ)
                print(render_civ_units(units, civ))
                continue

            # ── 兵种查询 ──
            results = repo.search(text)
            if not results:
                info(f"未找到「{text}」相关兵种。")
                continue

            unit = results[0]

            # icon 路径
            icon_path = repo.get_icon_path(unit)
            if icon_path:
                print(f"{C.DIM}[icon: {icon_path}]{C.RESET}")

            print(render_unit_card(unit))

            if len(results) > 1:
                others = "、".join(
                    r.name if r.name != r.name_en else r.name_en
                    for r in results[1:4]
                )
                info(f"你可能还想查：{others}")

    async def post_game_prompt(self) -> None:
        pass
