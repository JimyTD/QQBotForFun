"""静夜标记 · 游戏本体（状态机 + 交互）。

流程（与源项目 GameManager 同构）：

    夜晚 5 步 → 死讯 → 死亡触发链 → 骑士决斗 → 标记发言 → 投票放逐 → 触发链 → 下一轮

**交互模型：命令驱动**。本作删掉了"自由发言"，所以 `event_driven = False`——
一切输入都是被询问的，由 `session.ask` 顺序推进。这条决定了本文件的结构：
没有 `on_player_action`，主循环就是 `_run()` 里的一串 `await`。

**铁律（集中在 `_ask` / `_ask_text`）**：

1. 超时 / 玩家退出 / 私聊不可达 → 一律按"没有输入"处理，调用方**必须**走兜底并
   继续推进，绝不允许原地等待（源项目曾因"兜底也被拒"而卡死整局）；
2. `/结束` 会让等待中的 future 被 `cancel()` → `asyncio.CancelledError` **必须冒泡**，
   它是主循环唯一的正常退出通道，任何地方都不能吞掉它（因此这里不 import asyncio，
   也就无从误捕获）。
3. **信息防火墙**：私有动作（夜间技能、触发技能）的等待一旦出问题，只私聊告知本人，
   **群内一个字都不发**——"X 超时未响应"就等于当众宣布 X 有夜间身份；
   "X 选择不开枪"就等于当众翻牌他是猎人。见 `_ask(sensitive=...)` / `_notify_sensitive`。
"""

from __future__ import annotations

import copy
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from core import game_base, session
from core.errors import PlayerQuitError, WhisperFailedError
from core.errors import TimeoutError as GameTimeoutError
from core.game_base import GameBase, GameContext, GameMode, register_game
from core.types import EndReason

from .ai import controller as ai_controller
from .ai import guard as ai_guard
from .ai import names as ai_names
from .ai import persona as ai_persona
from .ai.logger import AILog

from . import syntax, views
from .config import cfg
from .engine import constants as C  # noqa: N812
from .engine import resolve
from .engine.fallback import fallback_marks, fallback_night_action, fallback_vote
from .engine.roles import create_role, has_voting_right, new_role_state
from .engine.types import (
    DeathRecordDict,
    GameStateDict,
    PlayerDict,
    PlayerMarksDict,
    empty_history,
    empty_night_actions,
    find_player,
)

DEFAULT_PRESET = "4standard"


def _describe_preset(preset: C.PresetConfig) -> str:
    """板子描述：`1 狼人 · 守卫 · 女巫 · 1 平民 · 屠边`。"""
    parts = [
        f"{C.ROLE_LABELS.get(role, role)}×{count}"
        for role, count in preset.roles.items()
        if count
    ]
    win = "屠边" if preset.win_condition == C.WIN_EDGE else "屠城"
    return " · ".join([*parts, win])


def _build_modes() -> list[GameMode]:
    """开局模式 = 板子（12 套预设 + 1 套自定义）。

    权威来源是 `engine.constants.PRESETS`，CLI 与 QQ 菜单共用同一份
    （`docs/13-cli-bot-parity.md`：MODES 只能有一个来源）。

    ⚠️ 自定义**必须排在最后**：`resolve_mode` 支持按编号选模式（"1"/"2"…），
    往中间插一个会静默改变既有编号的含义（玩家的习惯 + 测试都在用）。
    """
    modes: list[GameMode] = []
    for key, preset in C.PRESETS.items():
        label = C.PRESET_LABELS.get(key, key)
        modes.append(
            GameMode(
                id=key,
                name=label,
                description=_describe_preset(preset),
                aliases=(label.replace(" ", ""),),
            )
        )
    modes.append(
        GameMode(
            id="custom",
            name="自定义板子",
            description="逐位落座配角色 + 胜负条件 + 物品开关",
            aliases=("自定义", "custom", "自选"),
        )
    )
    return modes


@dataclass
class Outcome:
    """一次"等待 + 解析"的结果。"""

    kind: str = "abort"  # ok | skip | bad | abort
    value: Any = None
    problems: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.kind in ("ok", "skip")


