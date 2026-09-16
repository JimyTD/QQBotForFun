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
    display_suit,
    legal_play,
    parse_card,
    sonar_condition,
    sort_cards,
    suit_of,
    trick_winner,
)
from src.plugins.games.deep_sea_mission.game import (
    SONAR_BAD_FORMAT_TEXT,
    SONAR_ILLEGAL_TEXT,
    SONAR_MARKER_TEXT,
    SONAR_QUOTA_USED_TEXT,
    SONAR_USAGE_CORE,
    SONAR_USED_TEXT,
    DeepSeaMissionGame,
    is_sonar_text,
    parse_sonar,
    resolve_sonar_mode,
    sonar_block_reason,
)
from src.plugins.games.deep_sea_mission.rules import (
    evaluate_campaign_special,
    evaluate_tasks,
    mission_locked_win,
    task_progress,
)
from src.plugins.games.deep_sea_mission.tasks import draw_tasks

from .base import C, GameCLIAdapter, box, info, prompt

# 统一退出词: base.prompt() 在 Ctrl+C / EOF 时也返回 "quit",
# 各输入循环必须显式处理, 否则会无限刷屏 (见 docs/13)。
QUIT_TOKENS = {"quit", "exit", "退出", "结束"}


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
        # 声呐（规则与文案全部来自 game.py，见铁律 13）
        self.sonar_mode = "normal"
        self.sonar_note = ""
        self.sonar_used: dict[str, bool] = {}
        self.sonar_used_count = 0
        self.sonar_quota = 0
        # 玩家主动退出 (quit/exit/Ctrl+C/EOF): 置位后 play() 直接返回。
        self._aborted = False

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
        self.sonar_used = {str(p): False for p in self.players}
        self.sonar_used_count = 0
        self.sonar_quota = len(self.players) - 2

        if mode_id == "campaign":
            mission_no = type(self)._campaign_level
            mission = get_mission(mission_no)
            self.mission = mission
            self.sonar_mode, self.sonar_note = resolve_sonar_mode(mission, rng)
            if mission.task_source == "draw":
                self.tasks = draw_tasks(mission.difficulty, len(self.players), rng)
            elif mission.task_source == "fixed":
                self.tasks = fixed_tasks_m32(len(self.players))
            else:
                self.tasks = []
            self._apply_auto_assignment(mission)
        else:
            self.sonar_mode, self.sonar_note = resolve_sonar_mode(None, rng)
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

    def _deal_box_lines(self) -> list[str]:
        """发牌面板：默认不泄露他人手牌（与群内私聊一致），--debug 才全打。"""
        lines = [f"队长：{self.names[self.captain]}", ""]
        if self.debug:
            lines.append(
                "[debug] "
                + " / ".join(
                    f"{self.names[p]} {display_cards(self.hands[str(p)])}" for p in self.players
                )
            )
        lines.append(
            "手牌："
            + "、".join(f"{self.names[p]} {len(self.hands[str(p)])} 张" for p in self.players)
            + "（各自回合才展示自己的手牌，与群内一致）"
        )
        if self.sonar_note:
            lines.append(f"📡 {self.sonar_note}")
        return lines

    async def play(self) -> None:
        header = self._campaign_header()
        lines: list[str] = []
        if header:
            lines.append(header)
        lines += self._deal_box_lines()
        if self.tasks:
            lines += ["", "任务：", *self._task_lines()]
        else:
            lines += ["", "（本关无任务卡，直接出牌）"]
        box("深海任务 · 发牌", "\n".join(lines), C.BLUE)
        if self.tasks:
            await self._select_tasks()
            if self._aborted:
                return
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
            print(f"{self.names[player]} 手牌：{display_cards(self.hands[str(player)])}")
            print("\n".join(self._task_lines()))
            tag = "自由选任务" if free else f"{self.names[player]} 选任务"
            text = prompt(f"{tag}（如 1；pass 跳过）> ")
            if text.strip().lower() in QUIT_TOKENS:
                info("已退出本局。")
                self._aborted = True
                return
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
            print(f"{self.names[player]} 手牌：{display_cards(self.hands[str(player)])}")
            text = prompt(f"{self.names[player]} 是否包揽全部任务？(y/包揽 / n/过) > ").strip().lower()
            if text in QUIT_TOKENS:
                info("已退出本局。")
                self._aborted = True
                return
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
            print(f"{self.names[player]} 手牌：{display_cards(self.hands[str(player)])}")
            print("\n".join(self._task_lines()))
            text = prompt(f"{self.names[player]} 选任务（如 1；pass 跳过）> ")
            if text.strip().lower() in QUIT_TOKENS:
                info("已退出本局。")
                self._aborted = True
                return
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
        self._sonar_stage()  # 任务卡选完 → 第一墩开始前
        if self._aborted:
            return
        while any(self.hands[str(p)] for p in self.players):
            hand = self.hands[str(self.current)]
            print(f"\n第 {self.trick_no} 墩，轮到 {self.names[self.current]}")
            print(f"手牌：{display_cards(hand)}")
            if self.tasks:
                print("任务及完成情况：")
                print("\n".join(self._task_lines()))
            raw = prompt("出牌（声呐 蓝4 最高 · win/fail 结束 · setlevel N 跳关）> ")
            if raw.strip().lower() in QUIT_TOKENS:
                info("已退出本局。")
                return
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
            if self._declare_sonar(raw) != "not_sonar":
                continue  # 声呐不消耗出牌机会，同一玩家继续出牌
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
                self._sonar_stage()  # 墩间：任一玩家可发声呐
                if self._aborted:
                    return
            else:
                self.current = self.order[(self.order.index(self.current) + 1) % len(self.order)]
        box("手牌已打完", "请人工核对任务。输入胜利结算由 Bot 侧支持。", C.YEL)

    # ==================== 声呐 ====================
    # 规则判定（时机 / 写法 / 次数）全部调用 game.py 的共用实现，
    # 保证 CLI 与群里逐字一致（铁律 13）。

    def _sonar_block(self) -> str | None:
        return sonar_block_reason(
            sonar_mode=self.sonar_mode,
            mission_no=self.mission.no if self.mission else None,
            trick_no=self.trick_no,
            trick_in_progress=bool(self.current_trick),
        )

    def _sonar_available(self) -> bool:
        """此刻是否还有空着的声呐窗口（用于决定要不要开墩间提示）。"""
        if self.sonar_mode == "silence":
            return False
        if self.sonar_mode == "rapture":
            return self.sonar_used_count < self.sonar_quota
        return any(not self.sonar_used.get(str(p), False) for p in self.order)

    def _sonar_owner(self, card: str, marker: str) -> int | None:
        """按牌面反查归属：牌在整副里唯一，所以不会歧义（群内由发话人决定）。"""
        for p in self.order:
            if sonar_condition(self.hands[str(p)], card, marker):
                return p
        return None

    def _declare_sonar(self, text: str) -> str:
        """处理一条声呐输入 → "not_sonar" / "ok" / "rejected"。"""
        if not is_sonar_text(text):
            return "not_sonar"
        block = self._sonar_block()
        if block is not None:
            print(f"{C.RED}{block}{C.R}")
            return "rejected"
        parsed = parse_sonar(text)
        if parsed is None:
            print(f"{C.RED}{SONAR_BAD_FORMAT_TEXT.format(usage=SONAR_USAGE_CORE)}{C.R}")
            return "rejected"
        card, marker = parsed
        owner = self._sonar_owner(card, marker)
        if owner is None:
            print(f"{C.RED}{SONAR_ILLEGAL_TEXT}{C.R}")
            return "rejected"

        if self.sonar_mode == "rapture":
            if self.sonar_used_count >= self.sonar_quota:
                print(f"{C.RED}{SONAR_QUOTA_USED_TEXT}{C.R}")
                return "rejected"
            self.sonar_used_count += 1
            left = self.sonar_quota - self.sonar_used_count
            print(
                f"{C.GRN}📡 {self.names[owner]} 公开 {display_card(card)}："
                f"这是他的{display_suit(suit_of(card))}色{SONAR_MARKER_TEXT[marker]}牌"
                f"（剩余共享声呐 {left} 次）。{C.R}"
            )
            return "ok"

        if self.sonar_used.get(str(owner)):
            print(f"{C.RED}{SONAR_USED_TEXT}{C.R}")
            return "rejected"
        self.sonar_used[str(owner)] = True
        if self.sonar_mode == "currents":
            print(
                f"{C.GRN}📡 {self.names[owner]} 公开 {display_card(card)}："
                f"这是一张满足「最高/最低/唯一」之一的牌。{C.R}"
            )
        else:
            print(
                f"{C.GRN}📡 {self.names[owner]} 公开 {display_card(card)}："
                f"这是他的{display_suit(suit_of(card))}色{SONAR_MARKER_TEXT[marker]}牌。{C.R}"
            )
        return "ok"

    def _sonar_stage(self) -> None:
        """墩间声呐窗口：对应群里「任一玩家都能在墩与墩之间发声呐」。"""
        if not self._sonar_available():
            return
        print(f"\n{C.CYAN}—— 墩间声呐（任一玩家可发；直接回车继续）——{C.R}")
        while True:
            raw = prompt(f"声呐？(如 {SONAR_USAGE_CORE}) > ")
            if raw.strip().lower() in QUIT_TOKENS:
                info("已退出本局。")
                self._aborted = True
                return
            if not raw:
                return
            status = self._declare_sonar(raw)
            if status == "not_sonar":
                print(f"{C.RED}无法识别。请输入 {SONAR_USAGE_CORE}，或直接回车继续。{C.R}")
                continue
            # 报错就回到出牌流程；成功且还有额度则可继续发（rapture 允许同一人连发）
            if status != "ok" or not self._sonar_available():
                return

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
            progress = task_progress(self._eval_state(), task)
            if progress:
                lines.append(f"   └ {progress}")
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
