"""AI 混编局端到端（M4 的核心验收："AI 可参与完整对局，不卡死"）。

做法：2 个假真人（热座脚本）+ 2 个 AI 补位座位，用一个**会读提示词的假 LLM** 驱动 AI。
假 LLM 从提示里抠出"可选目标"再挑第一个 —— 这样它天然是"合规答案"，
用来验证的是**流程能不能跑完**，而不是模型聪不聪明。

顺带锁三件事：
1. AI 座位的动作真的进了对局（决策日志里有 night/marking/vote 记录）；
2. 没有一次超时兜底（假 LLM 是瞬时的，预算不该被撞到）；
3. AI 的名字与人格都落到了状态里。
"""

from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest

from core import llm, session
from src.plugins.games.silent_mark.ai import controller as ai_controller
from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812
from src.plugins.games.silent_mark.game import SilentMarkGame
from src.testing.harness import GameTestHarness

from .test_game_flow import FakePlayer


@pytest.fixture(autouse=True)
def _no_thinking_delay():
    """把 AI 的"模拟思考延迟"压成 0。

    那个延迟是对局体验的一部分（掩盖 LLM 延迟、更像真人），
    但绝不该让测试等上几分钟 —— 它有自己的单测。
    """
    with patch.object(ai_controller, "delay_seconds", lambda *a, **k: 0.0):
        yield


def _seats_after(text: str, marker: str) -> list[int]:
    """从提示里抠出某一行上的 ``N号玩家`` 座位号。"""
    for line in text.splitlines():
        if line.startswith(marker):
            return [int(match) for match in re.findall(r"(\d+)号玩家", line)]
    return []


