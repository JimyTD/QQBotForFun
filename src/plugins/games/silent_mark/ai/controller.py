"""AI 玩家控制器（移植自源项目 `ai/AIPlayerController.ts`）。

把"这个 AI 座位该行动了"变成一次**可用决策**，三级保证：

1. LLM 正常 → 三层容错解析 JSON → 守卫纠正 → 走**同一条**规则层校验；
2. 解析/校验失败 → **重试 1 次**（把失败原因塞回提示里让它改）；
3. 仍然失败 → 角色专属**确定性兜底**（`engine/fallback.py`，与真人超时兜底同一条路径）。

移植时特别要保住的三件事：

- **超时**：整个决策包在 ``asyncio.wait_for(budget)`` 里 —— 本仓库大原则是
  「AI 有超时，真人没有」。⚠️ 只接 ``TimeoutError``，**绝不接 ``CancelledError``**：
  `/结束` 就是靠它把等待打断的（它继承自 BaseException，本来也不会被 ``except Exception`` 捞到）。
- **思考延迟**：分布照抄源项目（两次随机取小 + 人格节奏 + 5% 秒交 / 4% 卡住）。
  在 QQ 群里这个延迟反而是优点：掩盖 LLM 延迟，让 AI 更像真人。
- **座位号解析**：同时接受数字、数字字符串与 ``3号``（源项目那处正则曾多写一个反斜杠，
  把模型答对的座位号判成非法）。这里直接复用真人的 `syntax.parse_seat`，两边不漂移。
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any

from nonebot import logger

from core import llm
from core.errors import LLMConfigError, LLMError

#: ⚠️ `LLMConfigError` 不是 `LLMError` 的子类（继承 GameError）。
#: 漏掉它 = 没配 api_key 时每一次 AI 决策都会抛出去，直接把对局打断。
_LLM_FAILURES = (LLMError, LLMConfigError)

from .. import syntax
from ..engine import constants as C  # noqa: N812
from ..engine import fallback, resolve
from ..engine.types import GameStateDict, find_player
from . import context as ai_context
from . import guard, prompts
from .logger import AILog
from .persona import Persona, persona_of

#: 模拟思考延迟范围（秒）——照抄源项目 `DELAY_RANGES`
DELAY_RANGES: dict[str, tuple[float, float]] = {
    "night": (3.0, 8.0),
    "marking": (5.0, 15.0),
    "voting": (2.0, 6.0),
    "trigger": (2.0, 5.0),
}


@dataclass
class Decision:
    """一次 AI 决策的完整结果（含"为什么"）。"""

    action: str
    target: str | None = None
    potion: str | None = None
    analysis: str = ""
    corrections: list[guard.GuardCorrection] = field(default_factory=list)
    used_fallback: bool = False
    source: str = "llm"  # llm | fallback | guard


def delay_seconds(kind: str, persona: Persona, *, rng: random.Random | None = None) -> float:
    """模拟思考延迟（秒）。

    - 基础延迟用"两次随机取小值"：多数偏快、少数偏慢，比均匀分布更像真人的长尾；
    - 再乘人格节奏（急性子 <1、谨慎型 >1）；
    - 少量异常值：真人偶尔秒交，也会偶尔卡住。
    """
    rand = rng or random
    low, high = DELAY_RANGES.get(kind, (2.0, 5.0))
    delay = low + min(rand.random(), rand.random()) * (high - low)
    delay *= persona.pace_factor
    dice = rand.random()
    if dice < 0.05:
        delay *= 0.3
    elif dice > 0.96:
        delay *= 1.8
    return max(0.8, delay)


def extract_json(content: str) -> dict[str, Any] | None:
    """三层容错地抠出 JSON。

    glm 系模型在 json_mode 下一般直接给 JSON，但线上仍会遇到"分析 + 代码块"、
    "分析里夹了一个对象、结论在后面"这类输出，所以三层都要有：
    直接解析 → markdown 代码块 → **从后往前**找完整对象（结论通常在最后）。
    """
    text = content.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, TypeError):
        pass

    fence = _fenced_json(text)
    if fence is not None:
        return fence

    for candidate in reversed(_brace_objects(text)):
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict) and parsed:
            return parsed
    return None


def _fenced_json(text: str) -> dict[str, Any] | None:
    start = text.find("```")
    while start != -1:
        body_start = text.find("\n", start)
        if body_start == -1:
            return None
        end = text.find("```", body_start)
        if end == -1:
            return None
        body = text[body_start:end].strip()
        if body.startswith("json"):
            body = body[4:].strip()
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, TypeError):
            pass
        start = text.find("```", end + 3)
    return None


def _brace_objects(text: str) -> list[str]:
    """按括号配对切出所有顶层 ``{...}``（不做字符串转义处理，够用且不会误吞）。"""
    found: list[str] = []
    depth = 0
    start = -1
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start != -1:
                found.append(text[start : index + 1])
                start = -1
            elif depth < 0:
                depth = 0
    return found


def target_pid(seat_value: Any, state: GameStateDict) -> str | None:
    """模型给的座位号 → pid。

    同时接受 ``6`` / ``"6"`` / ``"6号"``（复用真人那套 `syntax.parse_seat`）。
    """
    if isinstance(seat_value, bool):
        return None
    if isinstance(seat_value, int):
        text = str(seat_value)
    elif isinstance(seat_value, str):
        text = seat_value
    else:
        return None
    seat = syntax.parse_seat(text)
    if seat is None:
        return None
    for player in state["players"]:
        if player["seat"] == seat:
            return player["pid"]
    return None


# =====================================================================
# LLM 调用
# =====================================================================
async def _ask(
    state: GameStateDict, pid: str, user_prompt: str, *, max_tokens: int | None = None
) -> str | None:
    """一次调用。失败返回 None（由调用方决定重试或兜底）。

    ⚠️ ``CancelledError`` 不接：`/结束` 靠它打断。
    """
    player = find_player(state, pid)
    if player is None:
        return None
    system = prompts.system_prompt(
        seat=player["seat"],
        role=player["role"],
        faction=player["faction"],
        win_condition=state.get("win_condition") or C.WIN_EDGE,
    )
    history_text = ai_context.context_to_text(ai_context.build_context(state, pid))
    messages = [
        llm.LLMMessage(role="system", content=system),
        llm.LLMMessage(role="user", content=f"{history_text}\n\n{user_prompt}"),
    ]
    try:
        response = await llm.chat(
            messages, scene="silent_mark_ai", max_tokens=max_tokens
        )
    except _LLM_FAILURES as exc:
        logger.warning(f"[silent_mark.ai] {pid} 调用失败：{exc!r}")
        return None
    return response.content


def _record(
    log: AILog,
    kind: str,
    pid: str,
    persona: Persona,
    *,
    decision: Decision,
    raw: str | None = None,
    elapsed: float | None = None,
    note: str = "",
) -> None:
    log.record(
        kind,
        pid=pid,
        persona=persona.id,
        source=decision.source,
        action=decision.action,
        target=decision.target,
        analysis=decision.analysis[:400],
        corrections=[c.as_dict() for c in decision.corrections],
        fallback=decision.used_fallback,
        note=note,
        raw=(raw or "")[:800],
        elapsed=round(elapsed, 2) if elapsed is not None else None,
    )


# =====================================================================
# 夜间行动
# =====================================================================
async def night_action(
    *,
    state: GameStateDict,
    pid: str,
    targets: list[str],
    witch_info: dict | None = None,
    budget: float,
    log: AILog,
    rng: random.Random | None = None,
) -> Decision:
    """夜间的 AI 决策。``targets`` 是**规则层给的合法候选**（pid）。

    返回的 ``target`` 一定在 ``targets`` 里（或为 None）——合法性由规则层定义，
    这里不额外放宽，也不为 AI 开后门。
    """
    player = find_player(state, pid)
    if player is None:
        return Decision(action="skip", used_fallback=True, source="fallback")
    persona = persona_of(state, pid)
    rand = rng or random
    role = player["role"]

    started = time.monotonic()
    await asyncio.sleep(delay_seconds("night", persona, rng=rand))
    listed = "、".join(f"{find_player(state, t)['seat']}号玩家" for t in targets if find_player(state, t))
    prompt = prompts.night_action_prompt(
        role=role,
        targets=sorted(
            (find_player(state, t)["seat"] for t in targets if find_player(state, t))
        ),
        witch_info=witch_info,
    )

    decision: Decision | None = None
    for attempt in (1, 2):
        ask_prompt = (
            prompt
            if attempt == 1
            else f"{prompt}\n\n（注意：上次回复无法解析，请只返回规定格式的 JSON）"
        )
        raw = await _ask(state, pid, ask_prompt)
        if raw is None:
            continue
        candidate = _build_night_decision(
            state, pid, role, extract_json(raw), targets, rng=rand
        )
        if not candidate.used_fallback:
            decision = candidate
            break

    if decision is None:
        # 两次都没拿到可用决策（含调用直接失败）→ **兜底必须真的落地**，
        # 否则会退回一个"跳过"，对狼人/守卫来说是非法动作，阶段会卡住。
        decision = _fallback_night(state, pid, role, targets, rng=rand)
        decision.analysis = decision.analysis or "两次都没拿到可用决策"
    _record(
        log,
        "night",
        pid,
        persona,
        decision=decision,
        elapsed=time.monotonic() - started,
        note=f"候选={listed}",
    )
    return decision


def _build_night_decision(
    state: GameStateDict,
    pid: str,
    role: str,
    parsed: dict[str, Any] | None,
    targets: list[str],
    *,
    rng: random.Random,
    raw: str | None = None,
) -> Decision:
    if not parsed:
        return _fallback_night(state, pid, role, targets, rng=rng)

    analysis = str(parsed.get("analysis") or "")
    action = str(parsed.get("action") or "")
    potion = parsed.get("potion")
    potion = str(potion) if potion else None

    # 女巫：药水三选一
    if role == C.WITCH:
        if potion not in {"antidote", "poison", "none"}:
            return _fallback_night(state, pid, role, targets, rng=rng)
        if potion == "none":
            return Decision(action="none", potion="none", analysis=analysis)
        if potion == "antidote":
            return Decision(action="antidote", potion="antidote", analysis=analysis)
        chosen = target_pid(parsed.get("target"), state)
        if chosen not in targets:
            return _fallback_night(state, pid, role, targets, rng=rng)
        # 女巫没有"不刀队友/不重复查验"这类约束，守卫无事可做
        return Decision(action="poison", target=chosen, potion="poison", analysis=analysis)

    if action == "skip":
        return Decision(action="skip", analysis=analysis)

    if parsed.get("target") is None:
        # 空目标只有一种合法情形：守墓人且场上没有可验的死者（提示词里明确给了这个选项）。
        # 其余角色返回空目标属于无效回复 → 走兜底，绝不硬造一个"跳过"（规则层会拒）。
        if role == C.GRAVEDIGGER and not targets:
            return Decision(action="skip", analysis=analysis)
        return _fallback_night(state, pid, role, targets, rng=rng)

    chosen = target_pid(parsed.get("target"), state)
    if chosen is None or chosen not in targets:
        return _fallback_night(state, pid, role, targets, rng=rng)

    chosen, corrections = guard.guard_night_action(state, pid, role, chosen, targets, rng=rng)
    return _guard_decision("target", chosen, analysis, corrections)


def _guard_decision(
    action: str, target: str | None, analysis: str, corrections: list[guard.GuardCorrection]
) -> Decision:
    return Decision(
        action=action,
        target=target,
        analysis=analysis,
        corrections=corrections,
        source="guard" if corrections else "llm",
    )


def _fallback_night(
    state: GameStateDict,
    pid: str,
    role: str,
    targets: list[str],
    *,
    rng: random.Random,
) -> Decision:
    action = fallback.fallback_night_action(role, targets)
    if action is None:
        # 规则层本来就没有合法目标 → 直接跳过，绝不硬造动作（源项目同契约）
        return Decision(action="skip", analysis="没有合法目标", used_fallback=True, source="fallback")
    return Decision(
        action=str(action.get("action") or "target"),
        target=action.get("target"),
        potion=action.get("potion"),
        analysis="（兜底）" + (str(action.get("analysis") or "")),
        used_fallback=True,
        source="fallback",
    )


# =====================================================================
# 标记发言
# =====================================================================
async def marking(
    *,
    state: GameStateDict,
    pid: str,
    budget: float,
    log: AILog,
    rng: random.Random | None = None,
) -> dict | None:
    """AI 的标记发言。返回 ``PlayerMarksDict`` 或 None（无合法标记可提交）。"""
    player = find_player(state, pid)
    if player is None:
        return None
    persona = persona_of(state, pid)
    rand = rng or random

    evaluation_count = resolve.get_evaluation_mark_count(
        len([p for p in state["players"] if p["alive"]])
    )
    # 身份选项直接复用规则层（**已经是中文标签**，不要再套一层映射）
    identities = resolve.get_available_identities(state)
    # 理由：全部摆出来，让模型自己配身份；配错了由 `guard_marking` 第 4/5 条
    # 降级成"直觉判断"（真人界面是按所选身份过滤，两者等价）。
    reasons = [*C.COMMON_REASONS, *C.SPECIAL_REASONS]
    targets = sorted(
        (p["seat"] for p in state["players"] if p["alive"] and p["pid"] != pid)
    )

    started = time.monotonic()
    await asyncio.sleep(delay_seconds("marking", persona, rng=rand))
    prompt = prompts.marking_prompt(
        evaluation_mark_count=evaluation_count,
        available_identities=list(identities),
        targets=targets,
        available_reasons=[C.REASON_LABELS.get(r, r) for r in reasons],
        analysis_preference=persona.analysis_preference,
    )

    marks: dict | None = None
    corrections: list[guard.GuardCorrection] = []
    used_fallback = False
    raw_seen: str | None = None
    for attempt in (1, 2):
        ask_prompt = (
            prompt
            if attempt == 1
            else f"{prompt}\n\n（注意：上次回复没能通过校验，请严格按格式只返回 JSON）"
        )
        raw = await _ask(state, pid, ask_prompt, max_tokens=1000)
        if raw is not None:
            raw_seen = raw
        parsed = extract_json(raw) if raw else None
        candidate = _build_marks(state, pid, parsed)
        if candidate is None:
            continue
        corrections = guard.guard_marking(
            state, pid, candidate["identity_mark"], candidate["evaluation_marks"]
        )
        # 走**同一条**规则层校验（AI 与真人同权，绝不开后门）
        problems = resolve.validate_player_marks(state, pid, candidate)
        if not problems:
            marks = candidate
            break
        # 被规则层拒了也要留痕：排查"AI 表现怪"时，这条最能说明问题
        log.record(
            "marking_rejected",
            pid=pid,
            attempt=attempt,
            problems=problems,
            marks=candidate,
        )

    if marks is None:
        marks = fallback.fallback_marks(state, pid)
        used_fallback = True
        if marks:
            corrections = guard.guard_marking(
                state, pid, marks["identity_mark"], marks["evaluation_marks"]
            )

    log.record(
        "marking",
        pid=pid,
        persona=persona.id,
        source="fallback" if used_fallback else ("guard" if corrections else "llm"),
        marks=marks,
        corrections=[c.as_dict() for c in corrections],
        fallback=used_fallback,
        raw=(raw_seen or "")[:800],
        elapsed=round(time.monotonic() - started, 2),
    )
    return marks


def _build_marks(state: GameStateDict, pid: str, parsed: dict[str, Any] | None) -> dict | None:
    if not parsed:
        return None
    identity = syntax.normalize_identity(str(parsed.get("identity") or ""))
    if identity is None:
        return None
    reason = syntax.normalize_reason(str(parsed.get("reason") or ""))
    if reason is None:
        return None
    raw_evaluations = parsed.get("evaluations")
    if not isinstance(raw_evaluations, list):
        return None

    evaluations: list[dict] = []
    for raw in raw_evaluations:
        if not isinstance(raw, dict):
            continue
        target = target_pid(raw.get("target"), state)
        if target is None or target == pid:
            continue
        evaluation_identity = syntax.normalize_identity(str(raw.get("identity") or ""))
        evaluation_reason = syntax.normalize_reason(str(raw.get("reason") or ""))
        if evaluation_identity is None or evaluation_reason is None:
            continue
        evaluations.append(
            {
                "target": target,
                "identity": evaluation_identity,
                "reason": evaluation_reason,
            }
        )
    if not evaluations:
        return None
    return {
        "player": pid,
        "round": state["round"],
        "identity_mark": {"identity": identity, "reason": reason},
        "evaluation_marks": evaluations,
    }


# =====================================================================
# 投票
# =====================================================================
async def vote(
    *,
    state: GameStateDict,
    pid: str,
    candidates: list[str],
    budget: float,
    log: AILog,
    rng: random.Random | None = None,
) -> str | None:
    """AI 的投票。返回 pid 或 None（弃票）。"""
    player = find_player(state, pid)
    if player is None:
        return None
    persona = persona_of(state, pid)
    rand = rng or random

    started = time.monotonic()
    await asyncio.sleep(delay_seconds("voting", persona, rng=rand))
    prompt = prompts.voting_prompt(
        candidates=sorted(
            (find_player(state, c)["seat"] for c in candidates if find_player(state, c))
        ),
        self_seat=player["seat"],
        analysis_preference=persona.analysis_preference,
    )

    target: str | None = None
    corrections: list[guard.GuardCorrection] = []
    used_fallback = False
    raw_seen: str | None = None
    for _attempt in (1, 2):
        raw = await _ask(state, pid, prompt, max_tokens=500)
        if raw is not None:
            raw_seen = raw
        parsed = extract_json(raw) if raw else None
        chosen = target_pid((parsed or {}).get("target"), state)
        if chosen is None or chosen not in candidates:
            continue
        chosen, corrections = guard.guard_vote(state, pid, chosen, candidates)
        if chosen in candidates:
            target = chosen
            break

    if target is None:
        target = fallback.fallback_vote(candidates, pid)
        used_fallback = True

    log.record(
        "vote",
        pid=pid,
        persona=persona.id,
        source="fallback" if used_fallback else ("guard" if corrections else "llm"),
        target=target,
        corrections=[c.as_dict() for c in corrections],
        fallback=used_fallback,
        raw=(raw_seen or "")[:800],
        elapsed=round(time.monotonic() - started, 2),
    )
    return target


# =====================================================================
# 死亡触发（猎人开枪 / 白狼王带人 / 骑士决斗）
# =====================================================================
async def trigger(
    *,
    state: GameStateDict,
    pid: str,
    trigger_type: str,
    targets: list[str],
    can_act: bool = True,
    budget: float,
    log: AILog,
    rng: random.Random | None = None,
) -> str | None:
    """触发技能决策。返回 pid 或 None（跳过）。``can_act=False`` 直接跳过（如被毒死的猎人）。"""
    player = find_player(state, pid)
    if player is None:
        return None
    persona = persona_of(state, pid)
    rand = rng or random

    seats = sorted(
        (find_player(state, t)["seat"] for t in targets if find_player(state, t))
    )
    if trigger_type == guard.TRIGGER_WOLF_KING_DRAG:
        prompt = prompts.wolf_king_prompt(targets=seats)
    elif player["role"] == C.KNIGHT:
        prompt = prompts.knight_prompt(targets=seats)
    else:
        prompt = prompts.hunter_prompt(can_shoot=can_act, targets=seats)

    started = time.monotonic()
    await asyncio.sleep(delay_seconds("trigger", persona, rng=rand))

    target: str | None = None
    corrections: list[guard.GuardCorrection] = []
    used_fallback = False
    raw_seen: str | None = None
    for _attempt in (1, 2):
        raw = await _ask(state, pid, prompt, max_tokens=500)
        if raw is not None:
            raw_seen = raw
        parsed = extract_json(raw) if raw else None
        if not parsed:
            continue
        action = str(parsed.get("action") or "")
        if action in {"skip", "none"}:
            target = None
            break
        chosen = target_pid(parsed.get("target"), state)
        if chosen is None or chosen not in targets:
            continue
        chosen, corrections = guard.guard_trigger_action(
            state, pid, trigger_type, chosen, targets
        )
        target = chosen if chosen in targets else None
        break

    if target is None and not can_act:
        used_fallback = True  # 明确记录：不是"决定不开枪"，而是不允许开枪

    log.record(
        "trigger",
        pid=pid,
        persona=persona.id,
        trigger=trigger_type,
        source="fallback" if used_fallback else ("guard" if corrections else "llm"),
        target=target,
        corrections=[c.as_dict() for c in corrections],
        fallback=used_fallback,
        raw=(raw_seen or "")[:800],
        elapsed=round(time.monotonic() - started, 2),
    )
    return target


# =====================================================================
# 超时包装：AI 有超时、真人没有
# =====================================================================
async def with_budget(
    awaitable: Any, *, budget: float, log: AILog, kind: str, pid: str
) -> Any:
    """给一次 AI 决策套上超时。

    ⚠️ 只接 ``TimeoutError``：外部取消（`/结束`）必须继续往上冒泡，
    不能被这里当成"超时"吞掉。
    """
    try:
        return await asyncio.wait_for(awaitable, timeout=budget)
    except TimeoutError:
        log.record("timeout", phase=kind, pid=pid, budget=budget)
        logger.warning(f"[silent_mark.ai] {pid} 的 {kind} 决策超时（{budget}s），走兜底")
        return None
