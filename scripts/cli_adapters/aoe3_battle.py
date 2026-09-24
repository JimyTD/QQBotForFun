"""AoE3 斗蛐蛐 CLI 适配器。

MODES 定义在此（押注 / 国战 / 单挑 / 乱斗 / 王中王 / 王中王锦标赛）。
CLI 流程：
- 开局 → 生成阵容 → 展示面板 → 模拟押注 → 跑模拟 → 播报 → 战报
"""

from __future__ import annotations

import random

from cli_adapters.base import C, GameMode, info, prompt
from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.battle_contract import BattleResult
from plugins.games.aoe3_battle.broadcaster import (
    format_battle_report,
)
from plugins.games.aoe3_battle.civ_war_civs import pick_random_civs, resolve_civ
from plugins.games.aoe3_battle.civ_war_matchup import generate_civ_war_lineup
from plugins.games.aoe3_battle.game import AGE_DEFAULT
from plugins.games.aoe3_battle.lineup import (
    MatchLineup,
    _unit_cost,
    approx_lcm_budget,
    format_side_panel,
    format_vs_banner,
    generate_bet_lineup,
    generate_blacklist_lineup,
    generate_custom_lineup,
    generate_duel_lineup,
    generate_rival_lineup,
    generate_tournament_lineup,
)
from plugins.games.aoe3_battle.rival_themes import (
    pick_random_themes,
    resolve_theme,
)
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D
from plugins.games.aoe3_battle.tournament import Tournament, TournamentStage

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
        aliases=("单挑",),
    ),
    GameMode(
        id="blacklist",
        name="乱斗模式",
        description="怪物 / 战役英雄 / 作弊码兵互殴，战力分平衡",
        aliases=("乱斗",),
    ),
    GameMode(
        id="civ_war",
        name="国战",
        description="文明战术编制对决",
        aliases=("国战",),
    ),
    GameMode(
        id="custom",
        name="指定兵种对决",
        description="指定 1~2 种兵对决，相同资源",
        aliases=(),
    ),
    GameMode(
        id="rival",
        name="王中王",
        description="职能主题对决 · 表情选主题或指定主题",
        aliases=("王中王",),
    ),
    GameMode(
        id="rival_tournament",
        name="王中王锦标赛",
        description="8 兵种单败淘汰锦标赛",
        aliases=("锦标赛", "王中王锦标赛"),
    ),
]