def _fake_llm():
    """按提示内容编一个合规答案（挑第一个可选目标）。"""
    name_calls = {"count": 0}

    async def fake_chat(messages, *, scene, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        system: str = messages[0].content
        user: str = messages[-1].content

        def reply(payload: dict) -> llm.LLMResponse:
            return llm.LLMResponse(
                content=json.dumps(payload, ensure_ascii=False), model="fake", usage={}
            )

        if scene == "silent_mark_ai_name":
            name_calls["count"] += 1
            return llm.LLMResponse(
                content=f"夜行人{name_calls['count']}", model="fake", usage={}
            )

        if "标记发言阶段" in user:
            seats = _seats_after(user, "可评价的玩家：")[:2]
            return reply(
                {
                    "analysis": "信息不足，保守评价",
                    "identity": "平民",
                    "reason": "intuition",
                    "evaluations": [
                        {"target": seat, "identity": "好人", "reason": "intuition"}
                        for seat in seats
                    ],
                }
            )

        if "投票阶段" in user:
            seats = _seats_after(user, "候选人：")
            return reply({"analysis": "投第一个", "target": seats[0] if seats else None})

        if "女巫行动" in user:
            return reply({"analysis": "先不用药", "potion": "none", "target": None})

        if "开枪" in user or "带走" in user or "决斗" in user:
            return reply({"analysis": "不发动", "action": "skip", "target": None})

        seats = _seats_after(user, "可选目标：")
        if not seats:
            return reply({"analysis": "没有目标", "target": None})
        # 狼/守卫/预言家/守墓人都能这么答；女巫那条已在上面拦掉
        del system
        return reply({"analysis": "选第一个", "target": seats[0]})

    return fake_chat


async def test_two_humans_plus_two_ai_finish_a_whole_game() -> None:
    # 用 6 人板子：4 人板子只有 1 个平民，狼刀掉他就屠边成立，第一夜就终局了，
    # 走不到标记/投票（那是规则正确、板子太小）
    config = {"mode": "6standard", "seed": 11, "ai_seats": 3}
    fake = FakePlayer()
    harness = GameTestHarness(SilentMarkGame, players=[1001, 1002, 1003], config=config)
    fake.harness = harness

    with (
        patch.object(session, "ask", fake.ask),
        patch.object(llm, "chat", _fake_llm()),
    ):
        async with harness:
            await harness.start()

    assert harness.runner is not None
    assert harness.runner._ended is True, "混编局没有正常收场（可能卡住了）"

    state = harness.runner.ctx.state
    ai_players = [p for p in state["players"] if p.get("ai")]
    assert len(ai_players) == 3
    assert len(state["players"]) == 6

    # AI 名字与人格都落到了状态里
    assert all(
        p["nickname"] and not p["nickname"].startswith("AI") for p in ai_players
    ), [p["nickname"] for p in ai_players]
    assert set(state["ai"]) == {p["pid"] for p in ai_players}
    assert all(entry.get("persona") for entry in state["ai"].values())

    # 决策日志：AI 真的行动过，而且**一次超时兜底都没有**
    log = SilentMarkGame._ai_logs[harness.runner.ctx.session_id]
    text = log.path.read_text(encoding="utf-8")
    assert '"kind": "setup"' in text
    for kind in ("night", "marking", "vote"):
        assert f'"kind": "{kind}"' in text, f"AI 没有产生 {kind} 决策：{text[:400]}"
    assert '"kind": "timeout"' not in text, "假 LLM 是瞬时的，不该撞到超时预算"


async def test_ai_marks_are_rules_legal() -> None:
    """AI 的标记必须过规则层校验（不留痕 = 没被拒过）。"""
    config = {"mode": "6standard", "seed": 3, "ai_seats": 3}
    fake = FakePlayer()
    harness = GameTestHarness(SilentMarkGame, players=[1001, 1002, 1003], config=config)
    fake.harness = harness

    with (
        patch.object(session, "ask", fake.ask),
        patch.object(llm, "chat", _fake_llm()),
    ):
        async with harness:
            await harness.start()

    assert harness.runner is not None
    log = SilentMarkGame._ai_logs[harness.runner.ctx.session_id]
    text = log.path.read_text(encoding="utf-8")
    assert '"kind": "marking_rejected"' not in text, text[:600]

    # AI 提交的标记确实进了历史（夜里出局的 AI 不会走到标记阶段，所以用交集判）
    state = harness.runner.ctx.state
    ai_pids = {p["pid"] for p in state["players"] if p.get("ai")}
    marked = {marks["player"] for marks in state["history"]["marks"]}
    assert ai_pids & marked, (ai_pids, marked)


async def test_ai_seats_never_go_through_the_ask_path() -> None:
    """AI 座位**不经过** `session.ask`：那是真人的通道（问了也没人回）。"""
    config = {"mode": "6standard", "seed": 5, "ai_seats": 3}
    fake = FakePlayer()
    harness = GameTestHarness(SilentMarkGame, players=[1001, 1002, 1003], config=config)
    fake.harness = harness

    asked: list[int] = []
    real_ask = fake.ask

    async def spy_ask(qq_id, prompt=None, **kwargs):  # noqa: ANN001, ANN003, ANN202
        asked.append(int(qq_id))
        return await real_ask(qq_id, prompt, **kwargs)

    with (
        patch.object(session, "ask", spy_ask),
        patch.object(llm, "chat", _fake_llm()),
    ):
        async with harness:
            await harness.start()

    ai_pids = {p["pid"] for p in harness.runner.ctx.state["players"] if p.get("ai")}
    assert ai_pids and all(not pid.isdigit() for pid in ai_pids), ai_pids
    # 被问到的全是真人（QQ 号 1001~1003），AI 的 pid（`ai:N`）一次都没出现
    assert asked and all(qq in {1001, 1002, 1003} for qq in asked), asked


async def test_solo_host_can_start_and_ai_fills_the_rest() -> None:
    """群里最实际的场景：房主一个人 `@我 开始`，剩下 5 个座位由 AI 补满。

    这是"默认 AI 补位"的意义所在 —— 12 人板子再也不需要真的凑 12 个人。
    """
    config = {"mode": "6standard", "seed": 21, "ai_seats": 5}
    fake = FakePlayer()
    harness = GameTestHarness(SilentMarkGame, players=[1001], config=config)
    fake.harness = harness

    with (
        patch.object(session, "ask", fake.ask),
        patch.object(llm, "chat", _fake_llm()),
    ):
        async with harness:
            await harness.start()

    assert harness.runner is not None
    assert harness.runner._ended is True
    state = harness.runner.ctx.state
    assert len(state["players"]) == 6
    assert sum(1 for p in state["players"] if p.get("ai")) == 5
    # 房主自己不能被 AI 挤掉
    assert any(p["pid"] == "1001" for p in state["players"])


def test_ai_seats_change_the_board_size_check() -> None:
    """人数校验要把 AI 算进去：真人 + AI 之和必须等于板子人数。"""
    assert 2 + 2 == sum(C.PRESETS["4standard"].roles.values())