@register_game
class SilentMarkGame(GameBase):
    id = "silent_mark"
    #: 每局一份 AI 决策日志（键是 session_id；不放进 ctx.state：
    #: 它是要落盘的对象，塞进状态会污染 JSON 往返）
    _ai_logs: ClassVar[dict[str, AILog]] = {}
    name = "静夜标记"
    description = "无发言狼人杀：用标记代替发言，标注身份与立场"
    emoji = "🌙"
    min_players = C.MIN_PLAYERS
    max_players = C.MAX_PLAYERS
    version = "0.1.0"
    MODES = _build_modes()

    # =================================================================
    # 生命周期
    # =================================================================
    async def on_create(self, ctx: GameContext) -> None:
        settings = self._build_settings(ctx)
        seed = ctx.config.get("seed")
        rng = random.Random(seed) if seed is not None else random.Random()
        players = self._assign_players(ctx, settings, rng)

        ctx.state.update(
            {
                "status": "playing",
                "round": 1,
                "phase": C.PHASE_NIGHT,
                "players": players,
                "night_actions": empty_night_actions(),
                "night_current_role": None,
                "marking_order": [],
                "marking_current": 0,
                "pending_triggers": [],
                "history": empty_history(),
                "winner": None,
                "end_reason_code": None,
                "win_condition": settings["win_condition"],
                "settings": settings,
                "seat_owners": self._build_seat_owners(ctx),
                # 消息生命周期（见下方"消息生命周期"一节）：群里只有看板 + 一条提问
                "board_message_id": None,
                "prompt_message_id": None,
                "private_prompt_ids": {},
            }
        )

    async def on_start(self, ctx: GameContext) -> None:
        await self._setup_ai_seats(ctx)
        failed = await self._whisper_role_cards(ctx)
        if failed:
            names = "、".join(f"@{name}" for name in failed)
            await session.broadcast(
                ctx.group_id,
                "⚠️ 身份牌私聊失败：" + names + " 还没添加机器人为好友，无法开局。\n"
                "请先点机器人头像「添加好友」，加好后 @我 静夜标记 重新开局。",
            )
            runner = game_base.get_runner(ctx.session_id)
            if runner is not None:
                await runner.end(EndReason.ERROR)
            return

        # 开局那一次带上板子与胜负条件；之后看板只显示状态（不在群里重复念规则）
        await self._refresh_board(ctx, show_rules=True)
        await self._persist(ctx)
        await self._run(ctx)

    async def on_timeout(self, ctx: GameContext) -> None:
        await self._announce(ctx, "⏰ 本局静夜标记超时，已自动结束。")

    async def on_end(self, ctx: GameContext, reason: EndReason) -> None:
        st: GameStateDict = ctx.state
        # 收尾时撤掉群里那条提问与所有私聊提示；身份牌留着（复盘要用）
        await self._clear_prompts(ctx)
        await self._delete_state_message(ctx, "board_message_id")
        if reason == EndReason.COMPLETED:
            verdict = {
                "winner": st.get("winner"),
                "reason": st.get("end_reason_code") or "",
            }
            await self._announce(ctx, views.render_game_over(st, verdict))
            await self._award(ctx)
        elif reason != EndReason.ERROR:
            await self._announce(ctx, views.render_aborted(st, reason.value))

    def replay_pages(self, ctx: GameContext) -> list[str]:
        """复盘全文（一页一轮）。对局结束后才写真实死因，见 `views.render_replay`。"""
        return views.render_replay(
            ctx.state,
            ctx.state.get("settings") or {},
            reveal_all=bool(ctx.state.get("winner")),
        )

    async def repost_board(self, ctx: GameContext) -> None:
        """`@我 面板`：把群里的对局面板重新贴一遍（常驻那条被刷走/被撤回时用）。"""
        await self._refresh_board(ctx)

    def in_game_hint(self, ctx: GameContext) -> str:
        """@机器人 但没听懂时的情境提示。

        ⚠️ 别在这里推荐 `@我 认输`：它是全局「结束」命令的别名（`game_launcher`），
        会**终止整局**。只想自己出局请回复「退出」（只影响自己）。
        """
        return (
            "🎮 静夜标记进行中\n"
            "💡 按机器人提示回复；@我 记录 查看你的身份与私有记录\n"
            "💡 只想自己提前出局：回复「退出」（别人继续打）\n"
            "💡 想收掉整局：@我 结束（任何人都可以，不需要房主）"
        )

    # =================================================================
    # 供 commands.py 调用
    # =================================================================
    async def resign(
        self, ctx: GameContext, pid: str, *, reason_text: str = "认输"
    ) -> bool:
        """主动出局。**像其它出局路径一样公开遗物**（源项目 502ef26 的教训）。"""
        st: GameStateDict = ctx.state
        if st.get("status") != "playing":
            return False
        player = find_player(st, pid)
        if player is None or not player["alive"]:
            return False

        record = resolve.record_death(st, player, C.DEATH_RESIGNED)
        st["history"]["deaths"].append(record)
        await self._announce(
            ctx,
            views.render_death_notice(
                st, record, headline=f"🏳 {self._label(ctx, pid)} {reason_text}"
            ),
        )
        await self._persist(ctx)
        # ⚠️ 认输**不触发任何技能**。这是源项目 `GameManager.handleResign` 的明示意图：
        #   「玩家认输退出：视为死亡（不触发猎人/狼王等任何技能）、豁免正在等待的行动、检查胜负」
        # 认输是主动弃权，不能反过来当成一次"死亡触发"去开枪/带人。
        # （M2 我一度按"死亡链对任何出局方式一视同仁"改成会触发 —— 那是对源项目
        #   规则的偏离，核对 handleResign 后已改回，并由
        #   `test_resigning_hunter_does_not_shoot` 锁死。）
        await self._check_win(ctx)
        return True

    def my_records(self, ctx: GameContext, pid: str) -> str:
        player = find_player(ctx.state, pid)
        if player is None:
            return "你不是本局玩家。"
        return views.render_my_records(ctx.state, player)

    def pid_of(self, ctx: GameContext, qq: int) -> str | None:
        """某个 QQ 控制着哪个座位（`@我 记录` 用；调试座位也认）。"""
        return self._pid_by_controller(ctx, qq)

    # =================================================================
    # 主循环
    # =================================================================
    async def _run(self, ctx: GameContext) -> None:
        st: GameStateDict = ctx.state
        while st["status"] == "playing":
            await self._run_night(ctx)
            if st["status"] != "playing":
                return
            await self._run_marking(ctx)
            if st["status"] != "playing":
                return
            await self._run_voting(ctx)
            if st["status"] != "playing":
                return
            st["round"] += 1
            await self._persist(ctx)

    # =================================================================
    # 夜晚
    # =================================================================
    async def _run_night(self, ctx: GameContext) -> None:
        st: GameStateDict = ctx.state
        st["phase"] = C.PHASE_NIGHT
        st["night_actions"] = empty_night_actions()
        st["night_current_role"] = None
        # 天黑不是"新消息"，而是看板原地翻到夜晚那一段
        await self._refresh_board(ctx)

        for role_name in C.NIGHT_ACTION_ORDER:
            if st["status"] != "playing":
                return
            actors = self._night_actors(st, role_name)
            if not actors:
                continue
            if role_name == C.WEREWOLF:
                await self._wolf_discussion(ctx, actors)
            else:
                for player in actors:
                    if st["status"] != "playing":
                        return  # 期间认输可能已直接终局，不能再往下走
                    if not player["alive"]:
                        continue  # 前一个角色行动期间认输的人，不该再被问夜晚行动
                    st["night_current_role"] = role_name
                    await self._single_night_action(ctx, player, role_name)

        if st["status"] != "playing":
            return
        deaths = resolve.resolve_night(st)
        st["history"]["rounds"].append(copy.deepcopy(st["night_actions"]))
        st["history"]["deaths"].extend(deaths)
        st["night_current_role"] = None
        st["phase"] = C.PHASE_DAY_ANNOUNCEMENT
        # 死讯是**关键事件**：单独占一条（看板会被下一次更新覆盖，死讯必须能翻回去看）
        await self._announce(ctx, views.render_night_result(st, deaths))
        await self._refresh_board(ctx)
        await self._persist(ctx)
        await self._run_triggers(ctx, deaths)
        if st["status"] != "playing":
            return
        # 骑士决斗：死讯与触发链之后、标记发言之前（源项目顺序）
        await self._run_knight(ctx)

    def _night_actors(self, st: GameStateDict, role_name: str) -> list[PlayerDict]:
        if role_name == C.WEREWOLF:
            return [p for p in st["players"] if p["alive"] and p["role"] in C.WOLF_ROLES]
        return [p for p in st["players"] if p["alive"] and p["role"] == role_name]

    async def _single_night_action(
        self, ctx: GameContext, player: PlayerDict, role_name: str
    ) -> None:
        st: GameStateDict = ctx.state
        role_impl = create_role(player["role"])
        allowed = role_impl.get_available_targets(st, player)

        # 守墓人当夜无死者 → 自动跳过（源项目同样不打搅玩家）
        if role_name == C.GRAVEDIGGER and not allowed:
            role_impl.perform_night_action(st, player)
            return

        if role_name == C.WITCH:
            role_state = player["role_state"]
            # 两瓶药都用完 → 直接跳过，不问
            if role_state.get("antidote_used") and role_state.get("poison_used"):
                role_impl.perform_night_action(st, player, potion="none")
                return
            outcome = await self._ask_text(
                ctx,
                player["pid"],
                syntax.render_witch_prompt(
                    st, player["pid"], victim_pid=self._wolf_target(st)
                ),
                channel="private",
                timeout=None,
                parse=self._witch_parser(st, allowed),
                ai_kind="night",
                ai_targets=allowed,
            )
            accepted = False
            if outcome.kind == "ok":
                value = outcome.value or {}
                accepted = role_impl.perform_night_action(
                    st, player, target=value.get("target"), potion=value.get("potion")
                )
        else:
            outcome = await self._ask_text(
                ctx,
                player["pid"],
                syntax.render_target_prompt(
                    st,
                    player["pid"],
                    self._night_prompt_kind(player["role"]),
                    allowed_pids=allowed,
                ),
                channel="private",
                timeout=None,
                parse=self._target_parser(st, allowed),
                ai_kind="night",
                ai_targets=allowed,
            )
            accepted = outcome.usable and role_impl.perform_night_action(
                st, player, target=outcome.value
            )

        if not accepted:
            await self._apply_night_fallback(ctx, player)

    @staticmethod
    def _night_prompt_kind(role: str) -> str:
        if role in C.WOLF_ROLES:
            return "wolves"
        if role == C.SEER:
            return "seer"
        if role == C.GRAVEDIGGER:
            return "gravedigger"
        return "guard"

    @staticmethod
    def _wolf_target(st: GameStateDict) -> str | None:
        wolves = st["night_actions"].get("wolves")
        return wolves.get("target") if wolves else None

    async def _wolf_discussion(
        self, ctx: GameContext, wolves: list[PlayerDict]
    ) -> None:
        """狼人合议：逐狼私聊选择，并把"当前队友意向"告诉后面的狼。

        QQ 侧没有实时同步，用"逐个收集 + 告知已收集意向"等价替代（计划 §5 第 5 条）。
        """
        st: GameStateDict = ctx.state
        st["night_current_role"] = C.WEREWOLF
        role_impl = create_role(C.WEREWOLF)
        consensus: list[str] = []

        for wolf in wolves:
            if st["status"] != "playing":
                return  # 认输可能中途终局
            if not wolf["alive"]:
                continue  # 前面的狼表态期间有人认输，别再问死者
            allowed = role_impl.get_available_targets(st, wolf)
            extra: list[str] = []
            if len(wolves) > 1:
                if consensus:
                    labels = "、".join(
                        dict.fromkeys(syntax.player_label(st, p) for p in consensus)
                    )
                    extra = [f"🐺 队友当前意向：{labels}"]
                else:
                    extra = ["🐺 队友还没有表态"]

            outcome = await self._ask_text(
                ctx,
                wolf["pid"],
                syntax.render_target_prompt(
                    st, wolf["pid"], "wolves", allowed_pids=allowed, extra_lines=extra
                ),
                channel="private",
                timeout=None,  # 真人永远不超时；AI 的预算由 _ask_text 内部按 ai_kind 取
                parse=self._target_parser(st, allowed),
                ai_kind="night",
                ai_targets=allowed,
            )
            if outcome.usable:
                role_impl.perform_night_action(st, wolf, target=outcome.value)
            else:
                await self._apply_night_fallback(ctx, wolf)

            votes = (st["night_actions"].get("wolves") or {}).get("votes") or {}
            if wolf["pid"] in votes:
                consensus.append(votes[wolf["pid"]])

        await self._persist(ctx)

    async def _apply_night_fallback(self, ctx: GameContext, player: PlayerDict) -> None:
        """兜底：拿不到合法行动就跳过——**绝不原地等待**。"""
        st: GameStateDict = ctx.state
        if not player["alive"]:
            # 认输/被技能带走之后不该再产生夜间行动，否则"死人还能守护/查验"
            return
        role_impl = create_role(player["role"])
        allowed = role_impl.get_available_targets(st, player)
        action = fallback_night_action(player["role"], allowed)
        if action is None:
            # 私密：这句公开说等于承认"这个座位本夜被问过"（= 有夜间身份）
            await self._notify_sensitive(
                ctx, player["pid"], "🌙 本夜你没有可用目标，已自动跳过。"
            )
            return
        role_impl.perform_night_action(
            st, player, target=action.get("target"), potion=action.get("potion")
        )

    # =================================================================
    # 死亡触发链（猎人开枪 / 白狼王带人）
    # =================================================================
    async def _run_triggers(
        self, ctx: GameContext, deaths: list[DeathRecordDict]
    ) -> None:
        """跑死亡触发链。

        触发来源：被刀 / 被放逐 / 被毒 / 被决斗 / 被白狼王带走。
        ⚠️ **认输不算**——源项目 `handleResign` 明确规定"认输不触发任何技能"
        （见 `resign()` 里的说明）。
        """
        st: GameStateDict = ctx.state
        pending: list[dict[str, Any]] = []
        for death in deaths:
            player = find_player(st, death["pid"])
            if player is None:
                continue
            trigger = create_role(player["role"]).on_death(st, player, death["cause"])
            if trigger:
                pending.append(trigger)

        if not pending:
            await self._check_win(ctx)
            return

        st["pending_triggers"] = pending
        st["phase"] = C.PHASE_DAY_TRIGGER
        await self._refresh_board(ctx)

        while st["pending_triggers"] and st["status"] == "playing":
            trigger = st["pending_triggers"].pop(0)
            new_deaths = await self._resolve_trigger(ctx, trigger)
            # 技能造成的死亡可能再次触发；新触发插入队首（源项目行为）
            for death in new_deaths:
                actor = find_player(st, death["pid"])
                if actor is None:
                    continue
                sub = create_role(actor["role"]).on_death(st, actor, death["cause"])
                if sub:
                    st["pending_triggers"].insert(0, sub)
            await self._persist(ctx)
            if await self._check_win(ctx):
                return

    async def _resolve_trigger(
        self, ctx: GameContext, trigger: dict[str, Any]
    ) -> list[DeathRecordDict]:
        pid = trigger.get("pid")
        st: GameStateDict = ctx.state
        actor = find_player(st, pid) if pid else None
        if actor is None:
            return []

        trigger_type = trigger.get("type")
        if trigger_type == "hunter_shoot":
            return await self._hunter_shoot(ctx, actor)
        if trigger_type == "wolf_king_drag":
            return await self._wolf_king_drag(ctx, actor)
        return []

    async def _hunter_shoot(
        self, ctx: GameContext, actor: PlayerDict
    ) -> list[DeathRecordDict]:
        st: GameStateDict = ctx.state
        if not actor["role_state"].get("can_shoot"):
            return []
        allowed = [
            p["pid"] for p in st["players"] if p["alive"] and p["pid"] != actor["pid"]
        ]
        outcome = await self._ask_text(
            ctx,
            actor["pid"],
            syntax.render_target_prompt(
                st, actor["pid"], "hunter_shoot", allowed_pids=allowed, allow_skip=True
            ),
            channel="private",
            timeout=None,  # 真人永远不超时
            parse=self._target_parser(st, allowed, allow_skip=True),
            ai_kind="trigger",
            ai_targets=allowed,
        )
        actor["role_state"]["can_shoot"] = False

        if outcome.kind == "skip":
            # 私密确认：公开"选择不开枪"等于当众给这个座位翻牌"他是猎人"
            await self._notify_sensitive(ctx, actor["pid"], "🔫 你选择不开枪。")
            return []
        if not outcome.usable:
            return []
        return await self._apply_kill(
            ctx, outcome.value, C.DEATH_SHOT, f"🔫 {self._label(ctx, actor['pid'])} 开枪"
        )

    async def _wolf_king_drag(
        self, ctx: GameContext, actor: PlayerDict
    ) -> list[DeathRecordDict]:
        st: GameStateDict = ctx.state
        allowed = [
            p["pid"] for p in st["players"] if p["alive"] and p["pid"] != actor["pid"]
        ]
        outcome = await self._ask_text(
            ctx,
            actor["pid"],
            syntax.render_target_prompt(
                st, actor["pid"], "wolf_king_drag", allowed_pids=allowed, allow_skip=True
            ),
            channel="private",
            timeout=None,  # 真人永远不超时
            parse=self._target_parser(st, allowed, allow_skip=True),
            ai_kind="trigger",
            ai_targets=allowed,
        )
        if outcome.kind == "skip":
            # 同猎人：公开"选择不带人"= 当众翻牌"这个座位是白狼王"
            await self._notify_sensitive(ctx, actor["pid"], "👑 你选择不带人。")
            return []
        if not outcome.usable:
            return []
        return await self._apply_kill(
            ctx,
            outcome.value,
            C.DEATH_WOLF_KING_DRAG,
            f"👑 {self._label(ctx, actor['pid'])} 带走",
        )

    async def _apply_kill(
        self, ctx: GameContext, victim_pid: str, cause: str, headline: str
    ) -> list[DeathRecordDict]:
        st: GameStateDict = ctx.state
        victim = find_player(st, victim_pid)
        if victim is None or not victim["alive"]:
            return []
        record = resolve.record_death(st, victim, cause)
        st["history"]["deaths"].append(record)
        await session.broadcast(
            ctx.group_id, views.render_death_notice(st, record, headline=headline)
        )
        return [record]

    # =================================================================
    # 骑士决斗（白天，标记发言前）
    # =================================================================
    async def _run_knight(self, ctx: GameContext) -> None:
        st: GameStateDict = ctx.state
        knight = next(
            (p for p in st["players"] if p["alive"] and p["role"] == C.KNIGHT), None
        )
        if knight is None or knight["role_state"].get("duel_used"):
            return

        st["phase"] = C.PHASE_DAY_KNIGHT
        allowed = [
            p["pid"] for p in st["players"] if p["alive"] and p["pid"] != knight["pid"]
        ]
        outcome = await self._ask_text(
            ctx,
            knight["pid"],
            syntax.render_target_prompt(
                st, knight["pid"], "knight_duel", allowed_pids=allowed, allow_skip=True
            ),
            channel="private",
            timeout=None,  # 真人永远不超时
            parse=self._target_parser(st, allowed, allow_skip=True),
            ai_kind="trigger",
            ai_targets=allowed,
        )
        if outcome.kind == "skip":
            # 私密确认；骑士每天都会被问一次，不给回执玩家会以为输入没生效
            await self._notify_sensitive(ctx, knight["pid"], "⚔️ 你选择不决斗。")
            return
        if not outcome.usable:
            return

        knight["role_state"]["duel_used"] = True
        target = find_player(st, outcome.value)
        if target is None or not target["alive"]:
            return
        loser = target if target["faction"] == C.EVIL else knight
        record = resolve.record_death(st, loser, C.DEATH_DUEL)
        st["history"]["deaths"].append(record)
        await session.broadcast(
            ctx.group_id,
            views.render_death_notice(
                st,
                record,
                headline=(
                    f"⚔️ {self._label(ctx, knight['pid'])} 决斗 "
                    f"{self._label(ctx, target['pid'])}"
                ),
            ),
        )
        await self._persist(ctx)
        await self._run_triggers(ctx, [record])

    # =================================================================
    # 标记发言
    # =================================================================
    async def _run_marking(self, ctx: GameContext) -> None:
        st: GameStateDict = ctx.state
        alive_sorted = sorted(
            [p for p in st["players"] if p["alive"]], key=lambda p: p["seat"]
        )
        st["phase"] = C.PHASE_DAY_MARKING
        st["marking_order"] = [p["pid"] for p in alive_sorted]
        st["marking_current"] = 0
        await self._refresh_board(ctx)

        for pid in list(st["marking_order"]):
            if st["status"] != "playing":
                return
            player = find_player(st, pid)
            if player is None or not player["alive"]:
                continue  # 期间认输/出局的跳过

            if self._is_ai(ctx, pid):
                # AI 的标记不走文本解析（结构化的东西没必要来回编码），
                # 但**同样过规则层校验**：`controller.marking` 里会调
                # `resolve.validate_player_marks`，被拒就重试、再不行走兜底。
                marks = await ai_controller.with_budget(
                    ai_controller.marking(
                        state=st,
                        pid=pid,
                        budget=cfg.ai_marking_timeout,
                        log=self._ai_log(ctx),
                    ),
                    budget=cfg.ai_marking_timeout,
                    log=self._ai_log(ctx),
                    kind="marking",
                    pid=pid,
                )
            else:
                marks = await self._collect_marks(ctx, pid)
            if marks is None:
                # 认输可能就发生在这次提问里 → 已出局的人不该再"被默认标记"
                latest = find_player(st, pid)
                if latest is None or not latest["alive"]:
                    st["marking_current"] += 1
                    continue
                marks = fallback_marks(st, pid)
                if marks is None:
                    await self._announce(
                        ctx, f"⚠️ {self._label(ctx, pid)} 未能提交标记，本轮跳过。"
                    )
                    st["marking_current"] += 1
                    continue
                await self._announce(
                    ctx, f"（{self._label(ctx, pid)} 的标记未完成，已按默认标记处理）"
                )

            st["history"]["marks"].append(marks)
            st["marking_current"] += 1
            # 标记结果**不再单独发一条**：直接进看板。于是 N 个人发言只换来
            # 一条不断更新的板子，而不是 N 条播报（这就是"不刷屏"的关键）。
            await self._refresh_board(ctx)
            await self._persist(ctx)

    async def _collect_marks(self, ctx: GameContext, pid: str) -> PlayerMarksDict | None:
        st: GameStateDict = ctx.state
        first_time = not (st.get("history", {}).get("marks") or [])

        async def parse(text: str) -> Outcome:
            result = syntax.parse_marks(text, st, pid)
            if result.needs_guide:
                guided = await self._guided_marks(ctx, pid)
                if guided is None:
                    return Outcome(kind="abort")
                return Outcome(kind="ok", value=guided)
            if result.problems:
                return Outcome(kind="bad", problems=result.problems)
            problems = resolve.validate_player_marks(st, pid, result.marks)
            if problems:
                return Outcome(kind="bad", problems=problems)
            return Outcome(kind="ok", value=result.marks)

        outcome = await self._ask_text(
            ctx,
            pid,
            syntax.render_mark_prompt(st, pid, at_prefix=True, first_time=first_time),
            channel="group",
            timeout=cfg.ai_marking_timeout,
            parse=parse,
        )
        if outcome.kind == "bad":
            await self._announce(
                ctx,
                f"⚠️ {self._label(ctx, pid)} 的标记多次未通过校验，已按默认标记处理。",
            )
        if outcome.kind == "ok":
            # 玩家自己的指令消息用完即撤回（群里不留原始命令）
            await self._delete_user_input(ctx, self._controller(ctx, pid))
            return outcome.value
        return None

    async def _guided_marks(
        self, ctx: GameContext, pid: str
    ) -> PlayerMarksDict | None:
        """引导式标记：逐项 choose，与一行式产出**同样的状态**。

        为了不让玩家点太多轮，评价理由也单独问一次（保证两条路径能力等价）。
        """
        st: GameStateDict = ctx.state
        qq = self._controller(ctx, pid)
        if qq is None:
            return None

        # 引导全程走**私聊**：群里只有"看板 + 关键公告"，不该被问答刷屏。
        # 超时同样只对 AI 生效（真人永远等）。
        guidance_timeout = None if not self._is_ai(ctx, pid) else cfg.ai_marking_timeout

        async def ask_choice(options: list[str], prompt: str) -> int | None:
            try:
                return await session.choose(
                    qq,
                    options,
                    group_id=None,
                    timeout=guidance_timeout,
                    prompt=prompt,
                )
            except (
                GameTimeoutError,
                PlayerQuitError,
                WhisperFailedError,
                # ⚠️ `choose` 的重试次数用尽时会抛 ValueError（`ask` 的 validator 路径），
                # 不接住它 = 玩家连续答错就把整局崩掉。
                ValueError,
            ):
                return None

        identities = resolve.get_available_identities(st)
        index = await ask_choice(identities, "引导：请选择你要声明的身份")
        if index is None:
            return None
        identity = identities[index]

        reasons = [
            reason
            for reason in (*C.COMMON_REASONS, *C.SPECIAL_REASONS)
            if resolve.is_mark_reason_allowed_for_identity(identity, reason)
        ]
        index = await ask_choice(
            [C.REASON_LABELS[reason] for reason in reasons], "引导：请选择声明身份的理由"
        )
        if index is None:
            return None
        identity_reason = reasons[index]

        eval_identities = resolve.get_available_eval_identities(st)
        others = [p for p in st["players"] if p["alive"] and p["pid"] != pid]
        alive_count = len([p for p in st["players"] if p["alive"]])
        need = min(resolve.get_evaluation_mark_count(alive_count), len(others))

        evaluations: list[dict[str, str]] = []
        used: set[str] = set()
        for _ in range(need):
            remaining = [p for p in others if p["pid"] not in used]
            if not remaining:
                break
            index = await ask_choice(
                [f"{p['seat']}号 {p['nickname']}" for p in remaining],
                "引导：请选择要评价的玩家",
            )
            if index is None:
                return None
            target = remaining[index]
            used.add(target["pid"])

            index = await ask_choice(eval_identities, f"引导：{target['seat']} 号是什么身份")
            if index is None:
                return None
            eval_identity = eval_identities[index]

            index = await ask_choice(
                [C.REASON_LABELS[reason] for reason in reasons],
                f"引导：评价 {target['seat']} 号的理由",
            )
            if index is None:
                return None
            evaluations.append(
                {
                    "target": target["pid"],
                    "identity": eval_identity,
                    "reason": reasons[index],
                }
            )

        return {
            "player": pid,
            "round": st["round"],
            "identity_mark": {"identity": identity, "reason": identity_reason},
            "evaluation_marks": evaluations,
        }

    # =================================================================
    # 投票放逐
    # =================================================================
    async def _run_voting(self, ctx: GameContext) -> None:
        st: GameStateDict = ctx.state
        st["phase"] = C.PHASE_DAY_VOTING
        # 按座位顺序征求（源项目同序）；顺序固定，回放与复盘才不会飘
        voters = sorted(
            [p for p in st["players"] if p["alive"] and has_voting_right(p)],
            key=lambda p: p["seat"],
        )
        # 标记阶段那条提问到此为止，别让它杵在群里
        await self._delete_state_message(ctx, "prompt_message_id")
        await self._refresh_board(ctx, extra_lines=[self._vote_progress_line(0, len(voters))])

        votes: list[dict[str, str]] = []
        for voter in voters:
            if st["status"] != "playing":
                return
            if not voter["alive"]:
                continue
            allowed = [
                p["pid"] for p in st["players"] if p["alive"] and p["pid"] != voter["pid"]
            ]
            outcome = await self._ask_text(
                ctx,
                voter["pid"],
                syntax.render_target_prompt(
                    st, voter["pid"], "vote", allowed_pids=allowed
                ),
                channel="private",
                timeout=None,
                parse=self._target_parser(st, allowed),
                # 显式豁免：投票权是公开信息，出问题时点名催促无害（唯一的私聊非敏感等待）
                sensitive=False,
                ai_kind="vote",
                ai_targets=allowed,
            )
            target = outcome.value if outcome.usable else None
            if target is None:
                target = fallback_vote(allowed, voter["pid"])
            if target is None:
                continue  # 没有可投目标 → 就是弃票，看板里看得到，不必单独公告
            votes.append({"voter": voter["pid"], "target": target})
            # ⚠️ 这里**刻意不发**「✅ X 已投票」：那是纯粹的废话（投票明细最后会一次性公布）。
            # 进度通过看板原地更新表达。
            await self._refresh_board(
                ctx, extra_lines=[self._vote_progress_line(len(votes), len(voters))]
            )

        st["history"]["votes"].append(votes)
        result = resolve.resolve_voting(votes)
        await self._announce(ctx, views.render_vote_detail(st, votes, result))
        await self._persist(ctx)

        exiled = result.get("exiled")
        if exiled:
            await self._exile(ctx, exiled)
        else:
            await session.broadcast(ctx.group_id, "⚖️ 本轮无人被放逐。")

    async def _exile(self, ctx: GameContext, pid: str) -> None:
        st: GameStateDict = ctx.state
        player = find_player(st, pid)
        if player is None or not player["alive"]:
            return

        role_impl = create_role(player["role"])
        if role_impl.on_exile(st, player):
            await session.broadcast(ctx.group_id, views.render_fool_immunity(st, pid))
            await self._persist(ctx)
            await self._check_win(ctx)
            return

        record = resolve.record_death(st, player, C.DEATH_EXILED)
        st["history"]["deaths"].append(record)
        await session.broadcast(ctx.group_id, views.render_exile(st, record))
        await self._persist(ctx)
        await self._run_triggers(ctx, [record])

    # =================================================================
    # 胜负与结算
    # =================================================================
    async def _check_win(self, ctx: GameContext) -> bool:
        st: GameStateDict = ctx.state
        verdict = resolve.check_win_condition(st, st.get("win_condition", C.WIN_EDGE))
        if verdict is None:
            return False
        st["status"] = "finished"
        st["phase"] = C.PHASE_GAME_OVER
        st["winner"] = verdict["winner"]
        st["end_reason_code"] = verdict["reason"]
        await self._persist(ctx)
        runner = game_base.get_runner(ctx.session_id)
        if runner is not None:
            await runner.end(EndReason.COMPLETED)
        return True

    async def _award(self, ctx: GameContext) -> None:
        """发奖。同一 QQ 控制多个座位时只发一次（调试座位去重）。"""
        st: GameStateDict = ctx.state
        winner = st.get("winner")
        rewarded: set[int] = set()
        for player in st["players"]:
            qq = self._controller(ctx, player["pid"])
            if qq is None or qq in rewarded:
                continue
            rewarded.add(qq)
            won = player["faction"] == winner
            tag = "win" if won else "lose"
            await self.award(
                qq,
                cfg.win_coin if won else cfg.lose_coin,
                reason=f"silent_mark_{tag}:{ctx.session_id}",
                currency="coin",
            )
            await self.award(
                qq,
                cfg.win_score if won else cfg.lose_score,
                reason=f"silent_mark_{tag}:{ctx.session_id}",
                currency="score",
            )

    # =================================================================
    # 消息生命周期（对齐 `deep_sea_mission`：让群友不觉得刷屏）
    # =================================================================
    #
    # 群里只允许两类东西：
    #   ① **对局面板**——一条消息，状态变了原地更新（删旧发新），所有状态都塞进去；
    #   ② **独立事件公告**——死讯 / 开枪 / 放逐 / 结果 / 结算，值得单独回看。
    # 另外：
    #   · 当前提问群里同时只有一条，下一个人开始时旧提问被撤回；
    #   · 玩家自己的指令消息**发完就撤回**（群里不留原始命令）；
    #   · 私聊里每个座位只留最新一条提示（身份牌单独占一条，不受影响）。
    async def _delete_state_message(self, ctx: GameContext, key: str) -> None:
        message_id = ctx.state.get(key)
        if message_id is None:
            return
        await session.delete_message(int(message_id))
        ctx.state[key] = None

    async def _set_board(self, ctx: GameContext, text: str) -> None:
        """对局面板：**原地更新**，不新增群消息。"""
        await self._delete_state_message(ctx, "board_message_id")
        ctx.state["board_message_id"] = await session.broadcast(ctx.group_id, text)

    async def _set_prompt(self, ctx: GameContext, text: str, *, at: int | None = None) -> None:
        """当前提问：群里**同时只留一条**，新问题发出前先撤回旧问题。"""
        await self._delete_state_message(ctx, "prompt_message_id")
        ctx.state["prompt_message_id"] = await session.broadcast(ctx.group_id, text, at=at)

    async def _set_private_prompt(self, ctx: GameContext, qq: int, text: str) -> None:
        """私聊提示：每个座位只留最新一条。"""
        prompts: dict[str, int] = ctx.state.setdefault("private_prompt_ids", {})
        old = prompts.get(str(qq))
        if old is not None:
            await session.delete_message(int(old))
        new = await session.whisper(qq, text)
        if new is None:
            prompts.pop(str(qq), None)
        else:
            prompts[str(qq)] = new

    async def _clear_prompts(self, ctx: GameContext) -> None:
        """收尾：撤回群里那条提问 + 所有私聊提示。身份牌保留（便于复盘）。"""
        await self._delete_state_message(ctx, "prompt_message_id")
        prompts: dict[str, int] = ctx.state.get("private_prompt_ids") or {}
        for message_id in list(prompts.values()):
            await session.delete_message(int(message_id))
        prompts.clear()

    async def _delete_user_input(self, ctx: GameContext, qq: int | None) -> None:
        """撤回玩家自己的指令消息（群里不留原始命令）——深海任务的同款做法。"""
        if qq is None:
            return
        message_id = session.last_routed_message_id(ctx.session_id, qq)
        if message_id is not None:
            await session.delete_message(message_id)

    async def _announce(self, ctx: GameContext, text: str) -> None:
        """独立事件公告：值得在群里单独占一条、并让玩家日后能翻回去看。"""
        await session.broadcast(ctx.group_id, text)

    async def _refresh_board(
        self,
        ctx: GameContext,
        *,
        show_rules: bool = False,
        extra_lines: list[str] | None = None,
    ) -> None:
        """按当前状态重画对局面板（原地更新）。"""
        st: GameStateDict = ctx.state
        await self._set_board(
            ctx,
            views.render_board(
                st,
                st.get("settings") or {},
                headline=self._board_headline(ctx),
                tail_lines=extra_lines,
                show_rules=show_rules,
            ),
        )

    def _board_headline(self, ctx: GameContext) -> str:
        """看板第一行：现在是第几轮、什么阶段、轮到谁。"""
        st: GameStateDict = ctx.state
        phase = st.get("phase")
        day = f"第 {st['round']} 轮"
        if phase == C.PHASE_NIGHT:
            return f"🌙 静夜标记 · {day} · 天黑请闭眼"
        if phase == C.PHASE_DAY_ANNOUNCEMENT:
            return f"☀️ 静夜标记 · {day} · 天亮了"
        if phase == C.PHASE_DAY_TRIGGER:
            return f"☀️ 静夜标记 · {day} · 技能结算中"
        if phase == C.PHASE_DAY_KNIGHT:
            return f"☀️ 静夜标记 · {day} · 骑士决斗"
        if phase == C.PHASE_DAY_MARKING:
            order: list[str] = st.get("marking_order") or []
            index = int(st.get("marking_current") or 0)
            total = len(order)
            if index < total:
                return (
                    f"📝 静夜标记 · {day} · 标记发言（{index}/{total}）"
                    f" · 轮到 {syntax.player_label(st, order[index])}"
                )
            return f"📝 静夜标记 · {day} · 标记发言（{total}/{total}）"
        if phase == C.PHASE_DAY_VOTING:
            return f"🗳 静夜标记 · {day} · 投票放逐"
        return f"🌙 静夜标记 · {day}"

    @staticmethod
    def _vote_progress_line(received: int, total: int) -> str:
        return f"🗳 投票：已收 {received}/{total}（收齐后一次性公布明细）"

    # =================================================================
    # 超时原则：AI 有超时，真实玩家没有
    # =================================================================
    @staticmethod
    def _is_ai(ctx: GameContext, pid: str) -> bool:
        """该座位是不是 AI 补位；真人永远 False。"""
        player = find_player(ctx.state, pid)
        return bool(player and player.get("ai"))

    # =================================================================
    # AI 补位座位（M4）
    # =================================================================
    @staticmethod
    def _ai_budget(kind: str) -> float:
        """AI 座位的单步预算（**真人永远不传这个**，见 `_ask` 的超时原则）。"""
        if kind == "vote":
            return cfg.ai_voting_timeout
        if kind == "trigger":
            return cfg.ai_trigger_timeout
        return cfg.ai_night_timeout

    def _ai_log(self, ctx: GameContext) -> AILog:
        """每局一份 AI 决策日志（惰性创建，同一局复用）。"""
        log = self._ai_logs.get(ctx.session_id)
        if log is None:
            log = AILog(ctx.session_id)
            log.rotate()
            self._ai_logs[ctx.session_id] = log
        return log

    @staticmethod
    def _seat_text(ctx: GameContext, pid: str | None) -> str | None:
        """pid → 座位号文本。AI 的决策要转成**和真人一样的输入**再往下走。"""
        if pid is None:
            return None
        player = find_player(ctx.state, pid)
        return str(player["seat"]) if player else None

    async def _ai_text(
        self,
        ctx: GameContext,
        pid: str,
        *,
        kind: str,
        targets: list[str],
        budget: float,
    ) -> str | None:
        """让 AI 做一次决策，返回**座位号文本**。

        为什么返回文本而不是结构化结果：这样它会经过与真人**完全相同**的解析器与
        规则层校验（计划 §9.3 第 5 条：禁止为 AI 开后门）。这是结构上的保证，
        不是"记得也要校验一下"的自觉。

        返回 None = 没拿到可用决策（超时 / 全部失败）→ 调用方走原有兜底，绝不原地等待。
        """
        log = self._ai_log(ctx)
        state = ctx.state

        if kind == "vote":
            target = await ai_controller.with_budget(
                ai_controller.vote(
                    state=state, pid=pid, candidates=targets, budget=budget, log=log
                ),
                budget=budget,
                log=log,
                kind=kind,
                pid=pid,
            )
            return self._seat_text(ctx, target)

        if kind == "trigger":
            player = find_player(state, pid)
            # 触发类型/能否开枪都能从座位状态推出来，不必让调用方多传参数
            trigger_type = (
                ai_guard.TRIGGER_WOLF_KING_DRAG
                if player and player["role"] == C.WOLF_KING
                else "knight_duel"
                if player and player["role"] == C.KNIGHT
                else "hunter_shoot"
            )
            target = await ai_controller.with_budget(
                ai_controller.trigger(
                    state=state,
                    pid=pid,
                    trigger_type=trigger_type,
                    targets=targets,
                    can_act=bool(player and player["role_state"].get("can_shoot", True)),
                    budget=budget,
                    log=log,
                ),
                budget=budget,
                log=log,
                kind=kind,
                pid=pid,
            )
            return self._seat_text(ctx, target)

        decision = await ai_controller.with_budget(
            ai_controller.night_action(
                state=state,
                pid=pid,
                targets=targets,
                budget=budget,
                log=log,
            ),
            budget=budget,
            log=log,
            kind=kind,
            pid=pid,
        )
        return self._night_decision_text(ctx, decision)

    def _night_decision_text(
        self, ctx: GameContext, decision: ai_controller.Decision | None
    ) -> str | None:
        """把夜间决策翻成玩家会打的那些词（``解药`` / ``毒药 4`` / ``不用`` / ``4``）。"""
        if decision is None:
            return None
        if decision.action == "antidote":
            return "解药"
        if decision.action == "poison":
            seat = self._seat_text(ctx, decision.target)
            return f"毒药 {seat}" if seat else None
        if decision.action in {"none", "skip"} or decision.target is None:
            return "不用" if decision.action == "none" else None
        return self._seat_text(ctx, decision.target)

    # =================================================================
    # 交互（唯一的 IO 出口）
    # =================================================================
    async def _ask(
        self,
        ctx: GameContext,
        pid: str,
        prompt: str,
        *,
        channel: str,
        timeout: float | None,  # noqa: ASYNC109 — 交给 session.ask；真人传 None = 永远等
        sensitive: bool | None = None,
    ) -> str | None:
        """等待某座位的一次输入。

        返回 None = **没有可用输入**（超时 / 退出 / 私聊不可达 / 期间已出局），
        调用方必须走兜底并继续推进。

        ``timeout``：真人一律 ``None``（永远等），见 `_step_timeout`。

        ``sensitive`` 是**信息防火墙开关**：这次等待本身是否属于私有信息。
        夜间的守卫/狼人/女巫/预言家/守墓人，以及开枪/带人/决斗这类触发技能，
        全场只有特定身份会被问到——群内一句"X 超时未响应"就等于告诉所有人
        **X 是这几类身份之一**（12 人局里这是致命情报）。
        敏感的等待出问题时只私聊告知本人，群内一个字都不发。
        默认按通道推断（私聊即敏感）；`投票`是唯一显式豁免的（投票权公开，点名催促无害）。

        ⚠️ ``asyncio.CancelledError`` 绝不能被捕获：`/结束` 会 cancel 等待中的
        future，那是主循环唯一的正常退出通道（本文件因此不 import asyncio）。
        """
        qq = self._controller(ctx, pid)
        if qq is None:
            return None
        # 大原则（任何游戏都遵守）：**AI 有超时，真实玩家没有**。
        # 统一在这里强制，调用点只负责声明"这是哪个阶段的 AI 时限"。
        if not self._is_ai(ctx, pid):
            timeout = None
        if sensitive is None:
            sensitive = channel == "private"

        # 提示由我们自己发（不交给 session.ask），这样才能控制消息生命周期：
        # 群里的提问同时只留一条，下一个人的提问发出前，旧的被撤回。
        before = find_player(ctx.state, pid)
        was_alive = bool(before and before["alive"])
        if channel == "group":
            await self._set_prompt(ctx, prompt, at=qq)
            group_id: int | None = ctx.group_id
        else:
            await self._set_private_prompt(ctx, qq, prompt)
            group_id = None

        try:
            text = await session.ask(qq, None, group_id=group_id, timeout=timeout)
        except GameTimeoutError:
            await self._report_unavailable(
                ctx,
                pid,
                qq,
                sensitive=sensitive,
                private_text="⏰ 已超时未收到你的回复，本回合按默认处理。",
                public_text=f"⏰ {self._label(ctx, pid)} 超时未响应，已按默认处理。",
            )
            return None
        except PlayerQuitError:
            await self.resign(ctx, pid, reason_text="主动退出")
            return None
        except WhisperFailedError as exc:
            await self._report_unavailable(
                ctx,
                pid,
                qq,
                sensitive=sensitive,
                private_text="",  # 私聊不可达，连这条也送不出去
                public_text=(
                    f"⚠️ 无法私聊 {self._label(ctx, pid)}（{exc}），本回合按默认处理。"
                ),
            )
            return None

        # 只有"在**等待期间**新出局（认输/被技能带走）"才作废这次输入，交给兜底。
        # ⚠️ 绝不能用"当前已出局"来判定——死亡触发链（猎人开枪 / 白狼王带人）本身
        # 就是"本人已出局但仍然要行动"，那样写会让技能永远拿不到输入（答了也不生效）。
        player = find_player(ctx.state, pid)
        if player is None:
            return None
        if was_alive and not player["alive"]:
            return None
        return text

    async def _report_unavailable(
        self,
        ctx: GameContext,
        pid: str,
        qq: int | None,
        *,
        sensitive: bool,
        private_text: str,
        public_text: str,
    ) -> None:
        """汇报"这次没拿到输入"。

        ``sensitive=True`` 时**绝不公开**：只尝试私聊告知本人；若私聊本身不可达
        （从 `WhisperFailedError` 进来的那条路），就连私聊也不试——
        宁可静默，也不能用一条公告把"这个座位本夜被问过"告诉全场。
        """
        if sensitive:
            if not private_text:
                return
            await self._notify_sensitive(ctx, pid, private_text, qq=qq)
            return
        await session.broadcast(ctx.group_id, public_text)

    async def _notify_sensitive(
        self, ctx: GameContext, pid: str, text: str, *, qq: int | None = None
    ) -> None:
        """只私聊告知本人；私聊不可达就静默放弃——**任何情况下都不公开**。

        用途：① 私有动作出问题时的告知；② "跳过技能"这类**公开即泄露身份**的确认。
        """
        target = qq if qq is not None else self._controller(ctx, pid)
        if target is None:
            return
        try:
            await session.whisper(target, text)
        except WhisperFailedError:
            return

    async def _ask_text(
        self,
        ctx: GameContext,
        pid: str,
        prompt: str,
        *,
        channel: str,
        timeout: float | None,  # noqa: ASYNC109 — 交给 session.ask；真人传 None = 永远等
        parse: Callable[[str], Awaitable[Outcome]],
        sensitive: bool | None = None,
        ai_kind: str | None = None,
        ai_targets: list[str] | None = None,
    ) -> Outcome:
        """等待 + 解析 + 重问。

        ``timeout`` 给定时是**总预算**（重问不延长）；为 ``None``（真人）时不设时限，
        靠"重问轮数"自然收口，用尽后返回 ``bad``/``abort``，由调用方兜底。

        ``sensitive`` 原样透传给 `_ask`（见那里的信息防火墙说明）。

        ``ai_kind`` / ``ai_targets``：这次提问对 **AI 座位**是什么类型
        （``night`` / ``vote`` / ``trigger``）以及规则层给的合法候选。
        AI 不吃提示词：它拿控制器结论 → 翻成座位号文本 → 走下面**同一个** ``parse``，
        所以"AI 与真人同权校验"是结构保证，不是靠自觉。不传 = AI 没接线，直接兜底。
        """
        if self._is_ai(ctx, pid):
            text = await self._ai_text(
                ctx,
                pid,
                kind=ai_kind or "night",
                targets=ai_targets or [],
                budget=self._ai_budget(ai_kind or "night"),
            )
            return await parse(text) if text else Outcome(kind="abort")

        deadline = None if timeout is None else time.monotonic() + timeout
        current_prompt = prompt
        last_problems: list[str] = []

        for _ in range(cfg.retry_rounds + 1):
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 1.0:
                break
            text = await self._ask(
                ctx,
                pid,
                current_prompt,
                channel=channel,
                timeout=remaining,
                sensitive=sensitive,
            )
            if text is None:
                return Outcome(kind="abort")
            outcome = await parse(text)
            if outcome.usable:
                return outcome
            last_problems = outcome.problems
            current_prompt = self._retry_prompt(prompt, outcome.problems)

        if last_problems:
            return Outcome(kind="bad", problems=last_problems)
        return Outcome(kind="abort")

    @staticmethod
    def _retry_prompt(prompt: str, problems: list[str]) -> str:
        if not problems:
            return prompt
        lines = ["⚠️ 输入有问题，请重新发送："]
        lines.extend(f"· {problem}" for problem in problems)
        lines.append("")
        lines.append(prompt)
        return "\n".join(lines)

    def _target_parser(
        self, st: GameStateDict, allowed: list[str], *, allow_skip: bool = False
    ) -> Callable[[str], Awaitable[Outcome]]:
        """把 `syntax.parse_target` 的产物翻成 `Outcome`。"""

        async def _parse(text: str) -> Outcome:
            result = syntax.parse_target(text, st, allowed_pids=allowed)
            if result.problems:
                return Outcome(kind="bad", problems=result.problems)
            if result.skipped:
                if allow_skip:
                    return Outcome(kind="skip")
                return Outcome(kind="bad", problems=["这个行动必须选一名目标，不能跳过"])
            return Outcome(kind="ok", value=result.pid)

        return _parse

    def _witch_parser(
        self, st: GameStateDict, poison_targets: list[str]
    ) -> Callable[[str], Awaitable[Outcome]]:
        """把 `syntax.parse_witch_action` 的产物翻成 `Outcome`。"""

        async def _parse(text: str) -> Outcome:
            result = syntax.parse_witch_action(text, st, poison_targets=poison_targets)
            if result.problems:
                return Outcome(kind="bad", problems=result.problems)
            if result.potion == "antidote":
                return Outcome(kind="ok", value={"potion": "antidote", "target": None})
            if result.potion == "poison":
                return Outcome(
                    kind="ok", value={"potion": "poison", "target": result.target}
                )
            return Outcome(kind="ok", value={"potion": "none", "target": None})

        return _parse

    # =================================================================
    # 座位映射与工具
    # =================================================================
    @staticmethod
    def _build_seat_owners(ctx: GameContext) -> dict[str, int | None]:
        """pid → 控制者 QQ。

        人类座位默认 pid 就是 ``str(qq)``；调试座位（一个 QQ 控多座）由
        `config["seat_owners"]` 指定，AI 座位为 None（M4）。
        """
        owners: dict[str, int | None] = {
            str(user.qq_id): int(user.qq_id) for user in ctx.players
        }
        for pid, owner in (ctx.config.get("seat_owners") or {}).items():
            owners[str(pid)] = int(owner) if owner is not None else None
        return owners

    @staticmethod
    def _controller(ctx: GameContext, pid: str) -> int | None:
        return (ctx.state.get("seat_owners") or {}).get(pid)

    def _pid_by_controller(self, ctx: GameContext, qq: int) -> str | None:
        """反查某 QQ 控制着哪个座位（认输/记录等指令用）。"""
        for pid, owner in (ctx.state.get("seat_owners") or {}).items():
            if owner == qq:
                return pid
        return None

    @staticmethod
    def _label(ctx: GameContext, pid: str) -> str:
        return syntax.player_label(ctx.state, pid)

    def _build_settings(self, ctx: GameContext) -> dict[str, Any]:
        """把 `ctx.config` 翻成引擎认识的 settings。

        三种输入：

        - `mode` 命中预设 → 用预设板子（角色与胜负条件都跟着预设走）；
        - `mode == "custom"` → 用自定义向导产出的 `roles` / `win_condition`，
          并在**开局前**过一遍 `validate_game_settings`（非法直接拒，别开出一局坏棋）；
        - 其它（没给 / 不认识）→ 回落到默认预设。

        `settings["mode"]` 与 `ctx.config["mode"]` 不是同一个概念：
        前者只说"这份 settings 是预设还是自定义"（`engine.resolve` 按它取角色表）。
        """
        mode = str(ctx.config.get("mode") or DEFAULT_PRESET)
        custom_roles = ctx.config.get("roles")
        if mode == "custom" or (not mode and isinstance(custom_roles, dict)):
            settings: dict[str, Any] = {
                "mode": "custom",
                "preset": None,
                "roles": {str(k): int(v) for k, v in (custom_roles or {}).items()},
                "win_condition": ctx.config.get("win_condition") or C.WIN_EDGE,
                "items": {
                    "enabled": bool(ctx.config.get("items", True)),
                    "pool": list(
                        ctx.config.get("item_pool") or C.BASIC_ITEM_POOL
                    ),
                },
                "last_words": False,
            }
            ok, reason = resolve.validate_game_settings(settings)
            if not ok:
                raise ValueError(f"自定义板子不合法：{reason}")
            return settings

        preset_key = mode if mode in C.PRESETS else DEFAULT_PRESET
        preset = C.PRESETS[preset_key]
        total = sum(preset.roles.values())

        # 7 人及以上局默认把"猎犬哨"放进物品池（源项目定义了却从未启用，见计划 §2.3）
        pool = (
            list(C.LARGE_GAME_ITEM_POOL)
            if total >= C.LARGE_GAME_MIN_PLAYERS
            else list(C.BASIC_ITEM_POOL)
        )
        return {
            "mode": "preset",
            "preset": preset_key,
            "roles": dict(preset.roles),
            "win_condition": preset.win_condition,
            "items": {
                "enabled": bool(ctx.config.get("items", True)),
                # 房主可以在房间阶段覆盖物品池（`@我 物品 关` / 自定义向导）
                "pool": list(ctx.config.get("item_pool") or pool),
            },
            "last_words": False,
        }

    def _assign_players(
        self, ctx: GameContext, settings: dict[str, Any], rng: random.Random
    ) -> list[PlayerDict]:
        """分配座位、身份、随身物品。

        座位随机（与加入顺序无关）；狼人互相知道身份由 `views.render_role_card`
        表达，不额外写进状态（`faction` 已足够）。
        """
        roles = resolve.get_roles_from_settings(settings)
        ai_count = max(0, int(ctx.config.get("ai_seats") or 0))
        if len(roles) != len(ctx.players) + ai_count:
            raise ValueError(
                f"板子需要 {len(roles)} 名玩家，实际 {len(ctx.players)} 真人 + {ai_count} AI"
                "（建房时应该已经校验过人数）"
            )
        rng.shuffle(roles)

        seats = list(range(1, len(roles) + 1))
        rng.shuffle(seats)

        players: list[PlayerDict] = []
        for index, user in enumerate(ctx.players):
            role = roles[index]
            players.append(
                {
                    "pid": str(user.qq_id),
                    "nickname": user.nickname,
                    "seat": seats[index],
                    "role": role,
                    "faction": C.ROLE_FACTION[role],
                    "alive": True,
                    "items": resolve.assign_items(settings, rng),
                    "role_state": new_role_state(role),
                    # 真人永远不被计时（见 `_ask` 的超时原则）
                    "ai": False,
                }
            )

        # AI 补位：人数不够就填满（默认行为，房主可在房间阶段关掉）。
        # pid 用 `ai:N` —— 它**不是 QQ 号**，`seat_owners` 里也没有它，
        # 于是 `_controller()` 对它返回 None：所有"给这个座位发私聊"的路径自然跳过。
        for index in range(1, ai_count + 1):
            slot = len(ctx.players) + index - 1
            role = roles[slot]
            players.append(
                {
                    "pid": f"ai:{index}",
                    "nickname": f"AI{index}",  # 稍后在 on_start 换成 LLM 取的名字
                    "seat": seats[slot],
                    "role": role,
                    "faction": C.ROLE_FACTION[role],
                    "alive": True,
                    "items": resolve.assign_items(settings, rng),
                    "role_state": new_role_state(role),
                    "ai": True,
                }
            )

        resolve.calculate_balance_badges(players)
        return players

    async def _setup_ai_seats(self, ctx: GameContext) -> None:
        """给 AI 座位取名字、分人格（整局固定），并开一份决策日志。

        名字走 LLM（任何失败都回落名字池，**绝不因为取名卡住开局**）；
        人格洗牌后分配，与座位号无关（源项目的可预测性教训，见 `persona.py`）。
        """
        st: GameStateDict = ctx.state
        ai_players = [p for p in st["players"] if p.get("ai")]
        if not ai_players:
            return

        taken = [p["nickname"] for p in st["players"] if not p.get("ai")]
        for player in ai_players:
            player["nickname"] = await ai_names.generate_ai_name(taken)
            taken.append(player["nickname"])

        seed = ctx.config.get("seed")
        rng = random.Random(seed) if seed is not None else random.Random()
        personas = ai_persona.assign_personas([p["pid"] for p in ai_players], rng)
        st["ai"] = {pid: {"persona": persona.id} for pid, persona in personas.items()}
        self._ai_log(ctx).record(
            "setup",
            seats=[
                {
                    "pid": player["pid"],
                    "seat": player["seat"],
                    "name": player["nickname"],
                    "persona": personas[player["pid"]].label,
                }
                for player in ai_players
            ],
        )

    async def _whisper_role_cards(self, ctx: GameContext) -> list[str]:
        """逐个私聊身份牌，返回失败的**昵称**列表（不中断循环）。"""
        failed: list[str] = []
        for player in ctx.state["players"]:
            qq = self._controller(ctx, player["pid"])
            if qq is None:
                continue
            try:
                await session.whisper(qq, views.render_role_card(ctx.state, player))
            except WhisperFailedError:
                failed.append(player["nickname"])
        return failed

    @staticmethod
    async def _persist(ctx: GameContext) -> None:
        runner = game_base.get_runner(ctx.session_id)
        if runner is not None:
            await runner.persist()
