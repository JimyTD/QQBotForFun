"""深海任务 CLI adapter。"""

from __future__ import annotations

import random

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
from src.plugins.games.deep_sea_mission.tasks import draw_tasks

from .base import C, GameCLIAdapter, box, prompt


class DeepSeaMissionCLIAdapter(GameCLIAdapter):
    game_name = DeepSeaMissionGame.name
    MODES = DeepSeaMissionGame.MODES

    def __init__(self, *, debug: bool = False) -> None:
        self.debug = debug
        self.players = [1, 2, 3]
        self.names = {1: "P1", 2: "P2", 3: "P3"}
        self.hands: dict[str, list[str]] = {}
        self.tasks: list[dict] = []
        self.order = list(self.players)
        self.current = 1
        self.captain = 1
        self.trick_no = 1
        self.current_trick: list[dict[str, int | str]] = []
        self.lead_suit: str | None = None

    async def start(self, mode_id: str) -> None:  # noqa: ARG002
        n = prompt("玩家人数 3-5（默认 3）> ").strip()
        if n:
            count = int(n)
            if count < 3 or count > 5:
                raise ValueError("玩家人数必须是 3-5")
            self.players = list(range(1, count + 1))
            self.names = {p: f"P{p}" for p in self.players}
            self.order = list(self.players)
        d = prompt("任务总难度（默认 3）> ").strip()
        difficulty = int(d) if d else 3
        rng = random.Random()
        deck = build_deck(rng)
        self.hands = deal(deck, self.players)
        self.captain = next(int(pid) for pid, hand in self.hands.items() if "sub:4" in hand)
        self.current = self.captain
        self.tasks = draw_tasks(difficulty, len(self.players), rng)

    async def play(self) -> None:
        box(
            "深海任务 · 发牌",
            "\n".join(
                [
                    f"队长：{self.names[self.captain]}",
                    "",
                    *[
                        f"{self.names[p]} 手牌：{display_cards(self.hands[str(p)])}"
                        for p in self.players
                    ],
                    "",
                    "任务：",
                    *self._task_lines(),
                ]
            ),
            C.BLUE,
        )
        await self._select_tasks()
        await self._play_cards()

    async def _select_tasks(self) -> None:
        selector_index = self.order.index(self.captain)
        while any(t["assigned_to"] is None for t in self.tasks):
            player = self.order[selector_index]
            print("\n".join(self._task_lines()))
            text = prompt(f"{self.names[player]} 选任务（如 1；pass 跳过）> ")
            if text.lower() in {"pass", "过"}:
                selector_index = (selector_index + 1) % len(self.order)
                continue
            idx = int(text) - 1
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
            raw = prompt("出牌（或 win/fail 结束）> ")
            if raw in {"win", "胜利"}:
                box("胜利", "所有玩家胜利。", C.GRN)
                return
            if raw in {"fail", "失败"}:
                box("失败", "任务失败。", C.RED)
                return
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
                self.current = winner
                self.current_trick = []
                self.lead_suit = None
                self.trick_no += 1
            else:
                self.current = self.order[(self.order.index(self.current) + 1) % len(self.order)]
        box("手牌已打完", "请人工核对任务。输入胜利结算由 Bot 侧支持。", C.YEL)

    def _task_lines(self) -> list[str]:
        lines: list[str] = []
        for i, task in enumerate(self.tasks, 1):
            owner = task.get("assigned_to")
            owner_text = "未选" if owner is None else self.names[int(owner)]
            done = "✅" if task.get("completed") else "□"
            lines.append(f"{i}. {done} [{task['difficulty']}] {task['text']}（{owner_text}）")
        return lines
