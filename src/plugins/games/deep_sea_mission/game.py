"""深海任务：合作吃墩游戏框架。"""

from __future__ import annotations

import random
import re
from typing import Any

from core import game_base, render, session
from core.errors import WhisperFailedError
from core.game_base import GameBase, GameMode, register_game
from core.group_config import get_group_config, set_group_config
from core.types import EndReason, GameContext

from .campaign import (
    ASG_ALL_ONE_CREW,
    ASG_CAPTAIN_ALL,
    ASG_CAPTAIN_NO_TASK,
    ASG_HARDEST_TO_CAPTAIN,
    ASG_SELF_NOMINATE_1,
    ASG_SELF_NOMINATE_2,
    MOD_CURRENTS,
    MOD_DISTRESS,
    MOD_FREE_SELECTION,
    MOD_RAPTURE,
    MOD_REALTIME,
    MOD_SILENCE,
    MOD_UNFAMILIAR,
    CAMPAIGN_LEVEL_KEY,
    EPILOGUE_MODIFIERS,
    EPILOGUE_START_DIFFICULTY,
    Mission,
    fixed_tasks_m32,
    get_mission,
)
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
    value_of,
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
_PASS_CARD_RE = re.compile(r"^(?:传|求救传牌|distress)\s*(\S+)$", re.IGNORECASE)

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
        ),
        GameMode(
            id="campaign",
            name="战役模式",
            description="按官方 32 关推进",
            aliases=("深海战役", "战役", "campaign"),
        ),
    ]

    async def on_create(self, ctx: GameContext) -> None:
        player_count = len(ctx.players)
        if player_count < self.min_players or player_count > self.max_players:
            raise ValueError("深海任务需要 3-5 名玩家")
        mode = str(ctx.config.get("mode", "mission"))
        rng = random.Random()
        deck = build_deck(rng)
        hands = deal(deck, ctx.player_ids())
        captain_id = self._find_captain(hands)
        order = ctx.player_ids()
        captain_index = order.index(captain_id)

        common: dict[str, Any] = {
            "phase": "deal",
            "mode": mode,
            "seat_owners": self._initial_seat_owners(ctx),
            "hands": hands,
            "initial_hands": {pid: list(cards) for pid, cards in hands.items()},
            "captain_id": captain_id,
            "order": order,
            "current_player": captain_id,
            "selector_index": captain_index,
            "won_tricks": {str(p.qq_id): [] for p in ctx.players},
            "trick_no": 1,
            "current_trick": [],
            "trick_history": [],
            "lead_suit": None,
            "completed": False,
            "visible_message_id": None,
            "private_message_ids": {},
            "sonar_used": {str(p.qq_id): False for p in ctx.players},
            "sonar_public": [],
            "sonar_quota": player_count - 2,
            "sonar_used_count": 0,
        }

        if mode == "campaign":
            epilogue_diff = ctx.config.get("epilogue_difficulty")
            if epilogue_diff is not None:
                difficulty = int(epilogue_diff)
                common.update(
                    {
                        "mission_no": None,
                        "mission": {
                            "no": None,
                            "difficulty": difficulty,
                            "modifiers": list(EPILOGUE_MODIFIERS),
                            "assignment": None,
                            "special": None,
                            "note": "Epilogue 无限模式：🐙 自由选任务",
                        },
                        "epilogue_difficulty": difficulty,
                        "difficulty": difficulty,
                        "sonar_mode": "normal",
                        "sonar_note": "",
                        "assignment": None,
                        "special": None,
                        "distress_pending": False,
                        "tasks": draw_tasks(difficulty, player_count, rng),
                    }
                )
            else:
                mission_no = int(ctx.config.get("mission_no", 1))
                mission = get_mission(mission_no)
                sonar_mode, sonar_note = self._resolve_sonar_mode(mission, rng)
                if mission.task_source == "draw":
                    if mission.difficulty is None:
                        raise ValueError(f"战役关卡 {mission_no} 需要难度数值")
                    tasks = draw_tasks(mission.difficulty, player_count, rng)
                elif mission.task_source == "fixed":
                    tasks = fixed_tasks_m32(player_count)
                else:
                    tasks = []
                if mission.assignment == ASG_CAPTAIN_ALL:
                    for t in tasks:
                        t["assigned_to"] = captain_id
                elif mission.assignment == ASG_HARDEST_TO_CAPTAIN and tasks:
                    hardest = max(range(len(tasks)), key=lambda i: int(tasks[i]["difficulty"]))
                    tasks[hardest]["assigned_to"] = captain_id
                common.update(
                    {
                        "mission_no": mission_no,
                        "mission": {
                            "no": mission.no,
                            "difficulty": mission.difficulty,
                            "modifiers": list(mission.modifiers),
                            "assignment": mission.assignment,
                            "special": mission.special,
                            "note": mission.note,
                        },
                        "difficulty": mission.difficulty if mission.difficulty is not None else 0,
                        "sonar_mode": sonar_mode,
                        "sonar_note": sonar_note,
                        "assignment": mission.assignment,
                        "special": mission.special,
                        "distress_pending": False,
                        "tasks": tasks,
                    }
                )
                if mission.assignment == ASG_CAPTAIN_NO_TASK:
                    # 队长不参与选任务，selector 从队长下家开始
                    common["selector_index"] = (captain_index + 1) % len(order)
        else:
            target = int(ctx.config.get("difficulty", 3))
            common.update(
                {
                    "difficulty": target,
                    "sonar_mode": "normal",
                    "sonar_note": "",
                    "tasks": draw_tasks(target, player_count, rng),
                }
            )

        ctx.state.update(common)

    def _resolve_sonar_mode(self, mission: Mission, rng: random.Random) -> tuple[str, str]:
        """按关卡 modifiers 解析声呐模式。返回 (mode, 说明文本)。"""
        if MOD_UNFAMILIAR in mission.modifiers:
            draw = rng.randint(1, 9)
            if draw <= 3:
                return "normal", "🔴 抽到 1-3：正常声呐"
            if draw <= 6:
                return "currents", "🔴 抽到 4-6：❓ Currents（声呐不公开标记）"
            return "rapture", "🔴 抽到 7-9：-2 Rapture（全队共享声呐）"
        if MOD_CURRENTS in mission.modifiers:
            return "currents", "❓ Currents：声呐不公开标记"
        if MOD_RAPTURE in mission.modifiers:
            return "rapture", "-2 Rapture：全队共享声呐"
        if MOD_SILENCE in mission.modifiers:
            return "silence", "🔇 禁止交流"
        return "normal", ""

    async def on_start(self, ctx: GameContext) -> None:
        self._register_controllers_for_routing(ctx)
        failed = await self._whisper_all_hands(ctx)
        if failed:
            await self._end_on_whisper_failure(ctx, failed, "本局深海任务已结束。")
            return

        if ctx.state.get("mode") == "campaign":
            if not ctx.state.get("tasks"):
                # 无难度关：无任务卡，直接进入出牌
                ctx.state["phase"] = "playing"
                await session.broadcast(
                    ctx.group_id,
                    self._playing_panel(ctx, started=True, campaign_header=True),
                )
                return
            if not self._unassigned_task_indices(ctx):
                # 队长包揽等已全部分配完毕
                ctx.state["phase"] = "playing"
                await session.broadcast(
                    ctx.group_id,
                    self._playing_panel(ctx, started=True, campaign_header=True),
                )
                return
            assignment = ctx.state.get("assignment")
            if assignment in {ASG_ALL_ONE_CREW, ASG_SELF_NOMINATE_1, ASG_SELF_NOMINATE_2}:
                order = [int(x) for x in ctx.state["order"]]
                captain_index = order.index(int(ctx.state["captain_id"]))
                ctx.state["nomination"] = {
                    "turn": captain_index,
                    "start": captain_index,
                    "nominees": [],
                    "target": 2 if assignment == ASG_SELF_NOMINATE_2 else 1,
                    "fallback": assignment != ASG_ALL_ONE_CREW,
                }
                ctx.state["phase"] = "task_selection"
                await session.broadcast(ctx.group_id, self._nomination_panel(ctx))
                return

        ctx.state["phase"] = "task_selection"
        await session.broadcast(ctx.group_id, self._task_selection_panel(ctx))

    async def on_player_action(self, ctx: GameContext, player_id: int, message: str) -> bool:
        text = message.strip()
        if not text or text.startswith("/"):
            return False

        phase = str(ctx.state.get("phase", ""))
        if phase == "distress":
            if await self._handle_distress(ctx, player_id, text):
                await self._persist(ctx)
                return True
            return False

        if phase == "task_selection":
            if await self._handle_task_selection(ctx, player_id, text):
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
        title = self._campaign_title(ctx)
        if phase == "distress":
            return (
                f"{EMOJI} 深海任务{title} · 求救传牌\n"
                "💡 每位玩家 @我 传 蓝4（传 1 张给左邻，禁传潜艇）"
            )
        if phase == "task_selection":
            selector = self._nickname(ctx, int(ctx.state.get("order", [ctx.host_id])[int(ctx.state.get("selector_index", 0))]))
            return (
                f"{EMOJI} 深海任务{title} · 选任务阶段\n"
                f"💡 当前轮到 @{selector}：@我 选 任务编号；无任务可选时 @我 过\n"
                f"{self._sonar_hint(ctx)}"
            )
        if phase == "playing":
            current = self._nickname(ctx, int(ctx.state.get("current_player", ctx.host_id)))
            return (
                f"{EMOJI} 深海任务{title} · 第 {ctx.state.get('trick_no', 1)} 墩\n"
                f"💡 当前轮到 @{current}：@我 出 蓝4 / @我 蓝4\n"
                "💡 @我 完成 任务编号 · @我 胜利 / 失败\n"
                f"{self._sonar_hint(ctx)}"
            )
        if phase == "task_review":
            return f"{EMOJI} 深海任务{title} · 核对任务中\n💡 @我 完成 任务编号 · @我 胜利 / 失败"
        return f"{EMOJI} 深海任务{title}进行中"

    def _campaign_title(self, ctx: GameContext) -> str:
        if ctx.state.get("mode") != "campaign":
            return ""
        return f" · 第 {ctx.state.get('mission_no', '?')} 关"

    def _sonar_hint(self, ctx: GameContext) -> str:
        mode = ctx.state.get("sonar_mode", "normal")
        if mode == "silence":
            return "🔇 本关禁止交流（无法使用声呐）"
        if mode == "currents":
            return "❓ 声呐不公开标记（可用但队友只能猜）"
        if mode == "rapture":
            used = int(ctx.state.get("sonar_used_count", 0))
            quota = int(ctx.state.get("sonar_quota", 0))
            return f"📡 全队共享声呐：剩余 {quota - used} 次"
        return "📡 每人一次声呐：@我 声呐 蓝4 最高/最低/唯一"

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
            next_line = await self._advance_campaign_progress(ctx)
            lines = [
                f"任务难度：{ctx.state.get('difficulty', '?')}",
                f"完成墩数：{int(ctx.state.get('trick_no', 1)) - 1}",
                "",
                *self._result_review_lines(ctx),
                "",
                f"所有玩家：+{WIN_COIN_REWARD} 金币 · +{WIN_SCORE_REWARD} 分",
            ]
            if next_line:
                lines.append(next_line)
            await session.broadcast(
                ctx.group_id,
                render.text_card("深海任务 · 胜利结算", lines, emoji="🏆"),
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
        assignment = ctx.state.get("assignment")

        # 自荐类 assignment：走自荐子流程
        if assignment in {ASG_ALL_ONE_CREW, ASG_SELF_NOMINATE_1, ASG_SELF_NOMINATE_2}:
            return await self._handle_nomination(ctx, player_id, text)

        # 战役模式可选：求救信号传牌
        if ctx.state.get("mode") == "campaign" and text in {"求救", "传牌", "distress"}:
            await self._start_distress(ctx)
            return True

        free_selection = MOD_FREE_SELECTION in ctx.state.get("mission", {}).get("modifiers", [])
        order: list[int] = [int(x) for x in ctx.state["order"]]
        selector_index = int(ctx.state["selector_index"])
        current_selector = order[selector_index]

        if free_selection:
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
            seat = self._actor_seat(ctx, player_id)
            tasks[idx]["assigned_to"] = seat
            await session.broadcast(
                ctx.group_id,
                f"✅ {self._nickname(ctx, seat)} 选择任务 {idx + 1}：{tasks[idx]['text']}",
            )
            await self._after_selection_step(ctx)
            return True

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
        tasks = ctx.state["tasks"]
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
            await self._enter_playing(ctx)
            return
        await session.broadcast(ctx.group_id, self._task_selection_panel(ctx))

    async def _enter_playing(self, ctx: GameContext) -> None:
        ctx.state["phase"] = "playing"
        ctx.state["current_player"] = int(ctx.state["captain_id"])
        await self._replace_visible_group_message(
            ctx, self._playing_panel(ctx, started=True, campaign_header=True)
        )

    def _actor_seat(self, ctx: GameContext, actor_id: int) -> int:
        """返回操作者实际代表的座位（调试位控制器归位到其第一个座位）。"""
        order = [int(x) for x in ctx.state["order"]]
        if actor_id in order:
            return actor_id
        for seat in order:
            if self._can_control_seat(ctx, actor_id, seat):
                return seat
        return actor_id

    def _nomination_panel(self, ctx: GameContext) -> str:
        nom = ctx.state.get("nomination", {})
        order = [int(x) for x in ctx.state["order"]]
        current = order[int(nom.get("turn", 0))]
        target = int(nom.get("target", 1))
        nominees = [self._nickname(ctx, int(s)) for s in nom.get("nominees", [])]
        lines = [
            f"本关任务分配：{target} 名船员包揽全部任务",
            f"当前轮到：@{self._nickname(ctx, current)}",
        ]
        if nominees:
            lines.append(f"已包揽：{'、'.join(nominees)}")
        lines.extend(["", "指令：@我 包揽（承接全部任务）· @我 过（不承接）"])
        return render.text_card("深海任务 · 任务分配", lines, emoji=EMOJI)

    async def _handle_nomination(self, ctx: GameContext, player_id: int, text: str) -> bool:
        nom = ctx.state.get("nomination")
        if not nom:
            return False
        order = [int(x) for x in ctx.state["order"]]
        current = order[int(nom["turn"])]
        if not self._can_control_seat(ctx, player_id, current):
            await session.broadcast(
                ctx.group_id,
                f"⚠️ 现在轮到 @{self._nickname(ctx, current)} 表态（@我 包揽 / @我 过）。",
                at=player_id,
            )
            return True

        if text in {"包揽", "我来", "nominate"}:
            nom["nominees"].append(current)
            await session.broadcast(ctx.group_id, f"✅ @{self._nickname(ctx, current)} 包揽全部任务。")
            if len(nom["nominees"]) >= int(nom["target"]):
                self._assign_all_tasks_to_nominees(ctx, nom["nominees"])
                ctx.state.pop("nomination", None)
                await self._enter_playing(ctx)
                return True
            nom["turn"] = (int(nom["turn"]) + 1) % len(order)
            await session.broadcast(ctx.group_id, self._nomination_panel(ctx))
            return True

        if text in {"过", "pass", "不包揽"}:
            nom["turn"] = (int(nom["turn"]) + 1) % len(order)
            if int(nom["turn"]) == int(nom["start"]) and len(nom["nominees"]) == 0:
                if nom.get("fallback"):
                    # 无人应答 → 退回轮流选
                    ctx.state.pop("nomination", None)
                    await session.broadcast(
                        ctx.group_id,
                        "⚠️ 无人包揽，退回轮流选任务。\n" + self._task_selection_panel(ctx),
                    )
                    return True
                # all_one_crew 必须有人包揽，继续循环
                await session.broadcast(
                    ctx.group_id,
                    "⚠️ 本关必须有船员包揽全部任务，请继续表态。",
                )
            await session.broadcast(ctx.group_id, self._nomination_panel(ctx))
            return True

        return False

    def _assign_all_tasks_to_nominees(self, ctx: GameContext, nominees: list[int]) -> None:
        tasks: list[dict[str, Any]] = ctx.state["tasks"]
        if len(nominees) == 1:
            for t in tasks:
                t["assigned_to"] = nominees[0]
            return
        # 两人共同包揽：复制一份任务给第二位
        first = nominees[0]
        second = nominees[1]
        dup = [dict(t) for t in tasks]
        for t in tasks:
            t["assigned_to"] = first
        for t in dup:
            t["assigned_to"] = second
        ctx.state["tasks"] = tasks + dup

    async def _start_distress(self, ctx: GameContext) -> None:
        ctx.state["phase"] = "distress"
        ctx.state["distress_choices"] = {}
        await session.broadcast(
            ctx.group_id,
            "⚓ 求救信号：每位玩家 @我 传 蓝4（传 1 张给左邻，禁传潜艇）。\n"
            "全部传完后自动结算。",
        )

    async def _handle_distress(self, ctx: GameContext, player_id: int, text: str) -> bool:
        if text in {"取消", "不传", "取消传牌"}:
            ctx.state["phase"] = "task_selection"
            await session.broadcast(ctx.group_id, "已取消求救传牌。\n" + self._task_selection_panel(ctx))
            return True
        match = _PASS_CARD_RE.match(text)
        if match is None:
            return False
        seat = self._actor_seat(ctx, player_id)
        card = parse_card(match.group(1))
        hand = ctx.state["hands"].get(str(seat), [])
        if card is None or card not in hand:
            await session.broadcast(ctx.group_id, "⚠️ 你没有这张牌。", at=player_id)
            return True
        if suit_of(card) == "sub":
            await session.broadcast(ctx.group_id, "⚠️ 潜艇不能作为求救信号传牌。", at=player_id)
            return True
        choices: dict[str, str] = ctx.state.setdefault("distress_choices", {})
        if str(seat) in choices:
            await session.broadcast(ctx.group_id, "⚠️ 你已经传过了。", at=player_id)
            return True
        choices[str(seat)] = card
        await session.broadcast(ctx.group_id, f"✅ @{self._nickname(ctx, seat)} 已传 1 张牌。")
        if len(choices) >= len(ctx.state["order"]):
            await self._finish_distress(ctx)
        return True

    async def _finish_distress(self, ctx: GameContext) -> None:
        choices: dict[str, str] = ctx.state["distress_choices"]
        order = [int(x) for x in ctx.state["order"]]
        hands: dict[str, list[str]] = ctx.state["hands"]
        # 每人的牌传给左邻（下一家）
        for seat in order:
            left = order[(order.index(seat) + 1) % len(order)]
            card = choices[str(seat)]
            hands[str(seat)].remove(card)
            hands[str(left)].append(card)
        for seat in order:
            hands[str(seat)] = sort_cards(hands[str(seat)])
        # 传牌后重发私聊手牌
        failed = await self._whisper_all_hands(ctx)
        if failed:
            await self._end_on_whisper_failure(ctx, failed, "本局深海任务已结束。")
            return
        await session.broadcast(
            ctx.group_id,
            "⚓ 传牌完成：每位玩家各传 1 张给左邻。",
        )
        ctx.state.pop("distress_choices", None)
        ctx.state["phase"] = "task_selection"
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

        if ctx.state.get("phase") == "task_review":
            await session.broadcast(
                ctx.group_id,
                "⚠️ 出牌已经结束，请核对任务：@我 完成 编号，全部完成后 @我 胜利；失败则 @我 失败。",
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
        state = "撤销完成" if undo else "完成"
        await session.broadcast(ctx.group_id, f"✅ 任务 {idx + 1} 已{state}：{tasks[idx]['text']}")
        return True

    async def _handle_sonar(self, ctx: GameContext, player_id: int, text: str) -> bool:
        match = _SONAR_RE.match(text)
        if match is None:
            return False
        sonar_mode = ctx.state.get("sonar_mode", "normal")
        if sonar_mode == "silence":
            await session.broadcast(ctx.group_id, "🔇 本关禁止交流，无法使用声呐。", at=player_id)
            return True
        if (
            ctx.state.get("mode") == "campaign"
            and ctx.state.get("mission", {}).get("no") == 23
            and int(ctx.state.get("trick_no", 1)) <= 2
        ):
            await session.broadcast(ctx.group_id, "🔇 第二墩前禁止交流。", at=player_id)
            return True
        if ctx.state["current_trick"]:
            await session.broadcast(ctx.group_id, "⚠️ 一墩进行中不能使用声呐。", at=player_id)
            return True
        seat_id = self._find_sonar_seat(ctx, player_id, text)
        if seat_id is None:
            await session.broadcast(ctx.group_id, "⚠️ 声呐声明不合法。", at=player_id)
            return True
        card = parse_card(match.group(1))
        marker = SONAR_MARKERS.get(match.group(2).lower())
        hand = ctx.state["hands"].get(str(seat_id), [])
        if card is None or marker is None or not sonar_condition(hand, card, marker):
            await session.broadcast(ctx.group_id, "⚠️ 声呐声明不合法。", at=player_id)
            return True

        if sonar_mode == "rapture":
            used = int(ctx.state.get("sonar_used_count", 0))
            quota = int(ctx.state.get("sonar_quota", 0))
            if used >= quota:
                await session.broadcast(ctx.group_id, "⚠️ 全队共享声呐次数已用完。", at=player_id)
                return True
            ctx.state["sonar_used_count"] = used + 1
            ctx.state["sonar_public"].append({"player": seat_id, "card": card, "marker": marker})
            await session.broadcast(
                ctx.group_id,
                f"📡 @{self._nickname(ctx, seat_id)} 公开 {display_card(card)}：这是他的{display_suit(suit_of(card))}色{SONAR_MARKER_TEXT[marker]}牌（剩余共享声呐 {quota - used - 1} 次）。",
            )
            return True

        if ctx.state["sonar_used"].get(str(seat_id)):
            await session.broadcast(ctx.group_id, "⚠️ 你本局已经用过声呐。", at=player_id)
            return True
        ctx.state["sonar_used"][str(seat_id)] = True
        if sonar_mode == "currents":
            ctx.state["sonar_public"].append({"player": seat_id, "card": card})
            await session.broadcast(
                ctx.group_id,
                f"📡 @{self._nickname(ctx, seat_id)} 公开 {display_card(card)}：这是一张满足「最高/最低/唯一」之一的牌。",
            )
        else:
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
        is_first = not ctx.state["current_trick"]
        if is_first:
            ctx.state["lead_suit"] = suit_of(card)
        ctx.state["current_trick"].append({"player": seat_id, "card": card})
        await self._delete_user_action_message(ctx, player_id)
        if is_first and suit_of(card) == "sub":
            await session.broadcast(
                ctx.group_id,
                "🚢 本墩首牌是潜艇，本墩为潜艇墩（最大潜艇赢）。",
            )

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
        await self._replace_visible_group_message(ctx, self._finished_trick_panel(ctx, plays, winner))
        ctx.state["trick_no"] = int(ctx.state["trick_no"]) + 1
        ctx.state["current_trick"] = []
        ctx.state["lead_suit"] = None
        ctx.state["current_player"] = winner
        if not ctx.state["hands"].get(str(winner), []):
            ctx.state["phase"] = "task_review"
            mission_no = ctx.state.get("mission", {}).get("no")
            if ctx.state.get("mode") == "campaign" and mission_no in {8, 12, 21, 23, 27}:
                violation = self._check_no_difficulty_constraints(ctx)
                if violation is not None:
                    await session.broadcast(
                        ctx.group_id,
                        f"📌 本局出牌结束。\n💥 {violation}。\n"
                        "若确认违反约束，请 @我 失败。",
                    )
                else:
                    await session.broadcast(
                        ctx.group_id,
                        "📌 本局出牌结束，约束校验通过，请 @我 胜利 确认。",
                    )
            else:
                await session.broadcast(
                    ctx.group_id,
                    "📌 下一墩起手玩家已无手牌，本局出牌结束。请核对任务：@我 完成 编号，全部完成后 @我 胜利；失败则 @我 失败。",
                )

    async def _whisper_all_hands(self, ctx: GameContext) -> list[int]:
        """逐玩家私聊发手牌，返回私聊失败的座位 QQ 列表（成功者仍收到手牌）。"""
        failed: list[int] = []
        for player in ctx.players:
            hand = ctx.state["hands"][str(player.qq_id)]
            tasks = self._task_lines(ctx, assigned_only=False)
            lines = [*self._campaign_header_lines(ctx)]
            if lines:
                lines.append("")
            lines += [
                f"局号：{ctx.session_id}",
                f"座位：@{player.nickname}",
                f"队长：{self._nickname(ctx, int(ctx.state['captain_id']))}",
                f"你的手牌：{display_cards(hand)}",
                "",
                "任务池：",
                *tasks,
                "",
                "群里 @机器人 选 编号 / 出 蓝4 / 声呐 蓝4 最高",
            ]
            try:
                await self._replace_private_message(
                    ctx,
                    player.qq_id,
                    render.text_card(
                        f"深海任务 · {player.nickname} 的手牌",
                        lines,
                        emoji=EMOJI,
                    ),
                )
            except WhisperFailedError:
                failed.append(player.qq_id)
        return failed

    async def _end_on_whisper_failure(self, ctx: GameContext, failed: list[int], tail: str) -> None:
        failed_nicks = "、".join(f"@{self._nickname(ctx, qid)}" for qid in failed)
        bot_hint = ""
        try:
            bot = session.get_bot()
            bot_qq = str(getattr(bot, "self_id", "") or "")
            if bot_qq:
                bot_hint = f"（QQ {bot_qq}）"
        except Exception:  # noqa: BLE001
            bot_hint = ""
        await session.broadcast(
            ctx.group_id,
            f"⚠️ 手牌私聊失败：{failed_nicks} 尚未添加机器人{bot_hint}为好友，无法接收私聊手牌。\n"
            "请以上玩家先点击机器人头像「添加好友」，加好后 @我 深海任务 / 深海战役 重新开局。\n"
            f"{tail}",
        )
        runner = game_base.get_runner(ctx.session_id)
        if runner is not None:
            await runner.end(EndReason.ERROR)

    def _campaign_header_lines(self, ctx: GameContext) -> list[str]:
        if ctx.state.get("mode") != "campaign":
            return []
        mission = ctx.state.get("mission", {})
        no = mission.get("no")
        difficulty = mission.get("difficulty")
        title = f"第 {no} 关" if no else "Epilogue"
        if difficulty:
            title += f" · 难度 {difficulty}"
        lines = [f"🏁 战役 {title}"]
        special = mission.get("special") or ""
        if special:
            lines.append(f"⚡ 特殊：{special}")
        note = mission.get("note") or ""
        if note:
            lines.append(f"📌 {note}")
        sonar_note = ctx.state.get("sonar_note") or ""
        if sonar_note:
            lines.append(f"📡 {sonar_note}")
        return lines

    def _task_selection_panel(self, ctx: GameContext) -> str:
        order = [int(x) for x in ctx.state["order"]]
        selector = order[int(ctx.state["selector_index"])]
        lines = [*self._campaign_header_lines(ctx)]
        if lines:
            lines.append("")
        lines += [
            f"目标难度：{ctx.state['difficulty']}",
            f"队长：{self._nickname(ctx, int(ctx.state['captain_id']))}",
            f"当前选择：{self._nickname(ctx, selector)}",
            "",
            *self._task_lines(ctx),
            "",
            "指令：@我 选 2；任务少于玩家时可 @我 过",
        ]
        if MOD_FREE_SELECTION in ctx.state.get("mission", {}).get("modifiers", []):
            lines.append("🐙 自由选任务：任何玩家都可 @我 选 编号，先到先得")
        return render.text_card("深海任务 · 选择任务", lines, emoji=EMOJI)

    def _playing_panel(
        self, ctx: GameContext, *, started: bool = False, campaign_header: bool = False
    ) -> str:
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
        lines: list[str] = []
        if campaign_header:
            lines += self._campaign_header_lines(ctx)
            if lines:
                lines.append("")
        lines += [
            f"第 {ctx.state['trick_no']} 墩",
            f"轮到：@{self._nickname(ctx, current)}",
            trick_line,
            "",
        ]
        if ctx.state.get("tasks"):
            lines += self._task_lines(ctx)
            lines.append("")
        lines.append("指令：@我 出 蓝4 / @我 蓝4 / @我 完成 2 / @我 声呐 蓝4 最高")
        return render.text_card(title, lines, emoji=EMOJI)

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
        lines.extend(["", "指令：@我 出 蓝4 / @我 蓝4"])
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
        lines.extend(["", "当前吃墩数：", *self._trick_count_lines(ctx)])
        return render.text_card("深海任务 · 本墩结果", lines, emoji=EMOJI)

    def _task_lines(self, ctx: GameContext, *, assigned_only: bool = False) -> list[str]:
        lines: list[str] = []
        for i, task in enumerate(ctx.state["tasks"], 1):
            owner = task.get("assigned_to")
            if assigned_only and owner is None:
                continue
            owner_text = "未选择" if owner is None else self._nickname(ctx, int(owner))
            done = "✅" if task.get("completed") else "□"
            lines.append(f"{i}. {done} [{task['difficulty']}] {task['text']}（{owner_text}）")
        return lines

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
        n = len(order)
        if ctx.state.get("assignment") == ASG_CAPTAIN_NO_TASK:
            captain = int(ctx.state["captain_id"])
            start = int(ctx.state["selector_index"])
            for step in range(1, n + 1):
                nxt = (start + step) % n
                if int(order[nxt]) != captain:
                    ctx.state["selector_index"] = nxt
                    return
            ctx.state["selector_index"] = start
            return
        ctx.state["selector_index"] = (int(ctx.state["selector_index"]) + 1) % n

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
        lines.extend(["", f"你的手牌：{display_cards(hand)}"])
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
        else:
            for trick in history:
                play_text = "，".join(
                    f"@{self._nickname(ctx, int(play['player']))} {display_card(str(play['card']))}"
                    for play in trick.get("plays", [])
                )
                lines.append(
                    f"第 {trick['no']} 墩：{play_text}；赢家 @{self._nickname(ctx, int(trick['winner']))}"
                )
        # campaign + 无难度关时追加约束校验结果（只提示，胜负由玩家确认）
        violation = self._check_no_difficulty_constraints(ctx)
        if violation is not None:
            lines.append("")
            lines.append(f"约束校验：💥 {violation}")
        return lines

    async def _persist(self, ctx: GameContext) -> None:
        runner = game_base.get_runner(ctx.session_id)
        if runner is not None:
            await runner.persist()

    async def _end(self, ctx: GameContext, reason: EndReason) -> None:
        runner = game_base.get_runner(ctx.session_id)
        if runner is not None:
            await runner.end(reason)

    async def _advance_campaign_progress(self, ctx: GameContext) -> str | None:
        """推进战役进度，返回结算追加文案；非战役返回 None。"""
        if ctx.state.get("mode") != "campaign":
            return None
        group_id = ctx.group_id
        mission_no = ctx.state.get("mission_no")
        if mission_no is None:
            # Epilogue：难度 +1
            diff = int(ctx.state.get("epilogue_difficulty", EPILOGUE_START_DIFFICULTY))
            next_diff = diff + 1
            await set_group_config(group_id, CAMPAIGN_LEVEL_KEY, f"epilogue:{next_diff}")
            return f"Epilogue 下一难度：{next_diff}"
        mission_no = int(mission_no)
        if mission_no < 32:
            await set_group_config(group_id, CAMPAIGN_LEVEL_KEY, str(mission_no + 1))
            return f"下一关：第 {mission_no + 1} 关"
        await set_group_config(
            group_id, CAMPAIGN_LEVEL_KEY, f"epilogue:{EPILOGUE_START_DIFFICULTY}"
        )
        return f"32 关全部通关！进入 Epilogue（难度 {EPILOGUE_START_DIFFICULTY}）"

    # ------------------------------------------------------------------
    # 无难度关约束校验（M8/12/21/23/27）
    # ------------------------------------------------------------------
    def _check_no_difficulty_constraints(self, ctx: GameContext) -> str | None:
        """无难度关特殊约束校验。返回违规说明，None 表示通过。"""
        if ctx.state.get("mode") != "campaign":
            return None
        no = ctx.state.get("mission", {}).get("no")
        if no == 8:
            return self._check_value_gap(ctx, 9, "9")
        if no == 12:
            return self._check_no_pink_or_sub_lead(ctx)
        if no == 21:
            return self._check_value_gap(ctx, 1, "1")
        if no == 23:
            return self._check_first_winner_always_lead(ctx)
        if no == 27:
            return self._check_yellow5_last(ctx)
        return None

    def _check_value_gap(self, ctx: GameContext, value: int, label: str) -> str | None:
        order = [int(x) for x in ctx.state.get("order", [])]
        counts: list[tuple[int, int]] = []
        for seat in order:
            won = ctx.state.get("won_tricks", {}).get(str(seat), [])
            n = sum(
                1 for t in won for c in t.get("cards", []) if value_of(str(c)) == value
            )
            counts.append((seat, n))
        if len(counts) < 2:
            return None
        hi = max(counts, key=lambda x: x[1])
        lo = min(counts, key=lambda x: x[1])
        if hi[1] - lo[1] >= 2:
            return (
                f"违反约束：@{self._nickname(ctx, hi[0])} 赢得的 {label} 比 "
                f"@{self._nickname(ctx, lo[0])} 多 2 张及以上"
            )
        return None

    def _check_no_pink_or_sub_lead(self, ctx: GameContext) -> str | None:
        for trick in ctx.state.get("trick_history", []):
            first = str(trick["plays"][0]["card"])
            if suit_of(first) in {"pink", "sub"}:
                return (
                    f"违反约束：第 {trick['no']} 墩用 {display_card(first)} 开墩"
                    "（禁止粉牌或潜艇开墩）"
                )
        return None

    def _check_first_winner_always_lead(self, ctx: GameContext) -> str | None:
        history = ctx.state.get("trick_history", [])
        if not history:
            return None
        first_winner = int(history[0]["winner"])
        counts = {int(x): 0 for x in ctx.state.get("order", [])}
        for trick in history:
            counts[int(trick["winner"])] += 1
            fw = counts.get(first_winner, 0)
            for seat, n in counts.items():
                if n > fw:
                    return (
                        f"违反约束：第 {trick['no']} 墩后 @{self._nickname(ctx, seat)}（{n} 墩）"
                        f"超过了首墩赢家 @{self._nickname(ctx, first_winner)}（{fw} 墩）"
                    )
        return None

    def _check_yellow5_last(self, ctx: GameContext) -> str | None:
        history = ctx.state.get("trick_history", [])
        if not history:
            return None
        final_card = str(history[-1]["plays"][-1]["card"])
        if final_card != "yellow:5":
            return f"违反约束：最后一墩的最后一张牌是 {display_card(final_card)}，应为黄5"
        return None