class AoE3BattleCLIAdapter:
    """帝国3斗蛐蛐 — CLI 适配器。"""

    game_name = "帝国3斗蛐蛐 ⚔️"
    MODES = MODES

    def __init__(self, *, debug: bool = False) -> None:
        self._debug = debug
        self._mode_id = "bet"
        self._budget = 10000
        self._repo: UnitRepo | None = None
        self._match: MatchLineup | None = None
        self._result: BattleResult | None = None
        self._tournament: Tournament | None = None
        self._tournament_bets: dict[str, int] = {}

    async def start(self, mode_id: str) -> None:
        self._mode_id = mode_id
        self._repo = UnitRepo.get()
        info(f"已加载 {len(self._repo.all_units)} 个兵种数据")

        # 押注模式支持自定义预算
        if mode_id == "bet":
            budget_str = prompt("资源预算（直接回车默认 10000，范围 1000~50000）> ").strip()
            if budget_str.isdigit():
                self._budget = max(1000, min(50000, int(budget_str)))
            info(f"本局资源预算：{self._budget}")

        # 国战：随机文明或指定两个文明
        if mode_id == "civ_war":
            civ_text = prompt("文明（留空随机，或输入两个文明，如：英国 日本）> ").strip()
            if civ_text:
                tokens = civ_text.split()
                if len(tokens) != 2:
                    info("国战必须留空随机，或输入两个文明")
                    return
                profiles = [resolve_civ(token) for token in tokens]
                if any(profile is None for profile in profiles):
                    info("存在无法识别的文明")
                    return
                red_civ, blue_civ = profiles
                assert red_civ is not None and blue_civ is not None
                if red_civ.id == blue_civ.id:
                    info("国战双方必须是不同文明")
                    return
            else:
                red_civ, blue_civ = pick_random_civs()
            budget_str = prompt("资源预算（直接回车默认 10000）> ").strip()
            if budget_str.isdigit():
                self._budget = max(1000, min(50000, int(budget_str)))
            self._match, _ = generate_civ_war_lineup(
                self._repo,
                red_civ.id,
                blue_civ.id,
                budget=self._budget,
                age=AGE_DEFAULT,
                rng=random.Random(),
            )
            return

        # 指定兵种对决：让玩家输入兵种名
        if mode_id == "custom":
            info("指定兵种对决：输入 1~2 个兵种名（空格分隔）")
            names_str = prompt("兵种名（如：火枪手 散兵）> ").strip()
            if not names_str:
                info("未输入兵种名，退出")
                return
            unit_names = names_str.split()
            if len(unit_names) > 2:
                info("⚠️ 最多选 2 个兵种，只取前 2 个")
                unit_names = unit_names[:2]

            budget_str = prompt("资源预算（直接回车默认 10000）> ").strip()
            if budget_str.isdigit():
                self._budget = max(1000, min(50000, int(budget_str)))
            info(f"本局资源预算：{self._budget}")

            result = generate_custom_lineup(
                self._repo,
                unit_names,
                budget=self._budget,
                age=AGE_DEFAULT,
                rng=random.Random(),
            )
            if isinstance(result, str):
                info(f"生成失败：{result}")
                return
            self._match = result
            return

        if mode_id == "rival":
            options = pick_random_themes(count=3)
            info("王中王 · 随机 3 主题，请选一个：")
            for i, t in enumerate(options, start=1):
                info(f"  {i}. {t.title}")
            choice = prompt("输入 1/2/3（或主题名直接指定）> ").strip()
            theme = resolve_theme(choice)
            if theme is None and choice in ("1", "2", "3"):
                idx = int(choice) - 1
                if idx < len(options):
                    theme = options[idx]
            if theme is None:
                info("未选择有效主题，退出")
                return
            budget_str = prompt("资源预算（直接回车默认 10000）> ").strip()
            if budget_str.isdigit():
                self._budget = max(1000, min(50000, int(budget_str)))
            result = generate_rival_lineup(
                self._repo,
                theme.id,
                budget=self._budget,
                age=AGE_DEFAULT,
                rng=random.Random(),
            )
            if isinstance(result, str):
                info(f"生成失败：{result}")
                return
            self._match = result
            return

        if mode_id == "rival_tournament":
            options = pick_random_themes(count=3)
            info("王中王锦标赛 · 随机 3 主题，请选一个：")
            for i, t in enumerate(options, start=1):
                info(f"  {i}. {t.title}")
            choice = prompt("输入 1/2/3（或主题名直接指定）> ").strip()
            theme = resolve_theme(choice)
            if theme is None and choice in ("1", "2", "3"):
                idx = int(choice) - 1
                if idx < len(options):
                    theme = options[idx]
            if theme is None:
                info("未选择有效主题，退出")
                return
            budget_str = prompt("资源预算（直接回车默认 10000）> ").strip()
            if budget_str.isdigit():
                self._budget = max(1000, min(50000, int(budget_str)))
            result = generate_tournament_lineup(
                self._repo,
                theme.id,
                age=AGE_DEFAULT,
                rng=random.Random(),
            )
            if isinstance(result, str):
                info(f"生成失败：{result}")
                return
            self._tournament = Tournament.create(
                result,
                theme.title,
                age=AGE_DEFAULT,
                rng=random.Random(),
            )
            return

        # 生成阵容
        # 时代: 与线上默认一致 (game.AGE_DEFAULT, §3.10.6); 乱斗线上不启用时代
        rng = random.Random()
        if mode_id == "duel":
            self._match = generate_duel_lineup(self._repo, age=AGE_DEFAULT, rng=rng)
        elif mode_id == "blacklist":
            self._match = generate_blacklist_lineup(self._repo, rng=rng)
        else:
            self._match = generate_bet_lineup(
                self._repo, rng=rng, budget=self._budget, age=AGE_DEFAULT
            )

    async def play(self) -> None:
        if self._mode_id == "rival_tournament":
            await self._play_tournament()
            return

        assert self._match is not None

        match = self._match
        mode = self._mode_id

        # 1. 展示红方详情
        red_panel = format_side_panel(match.red, "red", mode, opponent=match.blue)
        print(f"\n{C.RED}{C.B}{'━' * 40}{C.R}")
        print(f"{C.RED}{red_panel}{C.R}")

        # 2. 展示蓝方详情
        blue_panel = format_side_panel(match.blue, "blue", mode, opponent=match.red)
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
        sim = BattleSimulator2D(
            red_army=[(s.unit, s.count) for s in match.red.slots],
            blue_army=[(s.unit, s.count) for s in match.blue.slots],
            duel_mode=is_duel,
            session_id="cli",
        )
        result = sim.run()
        self._result = result

        # 4. 最终战报；正式逐窗口播报与 brief/detailed 开关已彻底删除
        report = format_battle_report(result)
        print(f"\n{C.B}{report}{C.R}")

        # 5. 押注结算（CLI 简化版）
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

    async def _play_tournament(self) -> None:
        """在 CLI 中驱动真实锦标赛状态机。"""
        assert self._tournament is not None
        t = self._tournament

        print(f"\n{C.YEL}━━━ 王中王锦标赛 · {t.theme_title} ━━━{C.R}")
        print("参赛兵种：")
        for tu in t.units:
            print(f"  {tu.idx + 1}. {tu.display_name}")
        print(f"{C.DIM}输入 1-8 押注夺冠，开战开始，quit 退出。{C.R}")

        while True:
            text = prompt("押注/开战> ").strip().lower()
            if text in ("quit", "exit", "q", "退出"):
                info("已退出")
                return
            if text == "开战":
                break
            if text in tuple(str(i) for i in range(1, 9)):
                unit_idx = int(text) - 1
                if "CLI玩家" in self._tournament_bets:
                    print(f"{C.DIM}你已经押过了（锁死第一笔）{C.R}")
                    continue
                self._tournament_bets["CLI玩家"] = unit_idx
                print(f"{C.GRN}✅ 你押了 {unit_idx + 1}号 {t.get_unit(unit_idx).display_name} 夺冠{C.R}")
                continue
            print(f"{C.DIM}无效输入。1-8 / 开战 / quit{C.R}")

        # DRAW 是抽签完成后的等待态，第一轮开战需要显式推进。
        t.try_advance()

        while t.stage != TournamentStage.FINISHED:
            pending = t.get_current_round_matches()
            if not pending:
                if not t.try_advance():
                    raise RuntimeError(f"锦标赛在 {t.stage.value} 阶段无法推进")
                pending = t.get_current_round_matches()
            if not pending:
                continue

            print(f"\n{C.CYAN}━━━ {self._stage_label(t.stage)} ━━━{C.R}")
            for match in pending:
                self._run_tournament_match(t, match.match_id)
                t.try_advance()

            if t.stage in {
                TournamentStage.QF_DONE,
                TournamentStage.LOSERS_DONE,
                TournamentStage.SF_DONE,
                TournamentStage.THIRD_PLACE,
            }:
                if t.stage == TournamentStage.QF_DONE:
                    info("八强结束。输入「开战」进入排位赛与半决赛。")
                    self._wait_for_continue()
                elif t.stage == TournamentStage.LOSERS_DONE:
                    info("排位赛结束。输入「开战」进入半决赛。")
                    self._wait_for_continue()
                elif t.stage == TournamentStage.SF_DONE:
                    info("半决赛结束。输入「开战」进入季军战与决赛。")
                    self._wait_for_continue()
                t.try_advance()

        self._print_tournament_ranking(t)
        self._print_tournament_settlement(t)

    def _wait_for_continue(self) -> None:
        while True:
            text = prompt("开战> ").strip().lower()
            if text in ("quit", "exit", "q", "退出"):
                raise KeyboardInterrupt
            if text == "开战":
                return

    def _run_tournament_match(self, t: Tournament, match_id: str) -> None:
        """运行一场比赛并打印精简战报。"""
        match = t.matches[match_id]
        tu_a = t.get_unit(match.unit_a_idx)
        tu_b = t.get_unit(match.unit_b_idx)
        cost_a = max(1, _unit_cost(tu_a.unit))
        cost_b = max(1, _unit_cost(tu_b.unit))
        lcm_budget = approx_lcm_budget(cost_a, cost_b, self._budget)
        count_a = max(1, lcm_budget // cost_a)
        count_b = max(1, lcm_budget // cost_b)

        sim = BattleSimulator2D(
            red_army=[(tu_a.unit, count_a)],
            blue_army=[(tu_b.unit, count_b)],
            session_id=f"cli-tournament-{match_id}",
        )
        result = sim.run()
        if result.winner is None:
            winner_idx = random.choice([match.unit_a_idx, match.unit_b_idx])
        elif result.winner.value == "red":
            winner_idx = match.unit_a_idx
        else:
            winner_idx = match.unit_b_idx

        t.record_result(match_id, winner_idx)
        winner = t.get_unit(winner_idx)
        print(f"\n{C.B}{match.label}：{tu_a.display_name} vs {tu_b.display_name}{C.R}")
        print(f"  🔴 {tu_a.display_name} ×{count_a}  存活 {len(result.red_alive)}")
        print(f"  🔵 {tu_b.display_name} ×{count_b}  存活 {len(result.blue_alive)}")
        print(f"  {C.GRN}🏆 {winner.display_name} 胜{C.R}")

    @staticmethod
    def _stage_label(stage: TournamentStage) -> str:
        return {
            TournamentStage.QF: "八强战",
            TournamentStage.LOSERS: "败者组排位",
            TournamentStage.SF: "半决赛",
            TournamentStage.THIRD_PLACE: "季军战",
            TournamentStage.FINAL: "决赛",
        }.get(stage, stage.value)

    @staticmethod
    def _print_tournament_ranking(t: Tournament) -> None:
        print(f"\n{C.YEL}━━━ 最终排名 ━━━{C.R}")
        for rank, unit_idx in enumerate(t.final_ranks, start=1):
            print(f"  {rank}. {t.get_unit(unit_idx).display_name}")

    def _print_tournament_settlement(self, t: Tournament) -> None:
        if not self._tournament_bets:
            return
        champion_idx = t.final_ranks[0]
        champion_name = t.get_unit(champion_idx).display_name
        print(f"\n{C.YEL}━━━ 押注结算 ━━━{C.R}")
        print(f"🏆 冠军：{champion_name}")
        for name, unit_idx in self._tournament_bets.items():
            if unit_idx == champion_idx:
                print(f"  {C.GRN}{name}：押对了！🎉{C.R}")
            else:
                print(f"  {C.RED}{name}：押错了 😢{C.R}")

    async def post_game_prompt(self) -> None:
        pass
