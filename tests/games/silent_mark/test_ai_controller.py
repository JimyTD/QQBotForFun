"""AI 控制器（`ai/controller.py`）。

这里锁的是**"AI 永远不会卡住对局"**这条底线：LLM 返回垃圾、超时、报错、
给出非法目标 —— 每一种都必须落到兜底上，让阶段继续推进。
顺带锁三层 JSON 容错与座位号解析（源项目在后者上栽过）。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from core import llm
from core.errors import LLMError
from src.plugins.games.silent_mark.ai import controller
from src.plugins.games.silent_mark.ai.logger import AILog
from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812

WOLF = "1"
VILLAGER = "4"


def _player(pid: str, seat: int, role: str, faction: str, *, alive: bool = True) -> dict:
    return {
        "pid": pid,
        "nickname": f"P{seat}",
        "seat": seat,
        "role": role,
        "faction": faction,
        "alive": alive,
        "items": [],
        "role_state": {},
    }


def _state(players: list[dict]) -> dict:
    return {
        "status": "playing",
        "round": 1,
        "phase": C.PHASE_NIGHT,
        "players": players,
        "night_actions": {
            "guard": None,
            "wolves": None,
            "witch": None,
            "seer": None,
            "gravedigger": None,
        },
        "night_current_role": None,
        "marking_order": [],
        "marking_current": 0,
        "pending_triggers": [],
        "history": {"rounds": [], "marks": [], "votes": [], "deaths": []},
        "winner": None,
        "win_condition": C.WIN_EDGE,
    }


PLAYERS = [
    _player(WOLF, 1, C.WEREWOLF, C.EVIL),
    _player("2", 2, C.WEREWOLF, C.EVIL),
    _player("3", 3, C.SEER, C.GOOD),
    _player(VILLAGER, 4, C.VILLAGER, C.GOOD),
]


def _llm(*contents: str | None):
    """按顺序喂模型回复；``None`` = 抛 LLMError。"""
    queue = list(contents)

    async def fake_chat(messages, *, scene, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        assert queue, "LLM 被多调用了一次（重试次数超出预期）"
        nxt = queue.pop(0)
        if nxt is None:
            raise LLMError("boom")
        return llm.LLMResponse(content=nxt, model="fake", usage={})

    return fake_chat


def _log(tmp_path) -> AILog:  # noqa: ANN001
    return AILog("test-session", root=tmp_path)


class _Fast:
    """把模拟思考延迟压成 0 —— 否则每个用例都要等好几秒。"""

    def __enter__(self):
        self._patch = patch.object(controller, "delay_seconds", lambda *a, **k: 0.0)
        self._patch.start()

    def __exit__(self, *exc):  # noqa: ANN002
        self._patch.stop()


# =====================================================================
# 纯函数：JSON 容错 / 座位号 / 延迟
# =====================================================================
def test_extract_json_handles_plain_fence_and_chain_of_thought() -> None:
    assert controller.extract_json('{"target": 6}') == {"target": 6}
    assert controller.extract_json('```json\n{"target": 3}\n```') == {"target": 3}
    # CoT：分析里夹了对象，结论在后面 → 必须取**最后一个**
    text = '我先想想 {"暂定": 1}\n最终决定 {"analysis": "因为", "target": 2}'
    assert controller.extract_json(text) == {"analysis": "因为", "target": 2}
    assert controller.extract_json("完全不是 JSON") is None


def test_target_pid_accepts_number_string_and_seat_suffix() -> None:
    state = _state(PLAYERS)

    assert controller.target_pid(4, state) == VILLAGER
    assert controller.target_pid("4", state) == VILLAGER
    assert controller.target_pid("4号", state) == VILLAGER
    assert controller.target_pid(99, state) is None  # 不存在的座位
    assert controller.target_pid(True, state) is None  # bool 不是座位号
    assert controller.target_pid(None, state) is None


def test_delay_respects_persona_pace_and_floor() -> None:
    import random

    from src.plugins.games.silent_mark.ai.persona import AI_PERSONAS

    fast = next(p for p in AI_PERSONAS if p.id == "gut_player")
    slow = next(p for p in AI_PERSONAS if p.id == "vote_tracker")
    rng = random.Random(1)

    fast_values = [controller.delay_seconds("voting", fast, rng=rng) for _ in range(40)]
    slow_values = [controller.delay_seconds("voting", slow, rng=rng) for _ in range(40)]

    assert min(fast_values) >= 0.8
    assert max(slow_values) <= 6.0 * slow.pace_factor * 1.8 + 0.001
    # 人格节奏确实起作用（同样的骰子下急性子整体更快）
    assert sum(fast_values) < sum(slow_values)


# =====================================================================
# 夜间行动
# =====================================================================
async def test_night_action_uses_llm_target(tmp_path) -> None:
    with _Fast(), patch.object(llm, "chat", _llm('{"analysis": "他很可疑", "target": 4}')):
        decision = await controller.night_action(
            state=_state(PLAYERS),
            pid=WOLF,
            targets=["3", VILLAGER],
            budget=30,
            log=_log(tmp_path),
        )

    assert decision.target == VILLAGER
    assert decision.source == "llm"
    assert decision.used_fallback is False
    assert "他很可疑" in decision.analysis


async def test_wolf_targeting_a_teammate_is_corrected_by_the_guard(tmp_path) -> None:
    """模型想刀队友 → 守卫必须纠正（这是要出对局日志、要能追责的事）。"""
    with _Fast(), patch.object(llm, "chat", _llm('{"analysis": "刀2号", "target": 2}')):
        decision = await controller.night_action(
            state=_state(PLAYERS),
            pid=WOLF,
            targets=["2", "3", VILLAGER],
            budget=30,
            log=_log(tmp_path),
        )

    assert decision.target != "2"
    assert decision.corrections and decision.corrections[0].field == "night_attack"
    assert decision.source == "guard"


async def test_garbage_twice_falls_back_and_never_raises(tmp_path) -> None:
    with _Fast(), patch.object(llm, "chat", _llm("胡说八道", "还是胡说八道")):
        decision = await controller.night_action(
            state=_state(PLAYERS),
            pid=WOLF,
            targets=["3", VILLAGER],
            budget=30,
            log=_log(tmp_path),
        )

    assert decision.used_fallback is True
    assert decision.source == "fallback"
    assert decision.target in {"3", VILLAGER}


async def test_llm_error_falls_back(tmp_path) -> None:
    with _Fast(), patch.object(llm, "chat", _llm(None, None)):
        decision = await controller.night_action(
            state=_state(PLAYERS),
            pid=WOLF,
            targets=["3"],
            budget=30,
            log=_log(tmp_path),
        )

    assert decision.used_fallback is True
    assert decision.target in {"3"}


async def test_illegal_target_falls_back(tmp_path) -> None:
    """模型给了候选之外的座位 → 不能放行（AI 与真人同权校验）。"""
    with _Fast(), patch.object(llm, "chat", _llm('{"target": 2}', '{"target": 1}')):
        decision = await controller.night_action(
            state=_state(PLAYERS),
            pid=WOLF,
            targets=["3", VILLAGER],
            budget=30,
            log=_log(tmp_path),
        )

    assert decision.target in {"3", VILLAGER}
    assert decision.used_fallback is True


async def test_witch_chooses_a_potion(tmp_path) -> None:
    witch = _player("5", 5, C.WITCH, C.GOOD)
    state = _state([*PLAYERS, witch])

    with _Fast(), patch.object(
        llm, "chat", _llm('{"analysis": "毒他", "potion": "poison", "target": 2}')
    ):
        decision = await controller.night_action(
            state=state, pid="5", targets=["1", "2"], budget=30, log=_log(tmp_path)
        )

    assert decision.action == "poison" and decision.target == "2"

    with _Fast(), patch.object(
        llm, "chat", _llm('{"analysis": "不用药", "potion": "none", "target": null}')
    ):
        decision = await controller.night_action(
            state=state, pid="5", targets=["1", "2"], budget=30, log=_log(tmp_path)
        )

    assert decision.action == "none" and decision.target is None


# =====================================================================
# 投票 / 标记 / 触发
# =====================================================================
async def test_vote_returns_a_candidate_or_nothing(tmp_path) -> None:
    with _Fast(), patch.object(llm, "chat", _llm('{"analysis": "投他", "target": 3}')):
        target = await controller.vote(
            state=_state(PLAYERS),
            pid=VILLAGER,
            candidates=["1", "2", "3"],
            budget=20,
            log=_log(tmp_path),
        )

    assert target == "3"


async def test_vote_falls_back_when_model_keeps_missing(tmp_path) -> None:
    with _Fast(), patch.object(llm, "chat", _llm('{"target": 99}', "not json")):
        target = await controller.vote(
            state=_state(PLAYERS),
            pid=VILLAGER,
            candidates=["1", "2", "3"],
            budget=20,
            log=_log(tmp_path),
        )

    assert target in {"1", "2", "3"}


async def test_marking_produces_a_rules_legal_submission(tmp_path) -> None:
    state = _state(PLAYERS)
    state["phase"] = C.PHASE_DAY_MARKING
    # 轮到 1 号发言（规则层会校验"是不是你的顺序"，所以要真的把它排在当前）
    state["marking_order"] = ["1", "2", "3", VILLAGER]
    state["marking_current"] = 0
    payload = json.dumps(
        {
            "analysis": "3号像预言家",
            "identity": "平民",
            "reason": "intuition",
            "evaluations": [
                {"target": 3, "identity": "好人", "reason": "intuition"},
                {"target": 4, "identity": "好人", "reason": "mark_analysis"},
            ],
        },
        ensure_ascii=False,
    )
    log = _log(tmp_path)
    with _Fast(), patch.object(llm, "chat", _llm(payload, payload)):
        marks = await controller.marking(
            state=state, pid=WOLF, budget=30, log=log
        )

    logged = log.path.read_text(encoding="utf-8") if log.path.exists() else ""
    # 把决策日志塞进断言消息：一旦被规则层拒了，这里能直接看到原因
    assert marks is not None, logged
    assert "marking_rejected" not in logged, logged
    assert marks["identity_mark"]["identity"] in {"平民", "好人", "神职"}
    assert marks["identity_mark"]["identity"] != C.IDENTITY_WOLF  # 狼人不许自曝
    assert {e["target"] for e in marks["evaluation_marks"]} <= {"2", "3", VILLAGER}


async def test_marking_falls_back_on_garbage(tmp_path) -> None:
    state = _state(PLAYERS)
    state["phase"] = C.PHASE_DAY_MARKING
    state["marking_order"] = ["1", "2", "3", VILLAGER]
    state["marking_current"] = 0
    with _Fast(), patch.object(llm, "chat", _llm("???", "???")):
        marks = await controller.marking(
            state=state, pid=WOLF, budget=30, log=_log(tmp_path)
        )

    assert marks is not None  # 兜底必须给得出东西，否则阶段推进会缺料
    assert marks["identity_mark"]["identity"] != C.IDENTITY_WOLF


async def test_trigger_skip_and_target(tmp_path) -> None:
    state = _state(PLAYERS)
    hunter = state["players"][3]

    with _Fast(), patch.object(
        llm, "chat", _llm('{"analysis": "赌一把", "action": "shoot", "target": 1}')
    ):
        target = await controller.trigger(
            state=state,
            pid=hunter["pid"],
            trigger_type="hunter_shoot",
            targets=["1", "2", "3"],
            budget=20,
            log=_log(tmp_path),
        )
    assert target == "1"

    with _Fast(), patch.object(
        llm, "chat", _llm('{"analysis": "不开枪", "action": "skip", "target": null}')
    ):
        target = await controller.trigger(
            state=state,
            pid=hunter["pid"],
            trigger_type="hunter_shoot",
            targets=["1", "2", "3"],
            budget=20,
            log=_log(tmp_path),
        )
    assert target is None


# =====================================================================
# 超时：AI 有超时、真人没有
# =====================================================================
async def test_timeout_returns_none_and_logs(tmp_path) -> None:
    log = _log(tmp_path)

    async def slow():
        await asyncio.sleep(5)

    result = await controller.with_budget(slow(), budget=0.01, log=log, kind="night", pid=WOLF)

    assert result is None
    assert "timeout" in log.path.read_text(encoding="utf-8")


async def test_timeout_does_not_swallow_cancellation(tmp_path) -> None:
    """`/结束` 靠 CancelledError 打断等待 —— 绝不能被"超时兜底"吃掉。"""
    log = _log(tmp_path)

    async def slow():
        await asyncio.sleep(5)

    task = asyncio.create_task(
        controller.with_budget(slow(), budget=30, log=log, kind="night", pid=WOLF)
    )
    await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:  # pragma: no cover - 走到这里说明取消被吞了
        raise AssertionError("CancelledError 被吞掉了，`/结束` 会失效")
