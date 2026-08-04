"""海龟汤游戏主逻辑。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from nonebot import logger

from core import llm, render, session
from core.economy import balance as eco_balance, deduct as eco_deduct
from core.errors import InsufficientFundsError, LLMError, LLMJSONParseError
from core.game_base import GameBase, GameMode, register_game
from core.storage import get_session as db_session
from core.types import EndReason, GameContext

from .config import get_config
from .models import SoupQuestion, SoupSessionRecord
from .prompts import (
    CLAIM_SYSTEM,
    CLAIM_USER,
    JUDGE_USER,
    build_judge_system_prompt,
    format_clues,
)
from .puzzle_service import PuzzleData, mark_win, obtain_puzzle, record_last_puzzle


EMOJI = "🐢"


def _classify_message(text: str) -> str:
    """将玩家消息分类：question / claim / command。

    所有 @机器人 的消息都会到这里（message_router 已过滤），
    所以非命令、非宣告的消息统一当作提问。
    """
    s = text.strip()
    if not s:
        return "command"  # 空消息忽略
    # 指令：以 / 开头
    if s.startswith("/"):
        return "command"
    lowered = s.lower()
    for kw in ("汤底:", "汤底：", "答案:", "答案：", "宣告:", "宣告：", "claim:", "claim："):
        if lowered.startswith(kw):
            return "claim"
    # 其他所有消息当作提问
    return "question"


def _strip_claim_prefix(text: str) -> str:
    s = text.strip()
    for kw in ("汤底:", "汤底：", "答案:", "答案：", "宣告:", "宣告：", "claim:", "claim："):
        if s.lower().startswith(kw.lower()):
            return s[len(kw):].strip()
    return s


def _norm_clue(s: str) -> str:
    """线索归一化：只保留字母数字与中日韩文字，用于容错匹配。"""
    return "".join(ch for ch in s if ch.isalnum())


def locate_clue(clue: str, key_clues: list[str]) -> int | None:
    """把判官回填的线索原文定位到 key_clues 的下标。

    判官是 flash 级小模型，可能改写、截断或抄空。四级降级匹配：
      1. 完全相等
      2. 归一化后相等（忽略标点空格）
      3. 归一化后互相包含（模型多抄或少抄了修饰语）
      4. 最长公共子串占比 >= 0.6 且**唯一命中**（如「父亲去世」↔「父亲已经去世」）
    全部失配、或第 4 级出现多条并列候选（歧义）时返回 None，
    调用方按「命中但无法定位」处理，绝不猜测下标。
    """
    if not clue or not key_clues:
        return None
    if clue in key_clues:
        return key_clues.index(clue)
    nc = _norm_clue(clue)
    if not nc:
        return None
    normed = [_norm_clue(c) for c in key_clues]
    for i, n in enumerate(normed):
        if n and n == nc:
            return i
    for i, n in enumerate(normed):
        if n and (n in nc or nc in n):
            return i

    # 第 4 级：最长公共子序列占比，取最优且要求明显领先，避免歧义
    scored: list[tuple[float, int]] = []
    for i, n in enumerate(normed):
        if not n:
            continue
        lcs = _lcs_len(n, nc)
        ratio = lcs / max(len(n), len(nc))
        if ratio >= 0.6:
            scored.append((ratio, i))
    if not scored:
        return None
    scored.sort(reverse=True)
    if len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 1e-9:
        # 两条线索得分完全相同，无法区分，宁可不猜
        return None
    return scored[0][1]


def _lcs_len(a: str, b: str) -> int:
    """最长公共子序列长度（滚动数组 DP）。

    用子序列而非子串：判官常在线索中间插入或省略修饰词
    （「父亲去世」↔「父亲已经去世」），子串会漏判。
    线索都很短，O(n*m) 足够。
    """
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = max(prev[j], cur[j - 1])
        prev = cur
    return prev[len(b)]




def clue_progress(ctx: GameContext) -> tuple[int, int]:
    """返回 (已发现线索数, 线索总数)。

    已发现数取「可定位去重集合」与「无法定位的命中次数」之和，
    并按总数封顶，避免出现 6/5 这类越界显示。
    """
    puzzle = ctx.state.get("puzzle", {})
    total = len(puzzle.get("key_clues", []) or [])
    hit_idx = ctx.state.get("hit_clue_idx", []) or []
    unlocated = int(ctx.state.get("unlocated_key_hits", 0) or 0)
    found = len(set(hit_idx)) + unlocated
    if total:
        found = min(found, total)
    return found, total



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
            "canonical_facts": puzzle.canonical_facts,
            "surface_gloss": puzzle.surface_gloss,
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
                "💡 @我 发送问题即可提问",
                "💡 宣告汤底请以「汤底:」开头",
                "💡 @我 /回顾 看已知线索与进度",
                "💡 @我 /提示 花金币买方向提示",
                "💡 @我 结束 投降 · @我 状态 查看进度",
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
    ) -> bool:
        kind = _classify_message(message)
        if kind == "command":
            return False

        # 软上限
        max_q = int(ctx.state.get("max_questions", 50))
        qcount = int(ctx.state.get("question_count", 0))
        if qcount >= max_q and kind != "claim":
            await session.broadcast(
                ctx.group_id,
                "⚠️ 已达提问上限，请宣告汤底或 @我 结束 投降。",
                at=player_id,
            )
            return True

        if kind == "question":
            await self._handle_question(ctx, player_id, message)
        elif kind == "claim":
            await self._handle_claim(ctx, player_id, message)
        return True

    def in_game_hint(self, ctx: GameContext) -> str:
        puzzle = ctx.state.get("puzzle", {})
        title = puzzle.get("title", "")
        head = f"{EMOJI} 海龟汤进行中"
        if title:
            head += f" ·《{title}》"
        return (
            f"{head}\n"
            "💡 @我 直接提问 · 汤底:xxx 宣告答案\n"
            "💡 @我 状态 / 提示 / 汤面 / 结束"
        )

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
                        content=build_judge_system_prompt(
                            surface=puzzle["surface"],
                            truth=puzzle["truth"],
                            key_clues=puzzle.get("key_clues", []),
                            version="1.2",
                            with_clue=True,
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
            clue_raw = str(data.get("clue", "") or "")
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

        # ---- 线索进度维护（key 命中时）----
        newly_found = False
        if verdict == "key":
            key_clues = puzzle.get("key_clues", []) or []
            idx = locate_clue(clue_raw, key_clues)
            hit_idx: list[int] = ctx.state.setdefault("hit_clue_idx", [])
            if idx is not None:
                if idx not in hit_idx:
                    hit_idx.append(idx)
                    newly_found = True
                ctx.state["hit_clue_idx"] = hit_idx
            else:
                # 判官没给 clue 或抄错到无法定位：按次数计入，不猜下标
                logger.info(
                    f"[soup] key hit but clue unlocatable: clue={clue_raw!r} "
                    f"session={ctx.session_id}"
                )
                ctx.state["unlocated_key_hits"] = (
                    int(ctx.state.get("unlocated_key_hits", 0) or 0) + 1
                )
                newly_found = True

        # ---- 已排除记录（no 命中时，供 /回顾 面板使用）----
        if verdict == "no":
            ruled_out: list[str] = ctx.state.setdefault("ruled_out", [])
            ruled_out.append(question.strip())
            # 只保留最近 12 条，避免 state 无限膨胀
            ctx.state["ruled_out"] = ruled_out[-12:]

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

        # key 命中时附加线索进度，给玩家"闯关"而非"盲猜"的感觉
        if verdict == "key":
            found, total = clue_progress(ctx)
            if total:
                bar = "●" * found + "○" * max(0, total - found)
                tag = "🔓 新线索" if newly_found else "↩ 已知线索"
                label += f"\n   {tag} · 进度 {bar} {found}/{total}"
                if found >= total:
                    label += "\n   🎯 关键线索已全部集齐，快宣告汤底！"


        # 参与奖（核心设计：及时正反馈）
        cfg = get_config()
        if verdict == "key":
            await self.award(
                player_id,
                cfg.reward_score_on_key_hit,
                reason=f"turtle_soup_key:{ctx.session_id}",
                currency="score",
            )
            await self.award(
                player_id,
                cfg.reward_coin_on_key_hit,
                reason=f"turtle_soup_key:{ctx.session_id}",
                currency="coin",
            )
        elif verdict == "yes":
            await self.award(
                player_id,
                cfg.reward_score_on_yes,
                reason=f"turtle_soup_yes:{ctx.session_id}",
                currency="score",
            )
            await self.award(
                player_id,
                cfg.reward_coin_on_yes,
                reason=f"turtle_soup_yes:{ctx.session_id}",
                currency="coin",
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

    # ---------- 购买提示 ----------
    async def handle_hint(self, ctx: GameContext, player_id: int) -> str | None:
        """花金币直接揭示一条未发现的关键线索。

        返回被揭示的线索文本（成功时），或 None（已由内部发送错误消息）。
        揭示后计入线索进度，并写入 DB 供 /回顾 查看。
        由 commands.py 的 /提示 指令调用。
        """
        cfg = get_config()
        puzzle = ctx.state.get("puzzle")
        if not puzzle:
            return None

        # 防超限（兼容旧局里存过渐进式提示字符串）
        hints_purchased: list = ctx.state.setdefault("hints_purchased", [])
        if len(hints_purchased) >= cfg.max_hints_per_game:
            await session.broadcast(
                ctx.group_id,
                f"⚠️ 本局已购买 {cfg.max_hints_per_game} 次提示，达到上限。",
                at=player_id,
            )
            return None

        # 尚未揭示：既没买过，也没在提问里命中过
        all_clues: list[str] = puzzle.get("key_clues", []) or []
        purchased_idx = {i for i in hints_purchased if isinstance(i, int)}
        hit_idx = set(ctx.state.get("hit_clue_idx", []) or [])
        undiscovered_indices = [
            i
            for i in range(len(all_clues))
            if i not in purchased_idx and i not in hit_idx
        ]
        if not undiscovered_indices:
            await session.broadcast(
                ctx.group_id,
                "💡 所有关键线索都已揭示，靠你自己推理汤底啦！",
                at=player_id,
            )
            return None

        # 扣币
        try:
            await eco_deduct(
                player_id,
                cfg.hint_cost_coin,
                reason=f"turtle_soup_hint:{ctx.session_id}",
                currency="coin",
            )
        except InsufficientFundsError:
            cur_bal = await eco_balance(player_id, currency="coin")
            await session.broadcast(
                ctx.group_id,
                f"💰 金币不足！购买提示需要 {cfg.hint_cost_coin} 枚，"
                f"你当前只有 {cur_bal} 枚。",
                at=player_id,
            )
            return None

        # 直接揭示第一条未发现的线索
        target_idx = undiscovered_indices[0]
        clue_text = all_clues[target_idx]
        hint_number = len(hints_purchased) + 1

        hints_purchased.append(target_idx)
        ctx.state["hints_purchased"] = hints_purchased

        # 同步线索进度条
        hit_list: list[int] = ctx.state.setdefault("hit_clue_idx", [])
        if target_idx not in hit_list:
            hit_list.append(target_idx)
            ctx.state["hit_clue_idx"] = hit_list

        # 写入 DB，使 /回顾 能看到
        async with db_session() as sess:
            sess.add(
                SoupQuestion(
                    session_id=ctx.session_id,
                    asker_id=player_id,
                    question=f"[提示 #{hint_number}]",
                    verdict="key",
                    hint=clue_text,
                )
            )

        return clue_text

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
