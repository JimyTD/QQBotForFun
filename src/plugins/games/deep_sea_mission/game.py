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
from .rules import all_tasks_completed, any_task_failed, evaluate_tasks, task_needs_prediction
from .tasks import draw_tasks


EMOJI = "🌊"
WIN_COIN_REWARD = 30
WIN_SCORE_REWARD = 10

_SELECT_RE = re.compile(r"^(?:选|选择)\s*(\d+)$")
_COMPLETE_RE = re.compile(r"^完成\s*(\d+)$")
_UNDO_COMPLETE_RE = re.compile(r"^撤销完成\s*(\d+)$")
_PREDICT_RE = re.compile(r"^(?:预测|predict)\s*(\d+)\s+(\d+)$", re.IGNORECASE)
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
    description = "合作吃墩 · 私聊手牌 · 自动判定任务"
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
        for i, task in enumerate(tasks, 1):
            task["display_no"] = i
        order = ctx.player_ids()
        captain_index = order.index(captain_id)

        ctx.state.update(
            phase="deal",
            difficulty=target,
            seat_owners=self._initial_seat_owners(ctx),
            hands=hands,
            initial_hands={pid: list(cards) for pid, cards in hands.items()},
            captain_id=captain_id,
            order=order,
            current_player=captain_id,
            selector_index=captain_index,
            tasks=tasks,
            won_tricks={str(p.qq_id): [] for p in ctx.players},
            trick_no=1,
            current_trick=[],
            trick_history=[],
            lead_suit=None,
            completed=False,
            visible_message_id=None,
            private_message_ids={},
            sonar_used={str(p.qq_id): False for p in ctx.players},
            sonar_public=[],
        )

    async def on_start(self, ctx: GameContext) -> None:
        self._register_controllers_for_routing(ctx)
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

        if phase == "prediction":
            if await self.submit_prediction(ctx, player_id, text, is_private=False):
                await self._persist(ctx)
                return True
            return False

        if phase in {"playing", "task_review"}:
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
                "💡 任务自动判定 · @我 胜利 / 失败"
            )
        if phase == "task_review":
            return f"{EMOJI} 深海任务核对任务中\n💡 任务已自动判定；@我 胜利 / 失败"
        if phase == "prediction":
            return f"{EMOJI} 深海任务预测阶段\n💡 当前玩家按提示输入：@我 预测 任务编号 墩数"
        return f"{EMOJI} 深海任务进行中"

    async def on_end(self, ctx: GameContext, reason: EndReason) -> None:
        await self._delete_all_private_messages(ctx)
        if reason == EndReason.COMPLETED and ctx.state.get("completed"):
            await self._delete_visible_message(ctx)
            for qq_id in self._reward_recipient_ids(ctx):
                await self.award(
                    qq_id,
                    WIN_COIN_REWARD,
                    reason=f"deep_sea_mission_win:{ctx.session_id}",
                    currency="coin",
                )
                await self.award(
                    qq_id,
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
                        *self._result_review_lines(ctx),
                        "",
                        f"所有玩家：+{WIN_COIN_REWARD} 金币 · +{WIN_SCORE_REWARD} 分",
                    ],
                    emoji="🏆",
                ),
            )
        elif reason != EndReason.ERROR:
            await self._delete_visible_message(ctx)
            await session.broadcast(
                ctx.group_id,
                render.text_card(
                    "深海任务 · 游戏结束",
                    [
                        f"结束原因：{reason.value}",
                        f"任务难度：{ctx.state.get('difficulty', '?')}",
                        f"完成墩数：{int(ctx.state.get('trick_no', 1)) - 1}",
                        "",
                        *self._result_review_lines(ctx),
                    ],
                    emoji=EMOJI,
                ),
            )

    async def _handle_task_selection(self, ctx: GameContext, player_id: int, text: str) -> bool:
        order: list[int] = [int(x) for x in ctx.state["order"]]
        selector_index = int(ctx.state["selector_index"])
        current_selector = order[selector_index]
        if not self._can_control_seat(ctx, player_id, current_selector):
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
        if match is None and text.isdigit():
            match = re.match(r"^(\d+)$", text)
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
        tasks[idx]["assigned_to"] = current_selector
        await session.broadcast(
            ctx.group_id,
            f"✅ {self._nickname(ctx, current_selector)} 选择任务 {idx + 1}：{tasks[idx]['text']}",
        )
        self._advance_selector(ctx)
        await self._after_selection_step(ctx)
        return True

    async def _after_selection_step(self, ctx: GameContext) -> None:
        if not self._unassigned_task_indices(ctx):
            if self._next_prediction_task(ctx) is not None:
                ctx.state["phase"] = "prediction"
                await session.broadcast(ctx.group_id, self._prediction_panel(ctx))
                return
            ctx.state["phase"] = "playing"
            ctx.state["current_player"] = int(ctx.state["captain_id"])
            await self._replace_visible_group_message(ctx, self._playing_panel(ctx, started=True))
            return
        await session.broadcast(ctx.group_id, self._task_selection_panel(ctx))

    async def submit_prediction(
        self,
        ctx: GameContext,
        player_id: int,
        text: str,
        *,
        is_private: bool,
        user_message_id: int | None = None,
    ) -> bool:
        task = self._next_prediction_task(ctx)
        if task is None:
            ctx.state["phase"] = "playing"
            ctx.state["current_player"] = int(ctx.state["captain_id"])
            await self._replace_visible_group_message(ctx, self._playing_panel(ctx, started=True))
            return True
        owner = int(task["assigned_to"])
        if not self._can_control_seat(ctx, player_id, owner):
            await session.broadcast(
                ctx.group_id,
                f"⚠️ 现在需要 {self._nickname(ctx, owner)} 预测任务 {task['display_no']} 的墩数。",
                at=player_id,
            )
            return True
        match = _PREDICT_RE.match(text)
        if match is None:
            await self._prediction_error(ctx, player_id, f"请按格式输入：预测 {task['display_no']} 墩数", is_private)
            return True
        idx = int(match.group(1)) - 1
        prediction = int(match.group(2))
        tasks: list[dict[str, Any]] = ctx.state["tasks"]
        if idx < 0 or idx >= len(tasks) or tasks[idx] is not task:
            await self._prediction_error(ctx, player_id, f"当前要预测的是任务 {task['display_no']}。", is_private)
            return True
        if task["id"] == "T090" and is_private:
            await self._prediction_error(ctx, player_id, "这是公开预测任务，请在群里 @我 预测。", is_private)
            return True
        if task["id"] == "T091" and not is_private:
            if user_message_id is not None:
                await session.delete_message(user_message_id)
            await session.broadcast(ctx.group_id, "⚠️ 这是秘密预测任务，请私聊我发送：预测 任务编号 墩数", at=player_id)
            return True
        max_tricks = len(ctx.state["initial_hands"].get(str(owner), []))
        if prediction < 0 or prediction > max_tricks:
            await self._prediction_error(ctx, player_id, f"预测墩数应为 0-{max_tricks}。", is_private)
            return True
        task["prediction"] = prediction
        if task["id"] == "T090":
            await session.broadcast(
                ctx.group_id,
                f"✅ {self._nickname(ctx, owner)} 公开预测任务 {task['display_no']}：赢 {prediction} 墩。",
            )
        else:
            await session.broadcast(ctx.group_id, f"✅ {self._nickname(ctx, owner)} 已完成秘密预测。")
        if self._next_prediction_task(ctx) is not None:
            await session.broadcast(ctx.group_id, self._prediction_panel(ctx))
            return True
        ctx.state["phase"] = "playing"
        ctx.state["current_player"] = int(ctx.state["captain_id"])
        await self._replace_visible_group_message(ctx, self._playing_panel(ctx, started=True))
        return True

    async def _handle_playing(self, ctx: GameContext, player_id: int, text: str) -> bool:
        if text in {"失败", "任务失败"}:
            await session.broadcast(ctx.group_id, f"💥 @{self._nickname(ctx, player_id)} 宣告任务失败。")
            await self._end(ctx, EndReason.ABORTED)
            return True
        if text in {"胜利", "成功", "任务成功"}:
            if not self._can_manage_task(ctx, player_id):
                await session.broadcast(ctx.group_id, "⚠️ 只有房主或任务领取者可以宣告胜利。", at=player_id)
                return True
            evaluate_tasks(ctx.state, final=ctx.state.get("phase") == "task_review")
            if any_task_failed(ctx.state):
                await session.broadcast(ctx.group_id, "⚠️ 已有任务判定失败，不能胜利。", at=player_id)
                return True
            if not all_tasks_completed(ctx.state):
                await session.broadcast(ctx.group_id, "⚠️ 还有任务未完成，不能胜利。", at=player_id)
                return True
            ctx.state["completed"] = True
            await self._end(ctx, EndReason.COMPLETED)
            return True

        if await self._handle_manual_task(ctx, player_id, text):
            return True
        if await self._handle_sonar(ctx, player_id, text):
            return True

        if ctx.state.get("phase") == "task_review":
            await session.broadcast(
                ctx.group_id,
                "⚠️ 出牌已经结束，任务已自动判定；完成则 @我 胜利，失败则 @我 失败。",
                at=player_id,
            )
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
        owns_task = owner is not None and self._can_control_seat(ctx, player_id, int(owner))
        if not self._is_host_controller(ctx, player_id) and not owns_task:
            await session.broadcast(ctx.group_id, "⚠️ 只有房主或任务领取者可以修改任务状态。", at=player_id)
            return True
        tasks[idx]["completed"] = not undo
        if not undo:
            tasks[idx]["failed"] = False
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
        seat_id = self._find_sonar_seat(ctx, player_id, text)
        if seat_id is None:
            await session.broadcast(ctx.group_id, "⚠️ 声呐声明不合法。", at=player_id)
            return True
        if ctx.state["sonar_used"].get(str(seat_id)):
            await session.broadcast(ctx.group_id, "⚠️ 你本局已经用过声呐。", at=player_id)
            return True
        card = parse_card(match.group(1))
        marker = SONAR_MARKERS.get(match.group(2).lower())
        hand = ctx.state["hands"].get(str(seat_id), [])
        if card is None or marker is None or not sonar_condition(hand, card, marker):
            await session.broadcast(ctx.group_id, "⚠️ 声呐声明不合法。", at=player_id)
            return True
        ctx.state["sonar_used"][str(seat_id)] = True
        ctx.state["sonar_public"].append({"player": seat_id, "card": card, "marker": marker})
        await session.broadcast(
            ctx.group_id,
            f"📡 @{self._nickname(ctx, seat_id)} 公开 {display_card(card)}：这是他的{display_suit(suit_of(card))}色{SONAR_MARKER_TEXT[marker]}牌。",
        )
        return True

    async def _play_card(self, ctx: GameContext, player_id: int, card: str) -> None:
        seat_id = int(ctx.state["current_player"])
        if not self._can_control_seat(ctx, player_id, seat_id):
            await session.broadcast(
                ctx.group_id,
                f"⚠️ 还没轮到你。当前轮到 @{self._nickname(ctx, int(ctx.state['current_player']))}。",
                at=player_id,
            )
            return
        hand = ctx.state["hands"].get(str(seat_id), [])
        lead_suit = ctx.state.get("lead_suit")
        ok, reason = legal_play(hand, card, str(lead_suit) if lead_suit else None)
        if not ok:
            await session.broadcast(ctx.group_id, f"⚠️ {reason}。", at=player_id)
            return
        hand.remove(card)
        ctx.state["hands"][str(seat_id)] = sort_cards(hand)
        if not ctx.state["current_trick"]:
            ctx.state["lead_suit"] = suit_of(card)
        ctx.state["current_trick"].append({"player": seat_id, "card": card})
        await self._delete_user_action_message(ctx, player_id)

        if len(ctx.state["current_trick"]) >= len(ctx.state["order"]):
            await self._finish_trick(ctx)
            await self._whisper_after_play(ctx, seat_id)
            return
        await self._whisper_after_play(ctx, seat_id)
        ctx.state["current_player"] = self._next_after(ctx, seat_id)
        await self._replace_visible_group_message(ctx, self._current_trick_panel(ctx))

    async def _finish_trick(self, ctx: GameContext) -> None:
        plays: list[dict[str, int | str]] = ctx.state["current_trick"]
        winner = trick_winner(plays)
        trick_no = int(ctx.state["trick_no"])
        won = ctx.state["won_tricks"][str(winner)]
        won.append(
            {
                "no": trick_no,
                "cards": [p["card"] for p in plays],
            }
        )
        ctx.state["trick_history"].append(
            {
                "no": trick_no,
                "plays": [
                    {"player": int(p["player"]), "card": str(p["card"])}
                    for p in plays
                ],
                "winner": winner,
            }
        )
        ctx.state["current_player"] = winner
        if any(not ctx.state["hands"].get(str(pid), []) for pid in ctx.state["order"]):
            ctx.state["phase"] = "task_review"
            evaluate_tasks(ctx.state, final=True)
        else:
            evaluate_tasks(ctx.state, final=False)
        await self._replace_visible_group_message(ctx, self._finished_trick_panel(ctx, plays, winner))
        ctx.state["trick_no"] = int(ctx.state["trick_no"]) + 1
        ctx.state["current_trick"] = []
        ctx.state["lead_suit"] = None
        if ctx.state.get("phase") == "task_review":
            await session.broadcast(
                ctx.group_id,
                "📌 有玩家已无手牌，本局出牌结束。任务已自动判定；完成则 @我 胜利，失败则 @我 失败。",
            )
        elif any_task_failed(ctx.state):
            await session.broadcast(ctx.group_id, "⚠️ 已有任务判定失败。可继续打完复盘，或 @我 失败 结束。")

    async def _whisper_all_hands(self, ctx: GameContext) -> None:
        for player in ctx.players:
            hand = ctx.state["hands"][str(player.qq_id)]
            tasks = self._task_lines(ctx, assigned_only=False)
            await self._replace_private_message(
                ctx,
                player.qq_id,
                render.text_card(
                    f"深海任务 · {player.nickname} 的手牌",
                    [
                        f"局号：{ctx.session_id}",
                        f"座位：@{player.nickname}",
                        f"队长：{self._nickname(ctx, int(ctx.state['captain_id']))}",
                        "你的手牌：",
                        *self._hand_lines(hand),
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
                f"队长：{self._nickname(ctx, int(ctx.state['captain_id']))}",
                f"当前选择：{self._nickname(ctx, selector)}",
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
                "指令：@我 出 蓝4 / @我 蓝4 / @我 声呐 蓝4 最高",
            ],
            emoji=EMOJI,
        )

    def _prediction_panel(self, ctx: GameContext) -> str:
        task = self._next_prediction_task(ctx)
        if task is None:
            return render.text_card("深海任务 · 预测完成", ["即将开始出牌。"], emoji=EMOJI)
        owner = int(task["assigned_to"])
        return render.text_card(
            "深海任务 · 预测",
            [
                f"当前玩家：{self._nickname(ctx, owner)}",
                f"任务 {task['display_no']}：{task['text']}",
                "",
                self._prediction_instruction(task),
            ],
            emoji=EMOJI,
        )

    def _current_trick_panel(self, ctx: GameContext) -> str:
        current = int(ctx.state["current_player"])
        lines = [
            f"第 {ctx.state['trick_no']} 墩",
            f"轮到：@{self._nickname(ctx, current)}",
            "",
            "本墩场面：",
        ]
        for play in ctx.state.get("current_trick", []):
            lines.append(
                f"@{self._nickname(ctx, int(play['player']))}：{display_card(str(play['card']))}"
            )
        lines.extend(["", "当前任务：", *self._task_lines(ctx), "", "指令：@我 出 蓝4 / @我 蓝4"])
        return render.text_card("深海任务 · 当前场面", lines, emoji=EMOJI)

    def _finished_trick_panel(
        self,
        ctx: GameContext,
        plays: list[dict[str, int | str]],
        winner: int,
    ) -> str:
        lines = [
            f"第 {ctx.state['trick_no']} 墩结束",
            f"赢家：@{self._nickname(ctx, winner)}",
            f"下一墩起手：@{self._nickname(ctx, winner)}",
            "",
            "本墩出牌：",
        ]
        for play in plays:
            lines.append(
                f"@{self._nickname(ctx, int(play['player']))}：{display_card(str(play['card']))}"
            )
        lines.extend(
            [
                "",
                "当前吃墩数：",
                *self._trick_count_lines(ctx),
                "",
                "当前任务：",
                *self._task_lines(ctx),
            ]
        )
        return render.text_card("深海任务 · 本墩结果", lines, emoji=EMOJI)

    def _task_lines(self, ctx: GameContext, *, assigned_only: bool = False) -> list[str]:
        lines: list[str] = []
        for i, task in enumerate(ctx.state["tasks"], 1):
            owner = task.get("assigned_to")
            if assigned_only and owner is None:
                continue
            owner_text = "未选择" if owner is None else self._nickname(ctx, int(owner))
            if task.get("failed"):
                state = "❌"
            elif task.get("completed"):
                state = "✅"
            elif task_needs_prediction(task) and task.get("prediction") is None:
                state = "?"
            else:
                state = "□"
            prediction_text = ""
            if task_needs_prediction(task) and task.get("prediction") is not None:
                prediction_text = "（已预测）" if task["id"] == "T091" else f"（预测 {task['prediction']} 墩）"
            lines.append(
                f"{i}. {state} [{task['difficulty']}] {task['text']}{prediction_text}（{owner_text}）"
            )
        return lines

    def _next_prediction_task(self, ctx: GameContext) -> dict[str, Any] | None:
        for task in ctx.state.get("tasks", []):
            if (
                task.get("assigned_to") is not None
                and task_needs_prediction(task)
                and task.get("prediction") is None
            ):
                return task
        return None

    async def _prediction_error(
        self,
        ctx: GameContext,
        player_id: int,
        message: str,
        is_private: bool,
    ) -> None:
        if is_private:
            await session.whisper(player_id, f"⚠️ {message}")
        else:
            await session.broadcast(ctx.group_id, f"⚠️ {message}", at=player_id)

    def _prediction_instruction(self, task: dict[str, Any]) -> str:
        if task.get("id") == "T091":
            return f"请私聊我发送：预测 {task['display_no']} 墩数"
        return f"请在群里发送：@我 预测 {task['display_no']} 墩数"

    def _trick_count_lines(self, ctx: GameContext) -> list[str]:
        won_tricks: dict[str, list[dict[str, Any]]] = ctx.state.get("won_tricks", {})
        return [
            f"{self._nickname(ctx, int(seat_id))}：{len(won_tricks.get(str(seat_id), []))} 墩"
            for seat_id in ctx.state.get("order", [])
        ]

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

    def _trick_cards_text(self, trick: dict[str, Any]) -> str:
        return " ".join(display_card(str(card)) for card in trick.get("cards", []))

    def _can_manage_task(self, ctx: GameContext, player_id: int) -> bool:
        if self._is_host_controller(ctx, player_id):
            return True
        return any(
            t.get("assigned_to") is not None
            and self._can_control_seat(ctx, player_id, int(t["assigned_to"]))
            for t in ctx.state.get("tasks", [])
        )

    def _initial_seat_owners(self, ctx: GameContext) -> dict[str, int]:
        owners = {
            str(seat_id): int(owner_id)
            for seat_id, owner_id in dict(ctx.config.get("seat_owners", {})).items()
        }
        for player in ctx.players:
            owners.setdefault(str(player.qq_id), player.qq_id)
        return owners

    def _controller_of(self, ctx: GameContext, seat_id: int) -> int:
        return int(ctx.state.get("seat_owners", {}).get(str(seat_id), seat_id))

    def _can_control_seat(self, ctx: GameContext, actor_id: int, seat_id: int) -> bool:
        return actor_id == seat_id or actor_id == self._controller_of(ctx, seat_id)

    def _is_host_controller(self, ctx: GameContext, actor_id: int) -> bool:
        return self._can_control_seat(ctx, actor_id, ctx.host_id)

    def _reward_recipient_ids(self, ctx: GameContext) -> list[int]:
        ids = {self._controller_of(ctx, p.qq_id) for p in ctx.players}
        return sorted(ids)

    def _register_controllers_for_routing(self, ctx: GameContext) -> None:
        active = session.get_active(ctx.group_id)
        if active is None:
            return
        for owner_id in ctx.state.get("seat_owners", {}).values():
            active.player_ids.add(int(owner_id))

    def _find_sonar_seat(self, ctx: GameContext, actor_id: int, text: str) -> int | None:
        match = _SONAR_RE.match(text)
        if match is None:
            return None
        card = parse_card(match.group(1))
        marker = SONAR_MARKERS.get(match.group(2).lower())
        if card is None or marker is None:
            return None
        for seat_id in ctx.state.get("order", []):
            seat = int(seat_id)
            if not self._can_control_seat(ctx, actor_id, seat):
                continue
            hand = ctx.state["hands"].get(str(seat), [])
            if sonar_condition(hand, card, marker):
                return seat
        return None

    async def _delete_user_action_message(self, ctx: GameContext, player_id: int) -> None:
        message_id = session.last_routed_message_id(ctx.session_id, player_id)
        if message_id is not None:
            await session.delete_message(message_id)

    async def _delete_visible_message(self, ctx: GameContext) -> None:
        message_id = ctx.state.get("visible_message_id")
        if message_id is None:
            return
        await session.delete_message(int(message_id))
        ctx.state["visible_message_id"] = None

    async def _replace_visible_group_message(self, ctx: GameContext, message: str) -> None:
        await self._delete_visible_message(ctx)
        message_id = await session.broadcast(ctx.group_id, message)
        ctx.state["visible_message_id"] = message_id

    async def _whisper_after_play(self, ctx: GameContext, seat_id: int) -> None:
        hand = ctx.state["hands"].get(str(seat_id), [])
        won = ctx.state["won_tricks"].get(str(seat_id), [])
        recent = won[-1] if won else None
        lines = [
            f"座位：@{self._nickname(ctx, seat_id)}",
            f"剩余手牌：{len(hand)} 张",
            f"已吃墩数：{len(won)}",
        ]
        if recent is not None:
            lines.append(f"最近吃墩：第 {recent['no']} 墩，{self._trick_cards_text(recent)}")
        else:
            lines.append("最近吃墩：暂无")
        lines.extend(["", "你的手牌：", *self._hand_lines(hand)])
        await self._replace_private_message(
            ctx,
            seat_id,
            render.text_card("深海任务 · 出牌后状态", lines, emoji=EMOJI),
        )

    async def _replace_private_message(self, ctx: GameContext, seat_id: int, message: str) -> None:
        message_ids: dict[str, int] = ctx.state.setdefault("private_message_ids", {})
        old_message_id = message_ids.get(str(seat_id))
        if old_message_id is not None:
            await session.delete_message(int(old_message_id))
        new_message_id = await session.whisper(self._controller_of(ctx, seat_id), message)
        if new_message_id is not None:
            message_ids[str(seat_id)] = new_message_id
        else:
            message_ids.pop(str(seat_id), None)

    async def _delete_all_private_messages(self, ctx: GameContext) -> None:
        message_ids: dict[str, int] = ctx.state.get("private_message_ids", {})
        for message_id in list(message_ids.values()):
            await session.delete_message(int(message_id))
        message_ids.clear()

    def _result_review_lines(self, ctx: GameContext) -> list[str]:
        lines: list[str] = ["本局任务："]
        task_lines = self._task_lines(ctx)
        lines.extend(task_lines if task_lines else ["无任务"])
        lines.append("")
        lines.append("初始手牌：")
        initial_hands: dict[str, list[str]] = ctx.state.get("initial_hands", {})
        for seat_id in ctx.state.get("order", []):
            seat = int(seat_id)
            lines.append(f"@{self._nickname(ctx, seat)}：{display_cards(initial_hands.get(str(seat), []))}")
        lines.append("")
        lines.append("每墩回顾：")
        history = ctx.state.get("trick_history", [])
        if not history:
            lines.append("暂无完整墩记录")
            return lines
        for trick in history:
            play_text = "，".join(
                f"@{self._nickname(ctx, int(play['player']))} {display_card(str(play['card']))}"
                for play in trick.get("plays", [])
            )
            lines.append(
                f"第 {trick['no']} 墩：{play_text}；赢家 @{self._nickname(ctx, int(trick['winner']))}"
            )
        return lines

    def _hand_lines(self, hand: list[str]) -> list[str]:
        groups = [
            ("粉", "pink"),
            ("黄", "yellow"),
            ("蓝", "blue"),
            ("绿", "green"),
            ("潜艇", "sub"),
        ]
        lines: list[str] = []
        for label, suit in groups:
            cards = [card for card in sort_cards(hand) if suit_of(card) == suit]
            if cards:
                lines.append(f"{label}：{' '.join(display_card(card) for card in cards)}")
        return lines or ["（空）"]

    async def _persist(self, ctx: GameContext) -> None:
        runner = game_base.get_runner(ctx.session_id)
        if runner is not None:
            await runner.persist()

    async def _end(self, ctx: GameContext, reason: EndReason) -> None:
        runner = game_base.get_runner(ctx.session_id)
        if runner is not None:
            await runner.end(reason)
