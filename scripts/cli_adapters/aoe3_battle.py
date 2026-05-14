"""AoE3 斗蛐蛐 CLI 适配器。

MODES 定义在此（首期两个模式：押注 / 单挑）。
CLI 流程：
- 开局 → 生成阵容 → 展示面板 → 模拟押注 → 跑模拟 → 播报 → 战报
"""

from __future__ import annotations

import asyncio
import random
import time

from cli_adapters.base import C, GameCLIAdapter, GameMode, box, info, prompt

from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.broadcaster import (
    Broadcaster,
    BroadcastSegment,
    format_battle_report,
)
from plugins.games.aoe3_battle.lineup import (
    MatchLineup,
    format_matchup_panel,
    format_side_panel,
    format_vs_banner,
    generate_bet_lineup,
    generate_duel_lineup,
)
from plugins.games.aoe3_battle.simulator import BattleResult, BattleSimulator, Side

# =====================================================================
# 模式定义
# =====================================================================
MODES = [
    GameMode(
        id="bet",
        name="押注模式",
        description="随机双方阵容，群殴对决",
        aliases=("押注", "斗蛐蛐", "默认"),
    ),
    GameMode(
        id="duel",
        name="单挑模式",
        description="随机两个兵种，真 1v1",
        aliases=("单挑", "1v1"),
    ),
]


class AoE3BattleCLIAdapter:
    """帝国3斗蛐蛐 — CLI 适配器。"""

    game_name = "帝国3斗蛐蛐 ⚔️"
    MODES = MODES

    def __init__(self, *, debug: bool = False) -> None:
        self._debug = debug
        self._mode_id = "bet"
        self._budget = 3000
        self._repo: UnitRepo | None = None
        self._match: MatchLineup | None = None
        self._result: BattleResult | None = None

    async def start(self, mode_id: str) -> None:
        self._mode_id = mode_id
        self._repo = UnitRepo.get()
        info(f"已加载 {len(self._repo.all_units)} 个兵种数据")

        # 押注模式支持自定义预算
        if mode_id == "bet":
            budget_str = prompt("资源预算（直接回车默认 3000，范围 1000~10000）> ").strip()
            if budget_str.isdigit():
                self._budget = max(1000, min(10000, int(budget_str)))
            info(f"本局资源预算：{self._budget}")

        # 生成阵容
        rng = random.Random()
        if mode_id == "duel":
            self._match = generate_duel_lineup(self._repo, rng=rng)
        else:
            self._match = generate_bet_lineup(self._repo, rng=rng, budget=self._budget)

    async def play(self) -> None:
        assert self._match is not None

        match = self._match
        mode = self._mode_id

        # 1. 展示红方详情
        red_panel = format_side_panel(match.red, "red", mode)
        print(f"\n{C.RED}{C.B}{'━' * 40}{C.R}")
        print(f"{C.RED}{red_panel}{C.R}")

        # 2. 展示蓝方详情
        blue_panel = format_side_panel(match.blue, "blue", mode)
        print(f"\n{C.BLUE}{C.B}{'━' * 40}{C.R}")
        print(f"{C.BLUE}{blue_panel}{C.R}")

        # 3. VS 总览
        vs = format_vs_banner(match)
        print(f"\n{C.CYAN}{C.B}{'━' * 40}{C.R}")
        print(f"{C.CYAN}{vs}{C.R}")
        print(f"{C.CYAN}{'━' * 40}{C.R}")

        # 2. 模拟押注阶段
        bets: dict[str, str] = {}  # player_name -> "red" | "blue"
        print(f"\n{C.YEL}━━━ 押注阶段 ━━━{C.R}")
        print(f"{C.DIM}输入 1（红方）/ 2（蓝方）/ 开战（跳过押注）{C.R}")

        while True:
            text = prompt("押注> ").strip()
            if not text:
                continue
            low = text.lower()

            if low in ("开战", "start", "go"):
                break
            if low in ("quit", "exit", "q", "退出"):
                info("已退出")
                return
            if low in ("1", "押1", "押注1"):
                if "CLI玩家" in bets:
                    print(f"{C.DIM}你已经押过了（锁死第一笔）{C.R}")
                else:
                    bets["CLI玩家"] = "red"
                    print(f"{C.RED}✅ 你押了 🔴 红方{C.R}")
                continue
            if low in ("2", "押2", "押注2"):
                if "CLI玩家" in bets:
                    print(f"{C.DIM}你已经押过了（锁死第一笔）{C.R}")
                else:
                    bets["CLI玩家"] = "blue"
                    print(f"{C.BLUE}✅ 你押了 🔵 蓝方{C.R}")
                continue
            print(f"{C.DIM}无效输入。1 / 2 / 开战{C.R}")

        # 3. 跑模拟
        print(f"\n{C.DIM}战斗模拟中...{C.R}")
        is_duel = self._mode_id == "duel"
        sim = BattleSimulator(
            red_army=[(s.unit, s.count) for s in match.red.slots],
            blue_army=[(s.unit, s.count) for s in match.blue.slots],
            duel_mode=is_duel,
        )
        result = sim.run()
        self._result = result

        # 4. 播报
        bc = Broadcaster(result)
        segments = bc.generate()

        print(f"\n{C.CYAN}{'━' * 50}{C.R}")
        for seg in segments:
            if seg.is_key_event:
                print(f"\n{C.B}{seg.text}{C.R}")
            else:
                print(f"\n{seg.text}")

            if seg.should_sleep:
                # CLI 模式用较短的 sleep（真实群消息用 2s）
                time.sleep(0.5 if not self._debug else 0.1)

        # 5. 最终战报
        report = format_battle_report(result)
        print(f"\n{C.B}{report}{C.R}")

        # 6. 押注结算（CLI 简化版）
        if bets:
            print(f"\n{C.YEL}━━━ 押注结算 ━━━{C.R}")
            winner_side = result.winner.value if result.winner else None
            for name, side in bets.items():
                if winner_side is None:
                    print(f"  {name}：平局，退还入场券")
                elif side == winner_side:
                    print(f"  {C.GRN}{name}：押对了！🎉{C.R}")
                else:
                    print(f"  {C.RED}{name}：押错了 😢{C.R}")
            print(f"{C.DIM}（CLI 模式不扣/发金币）{C.R}")

    async def post_game_prompt(self) -> None:
        pass
