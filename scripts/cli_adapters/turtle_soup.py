"""海龟汤的 CLI Adapter。

MODES 权威清单定义在 src/plugins/games/turtle_soup/game.py 的 GameBase.MODES。
本 adapter 直接复用那份定义，保证 CLI / bot 一致。
"""

from __future__ import annotations

from core import llm
from core.errors import LLMError, LLMJSONParseError
from src.plugins.games.turtle_soup.config import get_config
from src.plugins.games.turtle_soup.game import TurtleSoupGame
from src.plugins.games.turtle_soup.prompts import (
    CLAIM_SYSTEM,
    CLAIM_USER,
    JUDGE_SYSTEM,
    JUDGE_USER,
    format_clues,
)
from src.plugins.games.turtle_soup.puzzle_service import (
    PuzzleData,
    mark_bad_by_group,
    obtain_puzzle,
    record_last_puzzle,
)

from .base import C, GameCLIAdapter, box, info, prompt


HELP_TEXT = (
    "用法：\n"
    "  · 提问：以 ? 结尾的一句话（例：他活着吗？）\n"
    "  · 宣告汤底：以「汤底:」或「答案:」开头\n"
    "  · status / 状态  查看进度\n"
    "  · recap  / 回顾  查看关键线索\n"
    "  · hint   / 提示  花金币购买一条方向性提示\n"
    "  · giveup / 投降  投降公布汤底\n"
    "  · quit   / 退出  退出当前游戏\n"
    "  · help   / 帮助  查看本帮助\n"
    "（局末会询问是否标记为烂题）"
)


# CLI 统一 group_id（和 Bot 的 group_id 不冲突，Bot 用的是真实 QQ 群号）
_CLI_GROUP_ID = 0


def _classify(text: str) -> str:
    s = text.strip()
    if not s:
        return "chat"
    lowered = s.lower()
    if lowered in ("help", "?", "？", "帮助"):
        return "help"
    if lowered in ("status", "状态"):
        return "status"
    if lowered in ("recap", "回顾"):
        return "recap"
    if lowered in ("hint", "提示"):
        return "hint"
    if lowered in ("giveup", "投降", "认输"):
        return "giveup"
    if lowered in ("quit", "exit", "退出"):
        return "quit"
    for kw in ("汤底:", "汤底：", "答案:", "答案：", "宣告:", "宣告："):
        if s.startswith(kw):
            return "claim"
    if s.endswith("?") or s.endswith("？"):
        return "question"
    if s.startswith(("问:", "问：", "q:", "Q:")):
        return "question"
    return "chat"


def _strip_claim(text: str) -> str:
    s = text.strip()
    for kw in ("汤底:", "汤底：", "答案:", "答案：", "宣告:", "宣告："):
        if s.startswith(kw):
            return s[len(kw):].strip()
    return s


