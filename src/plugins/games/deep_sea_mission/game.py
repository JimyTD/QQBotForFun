"""深海任务：合作吃墩游戏框架。"""

from __future__ import annotations

import random
import re
from typing import Any

from core import game_base, render, session
from core.errors import WhisperFailedError
from core.game_base import GameBase, GameMode, register_game
from core.types import EndReason, GameContext

from .cards import (
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
from .tasks import draw_tasks


EMOJI = "🌊"
WIN_COIN_REWARD = 30
WIN_SCORE_REWARD = 10

_SELECT_RE = re.compile(r"^(?:选|选择)\s*(\d+)$")
_COMPLETE_RE = re.compile(r"^完成\s*(\d+)$")
_UNDO_COMPLETE_RE = re.compile(r"^撤销完成\s*(\d+)$")
_PLAY_PREFIX_RE = re.compile(r"^(?:出|打|play)\s*", re.IGNORECASE)
_SONAR_RE = re.compile(r"^(?:声呐|沟通|sonar)\s*(\S+)\s*(最高|最低|唯一|high|low|only)$", re.IGNORECASE)

SONAR_MARKERS = {
    "最高": "highest",
    "high": "highest",
    "最低": "lowest",
    "low": "lowest",
    "唯一": "only",
    "only": "only",
}
SONAR_MARKER_TEXT = {
    "highest": "最高",
    "lowest": "最低",
    "only": "唯一",
}


@register_game
class DeepSeaMissionGame(GameBase):
    id = "deep_sea_mission"
    name = "深海任务"
    description = "合作吃墩 · 私聊手牌 · 手动确认任务"
    min_players = 3
    max_players = 5
    version = "1.0"
    serialize_actions = True
    event_driven = True
    emoji = EMOJI

    MODES = [
        GameMode(
            id="mission",
            name="任务难度",
            description="由开局命令指定任务总难度",
            aliases=("深海任务", "mission"),
        )
    ]

    async def on_create(self, ctx: GameContext) -> None:
        player_count = len(ctx.players)
        if player_count < self.min_players or player_count > self.max_players:
            raise ValueError("深海任务需要 3-5 名玩家")
        target = int(ctx.config.get("difficulty", 3))
        rng = random.Random()
        deck = build_deck(rng)
        hands = deal(deck, ctx.player_ids())
        captain_id = self._find_captain(hands)
        tasks = draw_tasks(target, player_count, rng)
        order = ctx.player_ids()
        captain_index = order.index(captain_id)

        ctx.state.update(
            phase="deal",
            difficulty=target,
            hands=hands,
            captain_id=captain_id,
            order=order,
            current_player=captain_id,
            selector_index=captain_index,
            tasks=tasks,
            won_tricks={str(p.qq_id): [] for p in ctx.players},
            trick_no=1,
            current_trick=[],
            lead_suit=None,
            completed=False,
            sonar_used={str(p.qq_id): False for p in ctx.players},
            sonar_public=[],
        )

    async def on_start(self, ctx: GameContext) -> None:
        try:
            await self._whisper_all_hands(ctx)
        except WhisperFailedError as e:
            await session.broadcast(ctx.group_id, f"⚠️ 手牌私聊失败：{e}\n本局深海任务已结束。")
            runner = game_base.get_runner(ctx.session_id)
            if runner is not None:
                await runner.end(EndReason.ERROR)
            return

        ctx.state["phase"] = "task_selection"
        await session.broadcast(ctx.group_id, self._task_selection_panel(ctx))

    async def on_player_action(self, ctx: GameContext, player_id: int, message: str) -> bool:
        text = message.strip()
        if not text or text.startswith("/"):
            return False

        phase = str(ctx.state.get("phase", ""))
        if phase == "task_selection":
            if await self._handle_task_selection(ctx, player_id, text):
                await self._persist(ctx)
                return True
            return False

        if phase == "playing":
            handled = await self._handle_playing(ctx, player_id, text)
            if handled:
                await self._persist(ctx)
            return handled

        return False

    def in_game_hint(self, ctx: GameContext) -> str:
        phase = ctx.state.get("phase")
        if phase == "task_selection":
            selector = self._nickname(ctx, int(ctx.state.get("order", [ctx.host_id])[int(ctx.state.get("selector_index", 0))]))
            return f"{EMOJI} 深海任务选任务阶段\n💡 当前轮到 @{selector}：@我 选 任务编号；无任务可选时 @我 过"
        if phase == "playing":
            current = self._nickname(ctx, int(ctx.state.get("current_player", ctx.host_id)))
            return (
                f"{EMOJI} 深海任务进行中 · 第 {ctx.state.get('trick_no', 1)} 墩\n"
                f"💡 当前轮到 @{current}：@我 出 蓝4 / @我 蓝4\n"
                "💡 @我 完成 任务编号 · @我 胜利 / 失败"
            )
        return f"{EMOJI} 深海任务进行中"

    async def on_end(self, ctx: GameContext, reason: EndReason) -> None:
        if reason == EndReason.COMPLETED and ctx.state.get("completed"):
            for player in ctx.players:
                await self.award(
                    player.qq_id,
                    WIN_COIN_REWARD,
                    reason=f"deep_sea_mission_win:{ctx.session_id}",
                    currency="coin",
                )
                await self.award(
                    player.qq_id,
                    WIN_SCORE_REWARD,
                    reason=f"deep_sea_mission_win:{ctx.session_id}",
                    currency="score",
                )
            await session.broadcast(
                ctx.group_id,
                render.text_card(
                    "深海任务 · 胜利结算",
                    [
                        f"任务难度：{ctx.state.get('difficulty', '?')}",
                        f"完成墩数：{int(ctx.state.get('trick_no', 1)) - 1}",
                        "",
                        f"所有玩家：+{WIN_COIN_REWARD} 金币 · +{WIN_SCORE_REWARD} 分",
                    ],
                    emoji="🏆",
                ),
            )
        elif reason != EndReason.ERROR:
            await session.broadcast(ctx.group_id, f"{EMOJI} 深海任务结束（{reason.value}）。")

    async def _handle_task_selection(self, ctx: GameContext, player_id: int, text: str) -> bool:
        order: list[int] = [int(x) for x in ctx.state["order"]]
        selector_index = int(ctx.state["selector_index"])
        current_selector = order[selector_index]
        if player_id != current_selector:
            await session.broadcast(
                ctx.group_id,
                f"⚠️ 现在轮到 @{self._nickname(ctx, current_selector)} 选择任务。",
                at=player_id,
            )
            return True

        unassigned = self._unassigned_task_indices(ctx)
        if text in {"过", "pass"}:
            if unassigned and len(unassigned) >= len(order):
                await session.broadcast(ctx.group_id, "⚠️ 还有足够任务可选，暂不能跳过。", at=player_id)
                return True
            self._advance_selector(ctx)
            await self._after_selection_step(ctx)
            return True

        match = _SELECT_RE.match(text)
        if not match:
            return False
        idx = int(match.group(1)) - 1
        tasks: list[dict[str, Any]] = ctx.state["tasks"]
        if idx < 0 or idx >= len(tasks):
            await session.broadcast(ctx.group_id, "⚠️ 没有这个任务编号。", at=player_id)
            return True
        if tasks[idx]["assigned_to"] is not None:
            await session.broadcast(ctx.group_id, "⚠️ 这个任务已经被选择。", at=player_id)
            return True
        tasks[idx]["assigned_to"] = player_id
        await session.broadcast(
            ctx.group_id,
            f"✅ @{self._nickname(ctx, player_id)} 选择任务 {idx + 1}：{tasks[idx]['text']}",
        )
        self._advance_selector(ctx)
        await self._after_selection_step(ctx)
        return True

    async def _after_selection_step(self, ctx: GameContext) -> None:
        if not self._unassigned_task_indices(ctx):
            ctx.state["phase"] = "playing"
            ctx.state["current_player"] = int(ctx.state["captain_id"])
            await session.broadcast(ctx.group_id, self._playing_panel(ctx, started=True))
            return
        await session.broadcast(ctx.group_id, self._task_selection_panel(ctx))

    async def _handle_playing(self, ctx: GameContext, player_id: int, text: str) -> bool:
        if text in {"失败", "任务失败"}:
            await session.broadcast(ctx.group_id, f"💥 @{self._nickname(ctx, player_id)} 宣告任务失败。")
            await self._end(ctx, EndReason.ABORTED)
            return True
        if text in {"胜利", "成功", "任务成功"}:
            if not self._can_manage_task(ctx, player_id):
                await session.broadcast(ctx.group_id, "⚠️ 只有房主或任务领取者可以宣告胜利。", at=player_id)
                return True
            ctx.state["completed"] = True
            await self._end(ctx, EndReason.COMPLETED)
            return True

        if await self._handle_manual_task(ctx, player_id, text):
            return True
        if await self._handle_sonar(ctx, player_id, text):
            return True

        card_text = _PLAY_PREFIX_RE.sub("", text).strip()
        card = parse_card(card_text)
        if card is None:
            return False
        await self._play_card(ctx, player_id, card)
        return True

    async def _handle_manual_task(self, ctx: GameContext, player_id: int, text: str) -> bool:
        match = _COMPLETE_RE.match(text)
        undo = False
        if match is None:
            match = _UNDO_COMPLETE_RE.match(text)
            undo = match is not None
        if match is None:
            return False
        idx = int(match.group(1)) - 1
        tasks: list[dict[str, Any]] = ctx.state["tasks"]
        if idx < 0 or idx >= len(tasks):
            await session.broadcast(ctx.group_id, "⚠️ 没有这个任务编号。", at=player_id)
            return True
        owner = tasks[idx].get("assigned_to")
        if player_id != ctx.host_id and player_id != owner:
            await session.broadcast(ctx.group_id, "⚠️ 只有房主或任务领取者可以修改任务状态。", at=player_id)
            return True
        tasks[idx]["completed"] = not undo
        state = "撤销完成" if undo else "完成"
        await session.broadcast(ctx.group_id, f"✅ 任务 {idx + 1} 已{state}：{tasks[idx]['text']}")
        return True

    async def _handle_sonar(self, ctx: GameContext, player_id: int, text: str) -> bool:
        match = _SONAR_RE.match(text)
        if match is None:
            return False
        if ctx.state["current_trick"]:
            await session.broadcast(ctx.group_id, "⚠️ 一墩进行中不能使用声呐。", at=player_id)
            return True
        if ctx.state["sonar_used"].get(str(player_id)):
            await session.broadcast(ctx.group_id, "⚠️ 你本局已经用过声呐。", at=player_id)
            return True
        card = parse_card(match.group(1))
        marker = SONAR_MARKERS.get(match.group(2).lower())
        hand = ctx.state["hands"].get(str(player_id), [])
        if card is None or marker is None or not sonar_condition(hand, card, marker):
            await session.broadcast(ctx.group_id, "⚠️ 声呐声明不合法。", at=player_id)
            return True
        ctx.state["sonar_used"][str(player_id)] = True
        ctx.state["sonar_public"].append({"player": player_id, "card": card, "marker": marker})
        await session.broadcast(
            ctx.group_id,
            f"📡 @{self._nickname(ctx, player_id)} 公开 {display_card(card)}：这是他的{display_suit(suit_of(card))}色{SONAR_MARKER_TEXT[marker]}牌。",
        )
        return True

    async def _play_card(self, ctx: GameContext, player_id: int, card: str) -> None:
        if player_id != int(ctx.state["current_player"]):
            await session.broadcast(
                ctx.group_id,
                f"⚠️ 还没轮到你。当前轮到 @{self._nickname(ctx, int(ctx.state['current_player']))}。",
                at=player_id,
            )
            return
        hand = ctx.state["hands"].get(str(player_id), [])
        lead_suit = ctx.state.get("lead_suit")
        ok, reason = legal_play(hand, card, str(lead_suit) if lead_suit else None)
        if not ok:
            await session.broadcast(ctx.group_id, f"⚠️ {reason}。", at=player_id)
            return
        hand.remove(card)
        ctx.state["hands"][str(player_id)] = sort_cards(hand)
        if not ctx.state["current_trick"]:
            ctx.state["lead_suit"] = suit_of(card)
        ctx.state["current_trick"].append({"player": player_id, "card": card})
        await session.broadcast(ctx.group_id, f"🃏 @{self._nickname(ctx, player_id)} 出了 {display_card(card)}")

        if len(ctx.state["current_trick"]) >= len(ctx.state["order"]):
            await self._finish_trick(ctx)
            return
        ctx.state["current_player"] = self._next_after(ctx, player_id)
        await session.broadcast(
            ctx.group_id,
            f"➡️ 轮到 @{self._nickname(ctx, int(ctx.state['current_player']))} 出牌。",
        )

    async def _finish_trick(self, ctx: GameContext) -> None:
        plays: list[dict[str, int | str]] = ctx.state["current_trick"]
        winner = trick_winner(plays)
        won = ctx.state["won_tricks"][str(winner)]
        won.append(
            {
                "no": int(ctx.state["trick_no"]),
                "cards": [p["card"] for p in plays],
            }
        )
        cards_text = " ".join(display_card(str(p["card"])) for p in plays)
        await session.broadcast(
            ctx.group_id,
            f"✅ 第 {ctx.state['trick_no']} 墩结束：{cards_text}\n"
            f"🏅 @{self._nickname(ctx, winner)} 赢得本墩。",
        )
        ctx.state["trick_no"] = int(ctx.state["trick_no"]) + 1
        ctx.state["current_trick"] = []
        ctx.state["lead_suit"] = None
        ctx.state["current_player"] = winner
        if not any(ctx.state["hands"][str(pid)] for pid in ctx.state["order"]):
            await session.broadcast(
                ctx.group_id,
                "📌 所有手牌已打完。请玩家核对任务：@我 完成 编号，全部完成后 @我 胜利；失败则 @我 失败。",
            )
        else:
            await session.broadcast(ctx.group_id, self._playing_panel(ctx))

    async def _whisper_all_hands(self, ctx: GameContext) -> None:
        for player in ctx.players:
            hand = ctx.state["hands"][str(player.qq_id)]
            tasks = self._task_lines(ctx, assigned_only=False)
            await session.whisper(
                player.qq_id,
                render.text_card(
                    "深海任务 · 你的手牌",
                    [
                        f"局号：{ctx.session_id}",
                        f"队长：@{self._nickname(ctx, int(ctx.state['captain_id']))}",
                        f"你的手牌：{display_cards(hand)}",
                        "",
                        "任务池：",
                        *tasks,
                        "",
                        "群里 @机器人 选 编号 / 出 蓝4 / 声呐 蓝4 最高",
                    ],
                    emoji=EMOJI,
                ),
            )

    def _task_selection_panel(self, ctx: GameContext) -> str:
        order = [int(x) for x in ctx.state["order"]]
        selector = order[int(ctx.state["selector_index"])]
        return render.text_card(
            "深海任务 · 选择任务",
            [
                f"目标难度：{ctx.state['difficulty']}",
                f"队长：@{self._nickname(ctx, int(ctx.state['captain_id']))}",
                f"当前选择：@{self._nickname(ctx, selector)}",
                "",
                *self._task_lines(ctx),
                "",
                "指令：@我 选 2；任务少于玩家时可 @我 过",
            ],
            emoji=EMOJI,
        )

    def _playing_panel(self, ctx: GameContext, *, started: bool = False) -> str:
        current = int(ctx.state["current_player"])
        title = "深海任务 · 开始出牌" if started else "深海任务 · 出牌"
        current_trick = ctx.state.get("current_trick", [])
        trick_line = "当前墩："
        if current_trick:
            trick_line += " ".join(
                f"@{self._nickname(ctx, int(p['player']))}:{display_card(str(p['card']))}"
                for p in current_trick
            )
        else:
            trick_line += "尚未出牌"
        return render.text_card(
            title,
            [
                f"第 {ctx.state['trick_no']} 墩",
                f"轮到：@{self._nickname(ctx, current)}",
                trick_line,
                "",
                *self._task_lines(ctx),
                "",
                "指令：@我 出 蓝4 / @我 蓝4 / @我 完成 2 / @我 声呐 蓝4 最高",
            ],
            emoji=EMOJI,
        )

    def _task_lines(self, ctx: GameContext, *, assigned_only: bool = False) -> list[str]:
        lines: list[str] = []
        for i, task in enumerate(ctx.state["tasks"], 1):
            owner = task.get("assigned_to")
            if assigned_only and owner is None:
                continue
            owner_text = "未选择" if owner is None else f"@{self._nickname(ctx, int(owner))}"
            done = "✅" if task.get("completed") else "□"
            lines.append(f"{i}. {done} [{task['difficulty']}] {task['text']}（{owner_text}）")
        return lines

    def _unassigned_task_indices(self, ctx: GameContext) -> list[int]:
        return [i for i, task in enumerate(ctx.state["tasks"]) if task.get("assigned_to") is None]

    def _advance_selector(self, ctx: GameContext) -> None:
        order = ctx.state["order"]
        ctx.state["selector_index"] = (int(ctx.state["selector_index"]) + 1) % len(order)

    def _next_after(self, ctx: GameContext, player_id: int) -> int:
        order = [int(x) for x in ctx.state["order"]]
        idx = order.index(player_id)
        return order[(idx + 1) % len(order)]

    def _find_captain(self, hands: dict[str, list[str]]) -> int:
        for pid, hand in hands.items():
            if "sub:4" in hand:
                return int(pid)
        raise ValueError("deck missing sub:4")

    def _nickname(self, ctx: GameContext, qq_id: int) -> str:
        player = ctx.get_player(qq_id)
        return player.nickname if player else str(qq_id)

    def _can_manage_task(self, ctx: GameContext, player_id: int) -> bool:
        if player_id == ctx.host_id:
            return True
        return any(t.get("assigned_to") == player_id for t in ctx.state.get("tasks", []))

    async def _persist(self, ctx: GameContext) -> None:
        runner = game_base.get_runner(ctx.session_id)
        if runner is not None:
            await runner.persist()

    async def _end(self, ctx: GameContext, reason: EndReason) -> None:
        runner = game_base.get_runner(ctx.session_id)
        if runner is not None:
            await runner.end(reason)
