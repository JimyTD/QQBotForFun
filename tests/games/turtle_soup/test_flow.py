"""海龟汤完整流程集成测试（LLM mock）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from core.types import EndReason
from src.plugins.games.turtle_soup.game import TurtleSoupGame
from src.plugins.games.turtle_soup.puzzle_service import PuzzleData
from src.testing.harness import GameTestHarness


_FAKE_PUZZLE = PuzzleData(
    id=1,
    title="测试汤",
    category="日常",
    surface="这是一段汤面。",
    truth="这是完整汤底。",
    key_clues=["线索A", "线索B"],
    difficulty=3,
    source="builtin",
)


async def test_full_flow_win() -> None:
    """玩家问一个问题 → 宣告正确 → 胜利结束。"""

    async def fake_obtain() -> PuzzleData:
        return _FAKE_PUZZLE

    async def fake_mark_win(_pid: int) -> None:
        return None

    # LLM 判定 mock：第一次 -> yes；第二次（宣告） -> correct
    call_log: list[dict] = []

    async def fake_chat(messages, *, scene, **kwargs):  # type: ignore[no-untyped-def]
        call_log.append({"scene": scene})
        from core.llm import LLMResponse

        if scene == "turtle_soup_judge":
            return LLMResponse(content='{"type": "yes", "hint": ""}', model="mock")
        if scene == "turtle_soup_claim":
            return LLMResponse(
                content='{"verdict": "correct", "feedback": "很棒！"}',
                model="mock",
            )
        return LLMResponse(content="{}", model="mock")

    with patch(
        "src.plugins.games.turtle_soup.game.obtain_puzzle",
        AsyncMock(side_effect=fake_obtain),
    ), patch(
        "src.plugins.games.turtle_soup.game.mark_win",
        AsyncMock(side_effect=fake_mark_win),
    ), patch("core.llm.chat", AsyncMock(side_effect=fake_chat)):

        async with GameTestHarness(TurtleSoupGame, players=[1001], group_id=42) as h:
            await h.start()
            assert h.broadcasts_contain("测试汤") or h.broadcasts_contain("《测试汤》")
            # 提问
            await h.send(1001, "他活着吗？")
            assert h.broadcasts_contain("是")
            # 宣告
            await h.send(1001, "汤底: 他是魔法师")
            # 等待事件链走完
            assert h.runner is not None
            # 游戏应已因 correct 走到 end
            assert h.runner._ended
            assert h.runner.ctx.state.get("winner_id") == 1001


async def test_flow_giveup() -> None:
    async def fake_obtain() -> PuzzleData:
        return _FAKE_PUZZLE

    with patch(
        "src.plugins.games.turtle_soup.game.obtain_puzzle",
        AsyncMock(side_effect=fake_obtain),
    ):
        async with GameTestHarness(TurtleSoupGame, players=[1001], group_id=43) as h:
            await h.start()
            assert h.runner is not None
            await h.runner.end(EndReason.ABORTED)
            assert h.runner._ended
            # 揭晓汤底应被广播
            assert any("完整汤底" in b or "汤底揭晓" in b or "完整汤底" in b for b in h.broadcasts)


async def test_flow_judge_irrelevant() -> None:
    async def fake_obtain() -> PuzzleData:
        return _FAKE_PUZZLE

    async def fake_chat(messages, *, scene, **kwargs):  # type: ignore[no-untyped-def]
        from core.llm import LLMResponse

        return LLMResponse(content='{"type":"irrelevant","hint":""}', model="mock")

    with patch(
        "src.plugins.games.turtle_soup.game.obtain_puzzle",
        AsyncMock(side_effect=fake_obtain),
    ), patch("core.llm.chat", AsyncMock(side_effect=fake_chat)):
        async with GameTestHarness(TurtleSoupGame, players=[1001], group_id=44) as h:
            await h.start()
            await h.send(1001, "完全不沾边？")
            assert h.broadcasts_contain("与此无关")
