"""趣味问答的 CLI Adapter。

MODES 权威清单定义在 src/plugins/games/trivia/game.py 的 GameBase.MODES。
本 adapter 直接复用那份定义，保证 CLI / bot 一致（铁律）。

单人 CLI 流程：
- 开局选类型 → 生成第 1 题 → 展示线索 1
- 用户输入：答案 / 「线索」/ 「跳过」/ 「状态」/ 「退出」
- 10 题结束 → 展示结算（CLI 下不入 economy.score）
"""

from __future__ import annotations

from src.plugins.games.trivia.answer_matcher import looks_like_answer, match, normalize
from src.plugins.games.trivia.config import get_config
from src.plugins.games.trivia.game import TriviaGame, _coin_for_tier, _score_for_tier
from src.plugins.games.trivia.prompts import TYPE_STYLE_GUIDES, type_display_name
from src.plugins.games.trivia.puzzle_generator import (
    PuzzleGenerationError,
    generate_puzzle,
)

from .base import C, GameCLIAdapter, box, info, prompt


HELP_TEXT = (
    "用法：\n"
    "  · 直接输入：你的答案（不用带前缀）\n"
    "  · 线索 / 再来一条：要下一条线索\n"
    "  · 跳过 / 不会：放弃本题\n"
    "  · status / 状态：查看进度\n"
    "  · quit / 退出：提前结束本局"
)

_CLI_PLAYER_NAME = "你"