class TurtleSoupCLIAdapter(GameCLIAdapter):
    game_name = TurtleSoupGame.name + " 🐢"
    MODES = TurtleSoupGame.MODES  # 与 bot 共享

    def __init__(self, *, debug: bool = False) -> None:
        self.debug = debug
        self.puzzle: PuzzleData | None = None
        self.question_count = 0
        self.key_clues_shown: list[tuple[str, str]] = []
        self.hints_purchased: list[int] = []  # 已购买提示对应的线索索引
        self.max_q = 50
        # CLI 本地累积的奖励（不真实调 economy，避免 qq_id=0 幽灵账户污染 DB）
        self.cli_score = 0
        self.cli_coin = 0

    def _show_reward(self, *, score: int = 0, coin: int = 0, label: str = "") -> None:
        """CLI 端本地累积并即时显示奖励，行为和 Bot 一致（只是不入 DB）。"""
        if score <= 0 and coin <= 0:
            return
        self.cli_score += score
        self.cli_coin += coin
        parts = []
        if score > 0:
            parts.append(f"{C.MAG}+{score} score{C.R}")
        if coin > 0:
            parts.append(f"{C.YEL}+{coin} coin{C.R}")
        suffix = f"（{label}）" if label else ""
        print(
            f"    {C.DIM}🎁 {' · '.join(parts)}{suffix}  "
            f"本局累计：{self.cli_score} score / {self.cli_coin} coin{C.R}"
        )

    async def start(self, mode_id: str) -> None:
        """统一入口：mode_id 决定是题库还是 LLM 生成。"""
        self.puzzle = await obtain_puzzle(mode=mode_id)

    async def _judge_question(self, question: str) -> tuple[str, str]:
        assert self.puzzle is not None
        resp = await llm.chat(
            messages=[
                llm.LLMMessage(
                    role="system",
                    content=JUDGE_SYSTEM.format(
                        surface=self.puzzle.surface,
                        truth=self.puzzle.truth,
                        key_clues=format_clues(self.puzzle.key_clues),
                    ),
                ),
                llm.LLMMessage(role="user", content=JUDGE_USER.format(question=question)),
            ],
            scene="turtle_soup_judge",
            json_mode=True,
        )
        if self.debug:
            print(f"{C.DIM}[debug] judge raw: {resp.content}{C.R}")
        data = resp.json()
        return str(data.get("type", "irrelevant")), str(data.get("hint", "") or "")

    async def _judge_claim(self, claim: str) -> tuple[str, str]:
        assert self.puzzle is not None
        resp = await llm.chat(
            messages=[
                llm.LLMMessage(
                    role="system",
                    content=CLAIM_SYSTEM.format(
                        truth=self.puzzle.truth,
                        key_clues=format_clues(self.puzzle.key_clues),
                    ),
                ),
                llm.LLMMessage(role="user", content=CLAIM_USER.format(claim=claim)),
            ],
            scene="turtle_soup_claim",
            json_mode=True,
        )
        if self.debug:
            print(f"{C.DIM}[debug] claim raw: {resp.content}{C.R}")
        data = resp.json()
        return str(data.get("verdict", "wrong")), str(data.get("feedback", "") or "")

    async def _handle_hint(self) -> None:
        """CLI 端购买提示逻辑：直接揭示一条未发现的关键线索。"""
        assert self.puzzle is not None
        cfg = get_config()

        # 防超限
        if len(self.hints_purchased) >= cfg.max_hints_per_game:
            print(
                f"{C.RED}⚠️ 本局已购买 {cfg.max_hints_per_game} 次提示，"
                f"达到上限。{C.R}"
            )
            return

        # 检查是否还有未揭示的线索
        all_clues = self.puzzle.key_clues
        undiscovered_indices = [
            i for i in range(len(all_clues)) if i not in self.hints_purchased
        ]
        if not undiscovered_indices:
            print(f"{C.DIM}💡 所有关键线索都已揭示，靠你自己推理汤底啦！{C.R}")
            return

        # 直接揭示第一条未发现的线索
        target_idx = undiscovered_indices[0]
        clue_text = all_clues[target_idx]
        self.hints_purchased.append(target_idx)

        # 归入回顾列表
        self.key_clues_shown.append(("[购买提示]", clue_text))

        # 模拟扣币（CLI 本地）
        self.cli_coin -= cfg.hint_cost_coin
        hints_used = len(self.hints_purchased)
        print(
            f"\n{C.B}🔮 购买提示（{hints_used}/{cfg.max_hints_per_game}）{C.R}"
        )
        print(f"  {C.MAG}💡 关键线索：{clue_text}{C.R}")
        print(
            f"  {C.DIM}💰 花费 {cfg.hint_cost_coin} 金币{C.R}"
        )

    async def play(self) -> None:  # noqa: C901
        assert self.puzzle is not None
        puzzle = self.puzzle
        stars = "★" * puzzle.difficulty + "☆" * (5 - puzzle.difficulty)
        box(
            f"🐢 海龟汤 · {puzzle.category} · {stars}",
            f"《{puzzle.title}》\n\n{puzzle.surface}",
            color=C.CYAN,
        )
        info("提问以 ? 结尾；宣告以「汤底:」开头；输入 help 查看完整指令。")

        while True:
            text = prompt()
            kind = _classify(text)

            if kind == "quit":
                info("退出本局。")
                record_last_puzzle(_CLI_GROUP_ID, puzzle.id)
                return
            if kind == "help":
                print(HELP_TEXT)
                continue
            if kind == "status":
                print(f"{C.DIM}📊 已提问 {self.question_count}/{self.max_q} 次{C.R}")
                continue
            if kind == "recap":
                if not self.key_clues_shown:
                    print(f"{C.DIM}📜 暂无关键线索{C.R}")
                else:
                    print(f"\n{C.B}📜 关键线索回顾{C.R}")
                    for q, h in self.key_clues_shown:
                        print(f"  💡 {q} → {h}")
                continue
            if kind == "hint":
                await self._handle_hint()
                continue
            if kind == "giveup":
                box(
                    "🏳 投降 · 汤底揭晓",
                    f"【标题】《{puzzle.title}》\n\n{puzzle.truth}\n\n"
                    f"【关键线索】\n"
                    + "\n".join(f"  - {c}" for c in puzzle.key_clues),
                    color=C.MAG,
                )
                record_last_puzzle(_CLI_GROUP_ID, puzzle.id)
                return
            if kind == "chat":
                print(f"{C.DIM}（闲聊不消耗额度；提问用 ? 结尾；help 查指令）{C.R}")
                continue

            if kind == "question":
                if self.question_count >= self.max_q:
                    print(f"{C.RED}⚠️ 已达提问上限，请宣告汤底或 giveup。{C.R}")
                    continue
                try:
                    verdict, hint = await self._judge_question(text)
                except (LLMError, LLMJSONParseError) as e:
                    print(f"{C.RED}⚠️ 汤主走神了：{e}{C.R}")
                    continue

                if verdict == "claim_detected":
                    info("汤主认为你其实是在宣告汤底，自动进入宣告判定…")
                    kind = "claim"
                else:
                    self.question_count += 1
                    label = {
                        "yes": f"{C.GRN}✅ 是{C.R}",
                        "no": f"{C.RED}❌ 不是{C.R}",
                        "irrelevant": f"{C.DIM}🤔 与此无关{C.R}",
                        "key": (
                            f"{C.MAG}💡 关键线索：{hint}{C.R}"
                            if hint
                            else f"{C.MAG}💡 关键线索{C.R}"
                        ),
                    }.get(verdict, f"{C.DIM}🤔 与此无关{C.R}")
                    print(
                        f"汤主> {label}  "
                        f"{C.DIM}({self.question_count}/{self.max_q}){C.R}"
                    )
                    if verdict == "key" and hint:
                        self.key_clues_shown.append((text, hint))
                        # 参与奖：问到 key 线索 → score + coin
                        cfg = get_config()
                        self._show_reward(
                            score=cfg.reward_score_on_key_hit,
                            coin=cfg.reward_coin_on_key_hit,
                            label="关键线索命中",
                        )
                    elif verdict == "yes":
                        # 参与奖：问到 yes → score + coin
                        cfg = get_config()
                        self._show_reward(
                            score=cfg.reward_score_on_yes,
                            coin=cfg.reward_coin_on_yes,
                            label="提问正确",
                        )
                    continue

            if kind == "claim":
                claim_text = (
                    _strip_claim(text)
                    if text.startswith(("汤底", "答案", "宣告"))
                    else text
                )
                try:
                    verdict, feedback = await self._judge_claim(claim_text)
                except (LLMError, LLMJSONParseError) as e:
                    print(f"{C.RED}⚠️ 汤主走神了：{e}{C.R}")
                    continue

                if verdict == "correct":
                    # 赢家奖励：coin + score
                    cfg = get_config()
                    self._show_reward(
                        score=cfg.reward_score_on_win,
                        coin=cfg.reward_coin_on_win,
                        label="宣告成功",
                    )
                    box(
                        "🏆 宣告成功！",
                        f"{feedback or '你答对了！'}\n\n【完整汤底】\n{puzzle.truth}",
                        color=C.GRN,
                    )
                    info(f"本局胜利！共提问 {self.question_count} 次。")
                    record_last_puzzle(_CLI_GROUP_ID, puzzle.id)
                    return
                elif verdict == "partial":
                    # 部分正确也给少量参与奖
                    cfg = get_config()
                    self._show_reward(
                        score=cfg.reward_score_on_partial_hit,
                        label="部分正确",
                    )
                    print(f"汤主> {C.YEL}🟡 部分正确 · {feedback}{C.R}")
                    print(
                        f"{C.DIM}   可继续提问（? 结尾）"
                        f"或补充后重新宣告（汤底: 开头）{C.R}"
                    )
                else:
                    print(f"汤主> {C.RED}❌ 不对 · {feedback}{C.R}")
                    print(f"{C.DIM}   本次宣告不消耗提问额度，继续推理吧{C.R}")

    async def post_game_prompt(self) -> None:
        """局末追问：这题要标记为烂题吗？"""
        if self.puzzle is None:
            return
        # builtin 题不允许标记烂题（特权），不追问
        if self.puzzle.source == "builtin":
            return
        answer = prompt(
            f"这局《{self.puzzle.title}》要标记为烂题吗？（会从题库硬删）(y/N) > "
        ).strip().lower()
        if answer in ("y", "yes", "是", "烂", "差"):
            ok, msg = await mark_bad_by_group(_CLI_GROUP_ID)
            icon = "🗑" if ok else "ℹ️"
            print(f"{icon} {msg}")
        else:
            # 用户选了 N，清一下记忆避免残留
            from src.plugins.games.turtle_soup.puzzle_service import clear_last_puzzle
            clear_last_puzzle(_CLI_GROUP_ID)
