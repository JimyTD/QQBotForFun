"""趣味问答游戏主逻辑。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from nonebot import logger

from core import render, session
from core.game_base import GameBase, GameMode, register_game
from core.types import EndReason, GameContext

from .answer_matcher import looks_like_answer, match, normalize
from .config import get_config
from .prompts import (
    TYPE_IDS,
    TYPE_STYLE_GUIDES,
    type_display_name,
)
from .puzzle_generator import (
    BankNotAvailableError,
    TriviaPuzzle,
    get_puzzle_from_bank,
)


EMOJI = "❓"

# 控制词：要求更多线索
_MORE_CLUE_WORDS = frozenset(
    normalize(w) for w in ("线索", "再来一条", "更多线索", "提示", "hint", "clue")
)
# 控制词：跳过当前题
_SKIP_WORDS = frozenset(
    normalize(w) for w in ("跳过", "不会", "pass", "下一题", "skip")
)


# -------------------- 工具：分类玩家消息 --------------------
def _classify_message(text: str) -> str:
    """player_action 的消息分类：more_clue / skip / answer / chat。"""
    s = text.strip()
    if not s:
        return "chat"
    if s.startswith("/"):
        return "chat"  # 指令交给其他 matcher
    norm = normalize(s)
    if norm in _MORE_CLUE_WORDS:
        return "more_clue"
    if norm in _SKIP_WORDS:
        return "skip"
    cfg = get_config()
    if looks_like_answer(s, cfg.max_answer_length):
        return "answer"
    return "chat"


# -------------------- 计分档位 --------------------
def _score_for_tier(clues_shown: int) -> int:
    cfg = get_config()
    if clues_shown <= 1:
        return cfg.score_tier_1_clue
    if clues_shown <= 3:
        return cfg.score_tier_2_3_clue
    return cfg.score_tier_4_5_clue


def _coin_for_tier(clues_shown: int) -> int:
    cfg = get_config()
    if clues_shown <= 1:
        return cfg.coin_tier_1_clue
    if clues_shown <= 3:
        return cfg.coin_tier_2_3_clue
    return cfg.coin_tier_4_5_clue


@register_game
class TriviaGame(GameBase):
    id = "trivia"
    name = "趣味问答"
    description = "听线索猜答案 · 6 种类型 · 10 题一局"
    min_players = 1
    max_players = 20
    version = "1.0"
    serialize_actions = False
    event_driven = True
    emoji = EMOJI

    # 开局模式 = 类型清单（与 scripts/cli_adapters/trivia.py 共享）
    MODES = [
        GameMode(
            id=tid,
            name=f"{info['emoji']} {info['name']}",
            description=f"{info['name']}题，LLM 出题",
            aliases=(info["name"], info["emoji"]),
        )
        for tid, info in TYPE_STYLE_GUIDES.items()
    ]

    @property
    def default_session_timeout_seconds(self) -> int:  # pragma: no cover
        return get_config().session_timeout_minutes * 60

    # ---------- 生命周期 ----------
    async def on_create(self, ctx: GameContext) -> None:
        cfg = get_config()
        type_id = (ctx.config or {}).get("mode") or TYPE_IDS[0]
        if type_id not in TYPE_IDS:
            type_id = TYPE_IDS[0]

        ctx.state.update(
            type=type_id,
            total=cfg.total_questions_per_game,
            current_index=0,
            current_puzzle=None,
            clues_shown=0,
            scores={},              # qq_id(int) → int   本局 score 累计（进 score 榜）
            coins={},               # qq_id(int) → int   本局 coin 累计（进钱包）
            history=[],
            last_activity_ts=datetime.utcnow().isoformat(),
        )

        # 预生成第 1 题（允许单题失败进 history 占位）
        await self._prepare_next_puzzle(ctx)

    async def on_start(self, ctx: GameContext) -> None:
        type_id = ctx.state["type"]
        total = ctx.state["total"]
        card = render.text_card(
            f"{self.name} · {type_display_name(type_id)}",
            [
                f"本局共 {total} 题 · 局号 {ctx.session_id}",
                "",
                "💡 群里任意发言即可作答",
                "💡 发 「线索」 要下一条线索",
                "💡 发 「跳过」 放弃本题",
                "💡 @我 问答状态 查看进度 · @我 结束 终止本局",
            ],
            emoji=EMOJI,
        )
        await session.broadcast(ctx.group_id, card)
        await self._announce_current_question(ctx, first=True)

    async def on_timeout(self, ctx: GameContext) -> None:
        await session.broadcast(ctx.group_id, "⏱ 本局趣味问答超时，即将结束。")

    async def on_end(self, ctx: GameContext, reason: EndReason) -> None:
        type_id = ctx.state.get("type", "?")
        scores: dict[int, int] = {
            int(k): int(v) for k, v in ctx.state.get("scores", {}).items()
        }
        coins: dict[int, int] = {
            int(k): int(v) for k, v in ctx.state.get("coins", {}).items()
        }
        history = ctx.state.get("history", [])
        cfg = get_config()

        # 计算 MVP（以 score 判）：可能并列
        mvp_ids: list[int] = []
        if scores:
            top = max(scores.values())
            if top > 0:
                mvp_ids = [qq for qq, s in scores.items() if s == top]

        # 发放奖励（走统一接口 self.award，双轨：score 入全局榜 + coin 进钱包）
        final_scores: dict[int, int] = {}
        final_coins: dict[int, int] = {}
        all_players = set(scores) | set(coins)
        for qq in all_players:
            score_total = scores.get(qq, 0) + (cfg.mvp_score_bonus if qq in mvp_ids else 0)
            coin_total = coins.get(qq, 0) + (cfg.mvp_coin_bonus if qq in mvp_ids else 0)
            if score_total > 0:
                final_scores[qq] = score_total
                await self.award(
                    qq,
                    score_total,
                    reason=f"trivia_{type_id}:{ctx.session_id}",
                    currency="score",
                )
            if coin_total > 0:
                final_coins[qq] = coin_total
                await self.award(
                    qq,
                    coin_total,
                    reason=f"trivia_{type_id}:{ctx.session_id}",
                    currency="coin",
                )

        # 组装结算卡
        status_text = {
            EndReason.COMPLETED: "胜利结算 ✅",
            EndReason.ABORTED: "中途结束",
            EndReason.TIMEOUT: "超时",
            EndReason.ERROR: "出错",
        }.get(reason, str(reason.value))

        lines: list[str] = [
            f"类型：{type_display_name(type_id)}",
            f"共答：{len(history)} 题",
            "",
        ]
        if final_scores:
            sorted_rank = sorted(final_scores.items(), key=lambda x: -x[1])
            medals = ["🥇", "🥈", "🥉"]
            for i, (qq, s) in enumerate(sorted_rank[:10]):
                nick = self._nickname_of(ctx, qq)
                medal = medals[i] if i < 3 else f" {i+1}."
                mvp_tag = " 👑 MVP" if qq in mvp_ids else ""
                coin_got = final_coins.get(qq, 0)
                lines.append(f"{medal} @{nick}  {s} 分 · +{coin_got} 金币{mvp_tag}")
        else:
            lines.append("（本局无人得分）")

        footer_lines = ["@我 榜 查看全服趣味分排行 · @我 金币 查钱包余额"]
        try:
            await session.broadcast(
                ctx.group_id,
                render.text_card(
                    f"{self.name} · {status_text}",
                    lines,
                    emoji="🏆",
                    footer=footer_lines,
                ),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[trivia] on_end broadcast failed: {e}")

    # ---------- 玩家消息 ----------
    async def on_player_action(
        self, ctx: GameContext, player_id: int, message: str
    ) -> bool:
        kind = _classify_message(message)
        if kind == "chat":
            return False

        ctx.state["last_activity_ts"] = datetime.utcnow().isoformat()

        if kind == "more_clue":
            await self._handle_more_clue(ctx, player_id)
        elif kind == "skip":
            await self._handle_skip(ctx, player_id)
        elif kind == "answer":
            await self._handle_answer(ctx, player_id, message)
        return True

    def in_game_hint(self, ctx: GameContext) -> str:
        idx = int(ctx.state.get("current_index", 0))
        total = int(ctx.state.get("total", 10))
        return (
            f"{EMOJI} 趣味问答进行中 · 第 {idx + 1}/{total} 题\n"
            "💡 群里直接猜答案 · @我 发「线索」「跳过」\n"
            "💡 @我 问答状态 / 结束"
        )

    # ---------- 核心流程 ----------
    async def _prepare_next_puzzle(self, ctx: GameContext) -> None:
        """为当前 current_index 从题库抽题。题库缺失/为空时触发错误广播并结束整局。"""
        type_id = ctx.state["type"]
        idx = int(ctx.state["current_index"])

        # 本局已出过的答案+别名（题库内抽题时避免重复）
        avoid = self._collect_used_names(ctx)

        try:
            puzzle = get_puzzle_from_bank(type_id, avoid=avoid)
        except BankNotAvailableError as e:
            logger.error(f"[trivia] bank unavailable for type={type_id}: {e}")
            ctx.state["current_puzzle"] = None
            ctx.state["clues_shown"] = 0
            await session.broadcast(
                ctx.group_id,
                f"⚠️ 趣味问答题库（{type_id}）暂不可用，对局无法继续。请联系管理员。",
            )
            await self._end_game(ctx, EndReason.ERROR)
            return

        ctx.state["current_puzzle"] = {
            "answer": puzzle.answer,
            "aliases": puzzle.aliases,
            "clues": puzzle.clues,
            "explanation": puzzle.explanation,
        }
        ctx.state["clues_shown"] = 1  # 开题时直接给第 1 条

    async def _announce_current_question(
        self, ctx: GameContext, *, first: bool = False
    ) -> None:
        puzzle = ctx.state.get("current_puzzle")
        if not puzzle:
            return
        idx = int(ctx.state["current_index"])
        total = int(ctx.state["total"])
        type_id = ctx.state["type"]
        clues_shown = int(ctx.state["clues_shown"])

        clue_lines = [f"💭 线索 1：{puzzle['clues'][0]}"]
        lines = [
            f"题目 {idx + 1}/{total}",
            "",
            *clue_lines,
        ]
        footer_hints = [
            "谁知道就直接在群里说答案",
            "发「线索」要下一条 · 发「跳过」放弃",
        ]
        header = f"{type_display_name(type_id)} · 开始！" if first else f"{type_display_name(type_id)} · 第 {idx + 1} 题"
        await session.broadcast(
            ctx.group_id,
            render.text_card(header, lines, emoji=EMOJI, footer=footer_hints),
        )

    async def _handle_more_clue(self, ctx: GameContext, player_id: int) -> None:
        puzzle = ctx.state.get("current_puzzle")
        if not puzzle:
            return
        clues = puzzle["clues"]
        cfg = get_config()
        shown = int(ctx.state.get("clues_shown", 0))
        if shown >= cfg.max_clues_per_puzzle:
            await session.broadcast(
                ctx.group_id,
                "📜 5 条线索都出完啦~ 实在不会就发「跳过」吧",
                at=player_id,
            )
            return
        shown += 1
        ctx.state["clues_shown"] = shown
        await session.broadcast(
            ctx.group_id,
            f"💭 线索 {shown}：{clues[shown - 1]}\n"
            f"   （已出 {shown}/{cfg.max_clues_per_puzzle} 条）",
        )

    async def _handle_skip(self, ctx: GameContext, player_id: int) -> None:
        puzzle = ctx.state.get("current_puzzle")
        if not puzzle:
            return
        # 立即清除防止并发重复跳过
        ctx.state["current_puzzle"] = None
        nickname = self._nickname_of(ctx, player_id)
        await session.broadcast(
            ctx.group_id,
            f"⏭ @{nickname} 跳过了本题",
        )
        await self._settle_question(ctx, winner_id=None, clues_used=int(ctx.state["clues_shown"]), puzzle=puzzle)

    async def _handle_answer(
        self, ctx: GameContext, player_id: int, message: str
    ) -> None:
        puzzle = ctx.state.get("current_puzzle")
        if not puzzle:
            return

        if match(message, puzzle["answer"], puzzle.get("aliases", [])):
            # ⚠️ 立即清除 current_puzzle，防止并发答对时重复出题
            ctx.state["current_puzzle"] = None

            clues_used = int(ctx.state["clues_shown"])
            score_delta = _score_for_tier(clues_used)
            coin_delta = _coin_for_tier(clues_used)
            scores = ctx.state.setdefault("scores", {})
            coins = ctx.state.setdefault("coins", {})
            # 注意：session state 的 key 可能在持久化时被转 str，这里统一 int
            scores[int(player_id)] = int(scores.get(int(player_id), 0)) + score_delta
            coins[int(player_id)] = int(coins.get(int(player_id), 0)) + coin_delta

            nickname = self._nickname_of(ctx, player_id)
            await session.broadcast(
                ctx.group_id,
                render.text_card(
                    "答对了！",
                    [
                        f"✅ @{nickname} +{score_delta} 分 · +{coin_delta} 金币"
                        f"（{clues_used} 条线索内猜中）",
                        "",
                        f"📖 答案：{puzzle['answer']}",
                        f"💡 {puzzle['explanation']}" if puzzle.get("explanation") else "",
                    ],
                    emoji="🎉",
                ),
            )
            await self._settle_question(ctx, winner_id=int(player_id), clues_used=clues_used, puzzle=puzzle)
        else:
            nickname = self._nickname_of(ctx, player_id)
            # 答错每次都回应（方案 A）
            await session.broadcast(
                ctx.group_id,
                f"❌ @{nickname} 不对哦，继续~",
            )

    async def _settle_question(
        self,
        ctx: GameContext,
        *,
        winner_id: int | None,
        clues_used: int,
        puzzle: dict | None = None,
    ) -> None:
        if puzzle is None:
            puzzle = ctx.state.get("current_puzzle") or {}
        idx = int(ctx.state["current_index"])
        total = int(ctx.state["total"])
        awarded = _score_for_tier(clues_used) if winner_id is not None else 0

        # 跳过场景：展示答案和讲解（答对场景在 _handle_answer 已展示）
        if winner_id is None and puzzle:
            await session.broadcast(
                ctx.group_id,
                render.text_card(
                    "答案揭晓",
                    [
                        f"📖 答案：{puzzle['answer']}",
                        f"💡 {puzzle['explanation']}" if puzzle.get("explanation") else "",
                    ],
                    emoji="📜",
                ),
            )

        # history
        ctx.state.setdefault("history", []).append(
            {
                "answer": puzzle.get("answer"),
                "aliases": list(puzzle.get("aliases", [])),
                "winner": winner_id,
                "clues_used": clues_used,
                "awarded": awarded,
            }
        )

        # 展示本局 TOP 3
        await self._broadcast_local_top(ctx)

        # 进入下一题 or 结算
        ctx.state["current_index"] = idx + 1
        ctx.state["current_puzzle"] = None
        ctx.state["clues_shown"] = 0

        if ctx.state["current_index"] >= total:
            await self._end_game(ctx, EndReason.COMPLETED)
            return

        await self._prepare_next_puzzle(ctx)
        await self._announce_current_question(ctx)

    async def _broadcast_local_top(self, ctx: GameContext) -> None:
        scores: dict[int, int] = {
            int(k): int(v) for k, v in ctx.state.get("scores", {}).items()
        }
        if not scores:
            return
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:3]
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (qq, s) in enumerate(ranked):
            nick = self._nickname_of(ctx, qq)
            lines.append(f"{medals[i]} @{nick}  {s} 分")
        idx = int(ctx.state["current_index"])
        total = int(ctx.state["total"])
        await session.broadcast(
            ctx.group_id,
            render.text_card(
                f"本局进度 {idx + 1}/{total}",
                lines,
                emoji="📊",
            ),
        )

    async def _end_game(self, ctx: GameContext, reason: EndReason) -> None:
        """内部收束：通过 runner 触发正式 end 流程（on_end 会跑）。"""
        from core import game_base as gb

        runner = gb.get_runner(ctx.session_id)
        if runner is not None:
            await runner.end(reason)

    # ---------- 工具 ----------
    @staticmethod
    def _nickname_of(ctx: GameContext, qq_id: int) -> str:
        p = ctx.get_player(qq_id)
        return p.nickname if p else str(qq_id)

    @staticmethod
    def _collect_used_names(ctx: GameContext) -> list[str]:
        """收集本局 history 里已出过的 answer + aliases，用于 generate_puzzle 的 avoid。"""
        used: list[str] = []
        for item in ctx.state.get("history", []) or []:
            if not isinstance(item, dict):
                continue
            ans = item.get("answer")
            if isinstance(ans, str) and ans.strip():
                used.append(ans.strip())
            for a in item.get("aliases", []) or []:
                if isinstance(a, str) and a.strip():
                    used.append(a.strip())
        return used

    def dump_state(self, ctx: GameContext) -> dict[str, Any]:
        return dict(ctx.state)

    def load_state(self, ctx: GameContext, data: dict[str, Any]) -> None:
        ctx.state.clear()
        ctx.state.update(data)
