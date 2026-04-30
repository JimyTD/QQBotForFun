"""海龟汤游戏主逻辑。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from nonebot import logger

from core import llm, render, session
from core.errors import LLMError, LLMJSONParseError
from core.game_base import GameBase, GameMode, register_game
from core.storage import get_session as db_session
from core.types import EndReason, GameContext

from .config import get_config
from .models import SoupQuestion, SoupSessionRecord
from .prompts import (
    CLAIM_SYSTEM,
    CLAIM_USER,
    JUDGE_SYSTEM,
    JUDGE_USER,
    format_clues,
)
from .puzzle_service import PuzzleData, mark_win, obtain_puzzle, record_last_puzzle


EMOJI = "🐢"


def _classify_message(text: str) -> str:
    """将玩家消息分类：question / claim / command / chat。"""
    s = text.strip()
    if not s:
        return "chat"
    # 指令：以 / 开头交给 NoneBot 的 matcher（这里已经在 session 之后被路由到游戏，
    # 说明它不是我们已知的命令；保险起见仍跳过以 / 开头的）
    if s.startswith("/"):
        return "command"
    lowered = s.lower()
    for kw in ("汤底:", "汤底：", "答案:", "答案：", "宣告:", "宣告：", "claim:", "claim："):
        if lowered.startswith(kw):
            return "claim"
    if s.endswith("?") or s.endswith("？"):
        return "question"
    if s.startswith(("问:", "问：", "q:", "Q:")):
        return "question"
    return "chat"


def _strip_claim_prefix(text: str) -> str:
    s = text.strip()
    for kw in ("汤底:", "汤底：", "答案:", "答案：", "宣告:", "宣告：", "claim:", "claim："):
        if s.lower().startswith(kw.lower()):
            return s[len(kw):].strip()
    return s


@register_game
class TurtleSoupGame(GameBase):
    id = "turtle_soup"
    name = "海龟汤"
    description = "LLM 驱动的水平思考谜题"
    min_players = 1
    max_players = 10
    version = "1.0"
    serialize_actions = False
    event_driven = True
    emoji = EMOJI

    # 开局模式（与 scripts/cli_adapters/turtle_soup.py 的 MODES 保持同步）
    MODES = [
        GameMode(
            id="library",
            name="题库随机",
            description="从题库挑一道现成的",
            aliases=("快速", "fast", "库"),
        ),
        GameMode(
            id="llm",
            name="LLM 即时生成",
            description="让大模型现场出一道（约 10-20s）",
            aliases=("生成", "new", "ai"),
        ),
    ]

    # 在 launcher 启动时会查询该属性作为整局 timeout
    @property
    def default_session_timeout_seconds(self) -> int:  # pragma: no cover
        return get_config().session_timeout_minutes * 60

    # ---------- 生命周期 ----------
    async def on_create(self, ctx: GameContext) -> None:
        # 保留生成时的配置快照，便于重启恢复
        cfg = get_config()
        ctx.state["max_questions"] = cfg.max_questions
        ctx.state["question_count"] = 0
        ctx.state["last_activity_ts"] = datetime.utcnow().isoformat()

        # 出题（mode 由 /开始 选择流程传入，存在 ctx.config 里）
        mode = ctx.config.get("mode") if ctx.config else None
        try:
            puzzle = await obtain_puzzle(mode=mode)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[soup] obtain_puzzle failed: {e}")
            await session.broadcast(
                ctx.group_id,
                "⚠️ 出题失败，请稍后再试。",
            )
            raise

        ctx.state["puzzle"] = {
            "id": puzzle.id,
            "title": puzzle.title,
            "category": puzzle.category,
            "surface": puzzle.surface,
            "truth": puzzle.truth,
            "key_clues": puzzle.key_clues,
            "difficulty": puzzle.difficulty,
            "source": puzzle.source,
        }

        # 写入海龟汤会话记录
        async with db_session() as sess:
            sess.add(
                SoupSessionRecord(
                    session_id=ctx.session_id,
                    puzzle_id=puzzle.id,
                    question_count=0,
                )
            )

    async def on_start(self, ctx: GameContext) -> None:
        puzzle = ctx.state["puzzle"]
        diff_stars = "★" * int(puzzle["difficulty"]) + "☆" * (5 - int(puzzle["difficulty"]))
        card = render.text_card(
            f"{self.name} · 局号 {ctx.session_id}",
            [
                f"{puzzle['category']} · {diff_stars}",
                "",
                f"《{puzzle['title']}》",
                "",
                puzzle["surface"],
            ],
            emoji=EMOJI,
            footer=[
                "💡 提问以 ? 结尾",
                "💡 宣告汤底请以「汤底:」开头",
                "💡 /汤 投降 投降 · /汤 状态 查看进度",
                "💡 /结束 终止本局",
            ],
        )
        await session.broadcast(ctx.group_id, card)

    async def on_timeout(self, ctx: GameContext) -> None:
        await session.broadcast(ctx.group_id, "⏱ 本局海龟汤超时，即将结束。")

    async def on_end(self, ctx: GameContext, reason: EndReason) -> None:
        puzzle = ctx.state.get("puzzle", {})
        qcount = int(ctx.state.get("question_count", 0))
        if not puzzle:
            return

        # 记录本 group 最近玩过的题，用于 /汤 烂题 短窗口淘汰
        try:
            record_last_puzzle(ctx.group_id, int(puzzle["id"]))
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"[soup] record_last_puzzle failed: {e}")

        # 结算
        winner_id = ctx.state.get("winner_id")
        if reason == EndReason.COMPLETED and winner_id:
            # 赢家奖励已在 _handle_claim::correct 分支发放，这里只做题库统计
            await mark_win(int(puzzle["id"]))
            highlight = f"🏆 MVP：@{self._nickname_of(ctx, int(winner_id))}"
        elif reason == EndReason.ABORTED:
            highlight = "🏳 本局已终止"
        elif reason == EndReason.TIMEOUT:
            highlight = "⏱ 本局已超时"
        else:
            highlight = ""

        status_text = {
            EndReason.COMPLETED: "胜利 ✅",
            EndReason.ABORTED: "中断",
            EndReason.TIMEOUT: "超时",
            EndReason.ERROR: "出错",
        }.get(reason, str(reason.value))

        summary = {
            "结果": status_text,
            "提问": f"{qcount} 次",
            "用时": self._duration(ctx),
        }

        card = render.result(
            "游戏结束",
            f"{EMOJI} {self.name} ·《{puzzle['title']}》",
            summary,
            highlight=highlight,
            footer="完整汤底 👇",
        )
        try:
            await session.broadcast(ctx.group_id, card)
            await session.broadcast(
                ctx.group_id,
                render.text_card(
                    "汤底揭晓",
                    [puzzle["truth"]],
                    emoji="📜",
                    footer=[f"关键线索：{ '、'.join(puzzle.get('key_clues', [])) }"],
                ),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[soup] on_end broadcast failed: {e}")

    # ---------- 玩家消息 ----------
    async def on_player_action(
        self, ctx: GameContext, player_id: int, message: str
    ) -> None:
        kind = _classify_message(message)
        if kind == "chat" or kind == "command":
            return

        # 软上限
        max_q = int(ctx.state.get("max_questions", 50))
        qcount = int(ctx.state.get("question_count", 0))
        if qcount >= max_q and kind != "claim":
            await session.broadcast(
                ctx.group_id,
                "⚠️ 已达提问上限，请宣告汤底或 /汤 投降 。",
                at=player_id,
            )
            return

        if kind == "question":
            await self._handle_question(ctx, player_id, message)
        elif kind == "claim":
            await self._handle_claim(ctx, player_id, message)

    # ---------- 问答判定 ----------
    async def _handle_question(
        self, ctx: GameContext, player_id: int, question: str
    ) -> None:
        puzzle = ctx.state["puzzle"]
        try:
            resp = await llm.chat(
                messages=[
                    llm.LLMMessage(
                        role="system",
                        content=JUDGE_SYSTEM.format(
                            surface=puzzle["surface"],
                            truth=puzzle["truth"],
                            key_clues=format_clues(puzzle.get("key_clues", [])),
                        ),
                    ),
                    llm.LLMMessage(role="user", content=JUDGE_USER.format(question=question)),
                ],
                scene="turtle_soup_judge",
                json_mode=True,
            )
            data = resp.json()
            verdict = str(data.get("type", "irrelevant"))
            hint = str(data.get("hint", "") or "")
        except (LLMError, LLMJSONParseError) as e:
            logger.warning(f"[soup] judge failed: {e}")
            await session.broadcast(
                ctx.group_id, "⚠️ 汤主走神了，请再问一次~", at=player_id
            )
            return

        # 宣告被检测
        if verdict == "claim_detected":
            await self._handle_claim(ctx, player_id, question)
            return

        # 累计计数
        ctx.state["question_count"] = int(ctx.state.get("question_count", 0)) + 1
        ctx.state["last_activity_ts"] = datetime.utcnow().isoformat()

        # 记录
        async with db_session() as sess:
            sess.add(
                SoupQuestion(
                    session_id=ctx.session_id,
                    asker_id=player_id,
                    question=question,
                    verdict=verdict,
                    hint=hint or None,
                )
            )
            row = await sess.get(SoupSessionRecord, ctx.session_id)
            if row is not None:
                row.question_count = int(ctx.state["question_count"])

        # 回复
        label = {
            "yes": "✅ 是",
            "no": "❌ 不是",
            "irrelevant": "🤔 与此无关",
            "key": f"💡 关键线索：{hint}" if hint else "💡 关键线索",
        }.get(verdict, "🤔 与此无关")

        # 参与奖（核心设计：及时正反馈）——问出 key / partial 都给 score
        # 注：partial 只在 _handle_claim 里出现；问答阶段只有 key 奖励
        cfg = get_config()
        if verdict == "key":
            await self.award(
                player_id,
                cfg.reward_score_on_key_hit,
                reason=f"turtle_soup_key:{ctx.session_id}",
                currency="score",
            )

        player = ctx.get_player(player_id)
        nickname = player.nickname if player else str(player_id)
        await session.broadcast(
            ctx.group_id,
            render.status_line(f"@{nickname}", f"❓ {question}", label),
        )

    # ---------- 宣告判定 ----------
    async def _handle_claim(self, ctx: GameContext, player_id: int, raw: str) -> None:
        puzzle = ctx.state["puzzle"]
        claim = _strip_claim_prefix(raw)
        try:
            resp = await llm.chat(
                messages=[
                    llm.LLMMessage(
                        role="system",
                        content=CLAIM_SYSTEM.format(
                            truth=puzzle["truth"],
                            key_clues=format_clues(puzzle.get("key_clues", [])),
                        ),
                    ),
                    llm.LLMMessage(role="user", content=CLAIM_USER.format(claim=claim)),
                ],
                scene="turtle_soup_claim",
                json_mode=True,
            )
            data = resp.json()
            verdict = str(data.get("verdict", "wrong"))
            feedback = str(data.get("feedback", "") or "")
        except (LLMError, LLMJSONParseError) as e:
            logger.warning(f"[soup] claim judge failed: {e}")
            await session.broadcast(
                ctx.group_id, "⚠️ 汤主走神了，请再宣告一次~", at=player_id
            )
            return

        player = ctx.get_player(player_id)
        nickname = player.nickname if player else str(player_id)

        if verdict == "correct":
            ctx.state["winner_id"] = player_id
            # 赢家奖励：coin（钱包）+ score（排行榜），双轨制
            cfg = get_config()
            await self.award(
                player_id,
                cfg.reward_coin_on_win,
                reason=f"turtle_soup_win:{ctx.session_id}",
                currency="coin",
            )
            await self.award(
                player_id,
                cfg.reward_score_on_win,
                reason=f"turtle_soup_win:{ctx.session_id}",
                currency="score",
            )
            await session.broadcast(
                ctx.group_id,
                render.text_card(
                    "宣告成功！",
                    [
                        f"🏆 @{nickname} 答对了！",
                        "",
                        feedback or "真相已被还原。",
                    ],
                    emoji="🏆",
                ),
            )
            # 结束游戏
            from core import game_base as gb

            runner = gb.get_runner(ctx.session_id)
            if runner is not None:
                await runner.end(EndReason.COMPLETED)
        elif verdict == "partial":
            # 部分正确也给少量 score 参与奖
            cfg = get_config()
            await self.award(
                player_id,
                cfg.reward_score_on_partial_hit,
                reason=f"turtle_soup_partial:{ctx.session_id}",
                currency="score",
            )
            await session.broadcast(
                ctx.group_id,
                render.status_line(
                    f"@{nickname}", "📣 宣告", f"🟡 部分正确 · {feedback}"
                )
                + "\n   可继续提问（? 结尾）或补充后重新宣告（汤底: 开头）",
            )
        else:
            await session.broadcast(
                ctx.group_id,
                render.status_line(
                    f"@{nickname}", "📣 宣告", f"❌ 不对 · {feedback}"
                )
                + "\n   本次宣告不消耗提问额度，继续推理吧",
            )

    # ---------- 工具 ----------
    @staticmethod
    def _nickname_of(ctx: GameContext, qq_id: int) -> str:
        p = ctx.get_player(qq_id)
        return p.nickname if p else str(qq_id)

    @staticmethod
    def _duration(ctx: GameContext) -> str:
        delta = datetime.utcnow() - ctx.started_at
        minutes = int(delta.total_seconds() // 60)
        return f"{minutes} 分钟" if minutes else "不到 1 分钟"

    # 允许默认状态序列化
    def dump_state(self, ctx: GameContext) -> dict[str, Any]:
        return dict(ctx.state)

    def load_state(self, ctx: GameContext, data: dict[str, Any]) -> None:
        ctx.state.clear()
        ctx.state.update(data)
