"""深海任务 CLI adapter。"""

from __future__ import annotations

import random

from src.plugins.games.deep_sea_mission.campaign import (
    ASG_ALL_ONE_CREW,
    ASG_CAPTAIN_ALL,
    ASG_CAPTAIN_NO_TASK,
    ASG_HARDEST_TO_CAPTAIN,
    ASG_SELF_NOMINATE_1,
    ASG_SELF_NOMINATE_2,
    MOD_FREE_SELECTION,
    Mission,
    fixed_tasks_m32,
    get_mission,
)
from src.plugins.games.deep_sea_mission.cards import (
    build_deck,
    deal,
    display_card,
    display_cards,
    legal_play,
    parse_card,
    sort_cards,
    suit_of,
    trick_winner,
)
from src.plugins.games.deep_sea_mission.game import DeepSeaMissionGame
from src.plugins.games.deep_sea_mission.rules import (
    evaluate_campaign_special,
    evaluate_tasks,
    mission_locked_win,
)

from .base import C, GameCLIAdapter, box, prompt


class DeepSeaMissionCLIAdapter(GameCLIAdapter):
    game_name = DeepSeaMissionGame.name
    MODES = DeepSeaMissionGame.MODES

    # 单次 CLI 运行内的战役进度（跨实例共享：play_cli「再来一局」会新建 adapter）。
    # 关掉 CLI 即失，不做持久化（docs/13 允许的机制差异）。
    _campaign_level = 1

    def __init__(self, *, debug: bool = False) -> None:
        self.debug = debug
        self.mode_id = "mission"
        self.players = [1, 2, 3]
        self.names = {1: "P1", 2: "P2", 3: "P3"}
        self.hands: dict[str, list[str]] = {}
        self.tasks: list[dict] = []
        self.order = list(self.players)
        self.current = 1
        self.captain = 1
        self.trick_no = 1
        self.current_trick: list[dict[str, int | str]] = []
        self.trick_history: list[dict] = []
        self.lead_suit: str | None = None
        self.mission: Mission | None = None

    async def start(self, mode_id: str) -> None:
        self.mode_id = mode_id
        n = prompt("玩家人数 3-5（默认 3）> ").strip()
        if n:
            count = int(n)
            if count < 3 or count > 5:
                raise ValueError("玩家人数必须是 3-5")
            self.players = list(range(1, count + 1))
            self.names = {p: f"P{p}" for p in self.players}
            self.order = list(self.players)
        rng = random.Random()
        deck = build_deck(rng)
        self.hands = deal(deck, self.players)
        self.captain = next(int(pid) for pid, hand in self.hands.items() if "sub:4" in hand)
        self.current = self.captain

        if mode_id == "campaign":
            mission_no = type(self)._campaign_level
            mission = get_mission(mission_no)
            self.mission = mission
            if mission.task_source == "draw":
                self.tasks = draw_tasks(mission.difficulty, len(self.players), rng)
            elif mission.task_source == "fixed":
                self.tasks = fixed_tasks_m32(len(self.players))
            else:
                self.tasks = []
            self._apply_auto_assignment(mission)
        else:
            d = prompt("任务总难度（默认 3）> ").strip()
            difficulty = int(d) if d else 3
            self.tasks = draw_tasks(difficulty, len(self.players), rng)

    def _apply_auto_assignment(self, mission: Mission) -> None:
        if mission.assignment == ASG_CAPTAIN_ALL:
            for t in self.tasks:
                t["assigned_to"] = self.captain
        elif mission.assignment == ASG_HARDEST_TO_CAPTAIN and self.tasks:
            hardest = max(range(len(self.tasks)), key=lambda i: int(self.tasks[i]["difficulty"]))
            self.tasks[hardest]["assigned_to"] = self.captain

    def _campaign_header(self) -> str:
        if not self.mission:
            return ""
        no = self.mission.no
        diff = self.mission.difficulty
        title = f"第 {no} 关" if no else "Epilogue"
        if diff:
            title += f" · 难度 {diff}"
        parts = [f"🏁 战役 {title}"]
        if self.mission.special:
            parts.append(f"⚡ 特殊：{self.mission.special}")
        if self.mission.note:
            parts.append(f"📌 {self.mission.note}")
        return "\n".join(parts)

    async def play(self) -> None:
        header = self._campaign_header()
        lines: list[str] = []
        if header:
            lines.append(header)
        lines += [
            f"队长：{self.names[self.captain]}",
            "",
            *[f"{self.names[p]} 手牌：{display_cards(self.hands[str(p)])}" for p in self.players],
        ]
        if self.tasks:
            lines += ["", "任务：", *self._task_lines()]
        else:
            lines += ["", "（本关无任务卡，直接出牌）"]
        box("深海任务 · 发牌", "\n".join(lines), C.BLUE)
        if self.tasks:
            await self._select_tasks()
        await self._play_cards()

    async def _select_tasks(self) -> None:
        mission = self.mission
        if mission and mission.assignment in {
            ASG_ALL_ONE_CREW,
            ASG_SELF_NOMINATE_1,
            ASG_SELF_NOMINATE_2,
        }:
            await self._nominate()
            return
        free = bool(mission and MOD_FREE_SELECTION in mission.modifiers)
        selector_index = self.order.index(self.captain)
        if mission and mission.assignment == ASG_CAPTAIN_NO_TASK:
            selector_index = (selector_index + 1) % len(self.order)
        while any(t["assigned_to"] is None for t in self.tasks):
            player = self.order[selector_index]
            print("\n".join(self._task_lines()))
            tag = "自由选任务" if free else f"{self.names[player]} 选任务"
            text = prompt(f"{tag}（如 1；pass 跳过）> ")
            if text.lower() in {"pass", "过"}:
                if not free:
                    selector_index = (selector_index + 1) % len(self.order)
                continue
            try:
                idx = int(text) - 1
            except ValueError:
                print(f"{C.RED}无效任务。{C.R}")
                continue
            if idx < 0 or idx >= len(self.tasks) or self.tasks[idx]["assigned_to"] is not None:
                print(f"{C.RED}无效任务。{C.R}")
                continue
            self.tasks[idx]["assigned_to"] = player
            if not free:
                selector_index = (selector_index + 1) % len(self.order)

    async def _nominate(self) -> None:
        assert self.mission is not None
        target = 2 if self.mission.assignment == ASG_SELF_NOMINATE_2 else 1
        fallback = self.mission.assignment != ASG_ALL_ONE_CREW
        order = self.order
        start = order.index(self.captain)
        turn = start
        nominees: list[int] = []
        while len(nominees) < target:
            player = order[turn]
            text = prompt(f"{self.names[player]} 是否包揽全部任务？(y/包揽 / n/过) > ").strip().lower()
            if text in {"y", "yes", "包揽", "我来"}:
                nominees.append(player)
                print(f"{C.GRN}{self.names[player]} 包揽。{C.R}")
            turn = (turn + 1) % len(order)
            if turn == start and len(nominees) == 0:
                if fallback:
                    print(f"{C.RED}无人包揽，退回轮流选。{C.R}")
                    await self._select_tasks_normal()
                    return
                print(f"{C.RED}本关必须有船员包揽，继续表态。{C.R}")
        if len(nominees) == 1:
            for t in self.tasks:
                t["assigned_to"] = nominees[0]
        else:
            first, second = nominees
            dup = [dict(t) for t in self.tasks]
            for t in self.tasks:
                t["assigned_to"] = first
            for t in dup:
                t["assigned_to"] = second
            self.tasks = self.tasks + dup

    async def _select_tasks_normal(self) -> None:
        selector_index = self.order.index(self.captain)
        while any(t["assigned_to"] is None for t in self.tasks):
            player = self.order[selector_index]
            print("\n".join(self._task_lines()))
            text = prompt(f"{self.names[player]} 选任务（如 1；pass 跳过）> ")
            if text.lower() in {"pass", "过"}:
                selector_index = (selector_index + 1) % len(self.order)
                continue
            try:
                idx = int(text) - 1
            except ValueError:
                print(f"{C.RED}无效任务。{C.R}")
                continue
            if idx < 0 or idx >= len(self.tasks) or self.tasks[idx]["assigned_to"] is not None:
                print(f"{C.RED}无效任务。{C.R}")
                continue
            self.tasks[idx]["assigned_to"] = player
            selector_index = (selector_index + 1) % len(self.order)

    async def _play_cards(self) -> None:
        box("深海任务 · 开始", "\n".join(self._task_lines()), C.CYAN)
        while any(self.hands[str(p)] for p in self.players):
            hand = self.hands[str(self.current)]
            print(f"\n第 {self.trick_no} 墩，轮到 {self.names[self.current]}")
            print(f"手牌：{display_cards(hand)}")
            if self.tasks:
                print("任务及完成情况：")
                print("\n".join(self._task_lines()))
            raw = prompt("出牌（win/fail 结束，setlevel N 跳关）> ")
            if raw in {"win", "胜利"}:
                self._on_win()
                box("胜利", "所有玩家胜利。", C.GRN)
                return
            if raw in {"fail", "失败"}:
                box("失败", "任务失败。", C.RED)
                return
            if raw.lower().startswith("setlevel"):
                self._handle_setlevel(raw)
                continue
            card = parse_card(raw)
            if card is None:
                print(f"{C.RED}无法识别牌。{C.R}")
                continue
            ok, reason = legal_play(hand, card, self.lead_suit)
            if not ok:
                print(f"{C.RED}{reason}{C.R}")
                continue
            hand.remove(card)
            self.hands[str(self.current)] = sort_cards(hand)
            if not self.current_trick:
                self.lead_suit = suit_of(card)
            self.current_trick.append({"player": self.current, "card": card})
            if len(self.current_trick) >= len(self.players):
                winner = trick_winner(self.current_trick)
                cards = " ".join(display_card(str(p["card"])) for p in self.current_trick)
                print(f"{C.GRN}本墩：{cards}，{self.names[winner]} 赢。{C.R}")
                self.trick_history.append(
                    {
                        "no": self.trick_no,
                        "plays": [
                            {"player": int(p["player"]), "card": str(p["card"])}
                            for p in self.current_trick
                        ],
                        "winner": winner,
                    }
                )
                self.current = winner
                self.current_trick = []
                self.lead_suit = None
                self.trick_no += 1
                if self._after_trick():
                    return
            else:
                self.current = self.order[(self.order.index(self.current) + 1) % len(self.order)]
        box("手牌已打完", "请人工核对任务。输入胜利结算由 Bot 侧支持。", C.YEL)

    def _task_lines(self) -> list[str]:
        lines: list[str] = []
        for i, task in enumerate(self.tasks, 1):
            owner = task.get("assigned_to")
            owner_text = "未选" if owner is None else self.names[int(owner)]
            if task.get("failed"):
                state = "❌"
            elif task.get("completed"):
                state = "✅"
            else:
                state = "□"
            lines.append(f"{i}. {state} [{task['difficulty']}] {task['text']}（{owner_text}）")
        return lines

    def _eval_state(self) -> dict:
        for i, task in enumerate(self.tasks, 1):
            task.setdefault("display_no", i)
        return {
            "mode": self.mode_id,
            "order": self.order,
            "captain_id": self.captain,
            "hands": self.hands,
            "tasks": self.tasks,
            "trick_history": self.trick_history,
            "mission": {
                "no": self.mission.no if self.mission else None,
                "special": self.mission.special if self.mission else None,
            },
        }

    def _after_trick(self) -> bool:
        """墩结束后判定。锁死胜利则收局并返回 True。"""
        state = self._eval_state()
        playing_ended = not any(self.hands[str(p)] for p in self.players)
        changes = evaluate_tasks(state, final=playing_ended)
        for line in changes:
            print(f"{C.GRN}{line}{C.R}" if "完成" in line else f"{C.RED}{line}{C.R}")
        if mission_locked_win(state):
            self._on_win()
            extra = "出牌结束，任务已全部完成。" if playing_ended else "任务已全部锁死完成，剩余墩不用打。"
            box("胜利", extra, C.GRN)
            return True
        status, msg = evaluate_campaign_special(state, final=playing_ended)
        if status == "failed" and msg:
            print(f"{C.RED}⚠️ {msg}。可继续打完复盘，或 fail 结束。{C.R}")
        return False

    def _on_win(self) -> None:
        """战役胜利后推进单次运行内的关卡进度（<32 则 +1）。"""
        if self.mode_id != "campaign":
            return
        level = type(self)._campaign_level
        if level < 32:
            type(self)._campaign_level = level + 1
            print(f"{C.GRN}战役通关！下一关：第 {level + 1} 关（再来一局自动进入）。{C.R}")
        else:
            print(f"{C.GRN}32 关全部通关！{C.R}")

    def _handle_setlevel(self, raw: str) -> None:
        """调试跳关：setlevel N（下一局生效，对应 Bot 的 @我 深海战役 N）。"""
        parts = raw.split()
        if len(parts) < 2 or not parts[1].isdigit():
            print(f"{C.RED}用法：setlevel 1-32（下一局生效）{C.R}")
            return
        no = int(parts[1])
        if not 1 <= no <= 32:
            print(f"{C.RED}关卡需在 1-32 之间。{C.R}")
            return
        type(self)._campaign_level = no
        print(f"{C.GRN}下一局将从第 {no} 关开始。{C.R}")