class TriviaCLIAdapter:
    game_name = TriviaGame.name + " ❓"
    MODES = TriviaGame.MODES  # 与 bot 共享

    def __init__(self, *, debug: bool = False) -> None:
        self.debug = debug
        self.type_id: str = "country"
        self.cfg = get_config()
        # 每题状态
        self.puzzle = None
        self.clues_shown = 0
        # 全局状态
        self.current_index = 0
        self.total = self.cfg.total_questions_per_game
        self.score: int = 0
        self.coin: int = 0
        self.history: list[dict] = []

    # ---------- Adapter 协议 ----------
    async def start(self, mode_id: str) -> None:
        if mode_id not in TYPE_STYLE_GUIDES:
            raise ValueError(f"unknown type: {mode_id}")
        self.type_id = mode_id
        self.current_index = 0
        self.score = 0
        self.coin = 0
        self.history = []
        await self._prepare_next()

    async def play(self) -> None:  # noqa: C901
        box(
            f"❓ {type_display_name(self.type_id)}",
            f"本局共 {self.total} 题。\n"
            f"猜到答案直接输入，发「线索」要下一条，发「跳过」放弃。\n"
            f"输入 help 查看完整指令。",
            color=C.CYAN,
        )

        # 展示第 1 题
        self._announce_current()

        while True:
            if self.puzzle is None:
                # 上一题出题失败，直接推进
                if not await self._advance_or_end():
                    return
                self._announce_current()
                continue

            text = prompt()
            kind = _classify(text)

            if kind == "quit":
                self._announce_end("中途结束")
                return
            if kind == "help":
                print(HELP_TEXT)
                continue
            if kind == "status":
                print(
                    f"{C.DIM}📊 第 {self.current_index + 1}/{self.total} 题 · "
                    f"已展示 {self.clues_shown}/{self.cfg.max_clues_per_puzzle} 条线索 · "
                    f"本局 {self.score} 分{C.R}"
                )
                continue
            if kind == "more_clue":
                self._print_next_clue()
                continue
            if kind == "skip":
                print(f"{C.DIM}⏭ 你跳过了本题{C.R}")
                self._settle_question(winner=False, clues_used=self.clues_shown)
                if not await self._advance_or_end():
                    return
                self._announce_current()
                continue
            if kind == "chat":
                print(f"{C.DIM}（输入不像答案；help 查指令）{C.R}")
                continue

            # kind == "answer"
            assert self.puzzle is not None
            if match(text, self.puzzle.answer, self.puzzle.aliases):
                score_delta = _score_for_tier(self.clues_shown)
                coin_delta = _coin_for_tier(self.clues_shown)
                self.score += score_delta
                self.coin += coin_delta
                box(
                    "🎉 答对了！",
                    f"+{score_delta} 分 · +{coin_delta} 金币"
                    f"（{self.clues_shown} 条线索内猜中）\n\n"
                    f"📖 答案：{self.puzzle.answer}\n"
                    f"💡 {self.puzzle.explanation}",
                    color=C.GRN,
                )
                self._settle_question(winner=True, clues_used=self.clues_shown)
                if not await self._advance_or_end():
                    return
                self._announce_current()
            else:
                print(f"{C.RED}❌ 不对哦，继续~{C.R}")

    # ---------- 内部 ----------
    async def _prepare_next(self) -> None:
        """生成当前 current_index 对应的题目。失败则 puzzle=None 占位。"""
        avoid = self._collect_used_names()
        try:
            self.puzzle = await generate_puzzle(self.type_id, avoid=avoid)
            self.clues_shown = 1
        except PuzzleGenerationError as e:
            print(f"{C.RED}⚠️ 第 {self.current_index + 1} 题出题失败：{e}{C.R}")
            self.puzzle = None
            self.clues_shown = 0

    def _collect_used_names(self) -> list[str]:
        """本局已出过的答案+别名，用于 generate_puzzle 的 avoid。"""
        used: list[str] = []
        for item in self.history:
            if not isinstance(item, dict):
                continue
            ans = item.get("answer")
            if isinstance(ans, str) and ans.strip():
                used.append(ans.strip())
            for a in item.get("aliases", []) or []:
                if isinstance(a, str) and a.strip():
                    used.append(a.strip())
        return used

    def _announce_current(self) -> None:
        if self.puzzle is None:
            return
        header = f"{type_display_name(self.type_id)} · 第 {self.current_index + 1}/{self.total} 题"
        body = f"💭 线索 1：{self.puzzle.clues[0]}"
        box(header, body, color=C.CYAN)

    def _print_next_clue(self) -> None:
        if self.puzzle is None:
            return
        if self.clues_shown >= self.cfg.max_clues_per_puzzle:
            print(f"{C.DIM}📜 5 条线索都出完啦~ 实在不会就输入「跳过」吧{C.R}")
            return
        self.clues_shown += 1
        print(
            f"{C.MAG}💭 线索 {self.clues_shown}：{self.puzzle.clues[self.clues_shown - 1]}{C.R}  "
            f"{C.DIM}({self.clues_shown}/{self.cfg.max_clues_per_puzzle}){C.R}"
        )

    def _settle_question(self, *, winner: bool, clues_used: int) -> None:
        if self.puzzle is None:
            return
        awarded = _score_for_tier(clues_used) if winner else 0
        if not winner:
            print(f"{C.DIM}📖 答案：{self.puzzle.answer}{C.R}")
            if self.puzzle.explanation:
                print(f"{C.DIM}💡 {self.puzzle.explanation}{C.R}")
        self.history.append(
            {
                "answer": self.puzzle.answer,
                "aliases": list(self.puzzle.aliases),
                "winner": _CLI_PLAYER_NAME if winner else None,
                "clues_used": clues_used,
                "awarded": awarded,
            }
        )

    async def _advance_or_end(self) -> bool:
        """推进到下一题；若已到终点则收尾并返回 False。"""
        self.current_index += 1
        self.puzzle = None
        self.clues_shown = 0
        if self.current_index >= self.total:
            self._announce_end("对局完成")
            return False
        await self._prepare_next()
        return True

    def _announce_end(self, status: str) -> None:
        # 单人局：只要有得分就发 MVP 奖励（score + coin 双轨）
        score_bonus = self.cfg.mvp_score_bonus if self.score > 0 else 0
        coin_bonus = self.cfg.mvp_coin_bonus if self.score > 0 else 0
        total_score = self.score + score_bonus
        total_coin = self.coin + coin_bonus
        lines = [
            f"类型：{type_display_name(self.type_id)}",
            f"共答：{len(self.history)} 题",
            "",
            f"基础得分：{self.score} 分 · {self.coin} 金币",
        ]
        if score_bonus or coin_bonus:
            lines.append(f"MVP 奖励：+{score_bonus} 分 · +{coin_bonus} 金币")
        lines.append(f"总计：{total_score} 分 · {total_coin} 金币")
        box(f"🏆 趣味问答 · {status}", "\n".join(lines), color=C.MAG)
        info("CLI 模式不会写入全局积分榜 / 钱包")


# ---------- 消息分类（与 bot 保持一致） ----------
_MORE_CLUE_WORDS = frozenset(
    normalize(w) for w in ("线索", "再来一条", "更多线索", "提示", "hint", "clue")
)
_SKIP_WORDS = frozenset(
    normalize(w) for w in ("跳过", "不会", "pass", "下一题", "skip")
)


def _classify(text: str) -> str:
    s = text.strip()
    if not s:
        return "chat"
    low = s.lower()
    if low in ("help", "?", "？", "帮助"):
        return "help"
    if low in ("status", "状态"):
        return "status"
    if low in ("quit", "exit", "退出"):
        return "quit"
    norm = normalize(s)
    if norm in _MORE_CLUE_WORDS:
        return "more_clue"
    if norm in _SKIP_WORDS:
        return "skip"
    cfg = get_config()
    if looks_like_answer(s, cfg.max_answer_length):
        return "answer"
    return "chat"
