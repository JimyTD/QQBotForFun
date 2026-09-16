"""AI 决策语义校验层（移植自源项目 `ai/AIDecisionGuard.ts`）。

三条设计原则（照抄，原文见源文件注释）：

1. prompt 里的文字约束是**软约束**，模型可能忽略；本模块是**硬约束**，
   代码层面保证不出现违背"AI 自己已知信息"的决策。
2. **只在决策明确违背 AI 自己的私有信息时才纠正**，不干预正常的策略选择空间
   （例如"该不该投这个人"属于策略，不纠正）。
3. 每次纠正都**带原因**返回，便于日志追踪与调试 —— **不要静默改写**。

⚠️ 触发校验里**只保留白狼王"不带走队友"**这一条。猎人与骑士在本规则里没有任何
查验能力（查验结果只属于预言家/守墓人自己），"不应选择已确认好人"这种私有信息
在他们身上根本不存在 —— 源项目 502ef26 已核实过并改成注释说明。
本移植**不写永不触发的死代码**。

动作名与源项目的对应关系（本侧重用角色 key，少一层映射）：

| 源项目 | 本侧 |
|---|---|
| `'attack'` | `C.WEREWOLF` / `C.WOLF_KING`（狼人合议） |
| `'investigate'` | `C.SEER` |
| `'autopsy'` | `C.GRAVEDIGGER` |
| `'wolf_king_drag'` | `'wolf_king_drag'`（与 `PendingTriggerDict.type` 同字面量） |
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..engine import constants as C  # noqa: N812
from ..engine.types import GameStateDict, find_player

#: 白狼王带人（与 `engine.types.PendingTriggerDict.type` 同一字面量）
TRIGGER_WOLF_KING_DRAG = "wolf_king_drag"


@dataclass(frozen=True)
class GuardCorrection:
    """一次纠正。``before`` / ``after`` 用座位标签（``3号``），日志里一眼能看懂。"""

    field: str
    before: str
    after: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        """给日志用的形状（沿用源项目的键名 ``from`` / ``to``）。"""
        return {
            "field": self.field,
            "from": self.before,
            "to": self.after,
            "reason": self.reason,
        }


def _seat_label(state: GameStateDict, pid: str) -> str:
    player = find_player(state, pid)
    return f"{player['seat']}号" if player else pid[:6]


# =====================================================================
# 私有信息收集（只收"本人自己"的信息，绝不共享）
# =====================================================================
def collect_seer_results(state: GameStateDict, pid: str) -> dict[str, str]:
    """某预言家自己的查验结果：``pid → good/evil``。非预言家恒为空。"""
    player = find_player(state, pid)
    if player is None or player["role"] != C.SEER:
        return {}
    results: dict[str, str] = {}
    for night in state["history"]["rounds"]:
        action = night.get("seer") or {}
        target = action.get("target")
        if not target:
            continue
        seen = find_player(state, target)
        if seen is not None:
            results[target] = "good" if seen["faction"] == C.GOOD else "evil"
    return results


def collect_gravedigger_results(state: GameStateDict, pid: str) -> dict[str, str]:
    """某守墓人自己的验尸结果。非守墓人恒为空。"""
    player = find_player(state, pid)
    if player is None or player["role"] != C.GRAVEDIGGER:
        return {}
    results: dict[str, str] = {}
    for night in state["history"]["rounds"]:
        action = night.get("gravedigger") or {}
        target = action.get("target")
        if not target:
            continue
        seen = find_player(state, target)
        if seen is not None:
            results[target] = "good" if seen["faction"] == C.GOOD else "evil"
    return results


def _all_verified(state: GameStateDict, pid: str) -> dict[str, str]:
    return {**collect_seer_results(state, pid), **collect_gravedigger_results(state, pid)}


def teammate_ids(state: GameStateDict, pid: str) -> set[str]:
    """狼人队友的 pid 集合（非狼阵营恒为空）。"""
    player = find_player(state, pid)
    if player is None or player["faction"] != C.EVIL:
        return set()
    return {
        other["pid"]
        for other in state["players"]
        if other["faction"] == C.EVIL and other["pid"] != pid
    }


def count_wolf_marks(state: GameStateDict, candidates: list[str]) -> dict[str, int]:
    """候选者被标记为"狼人"的次数（用于"顺势推锅"时挑最像的目标）。"""
    counts = {pid: 0 for pid in candidates}
    for marks in state["history"]["marks"]:
        for evaluation in marks["evaluation_marks"]:
            target = evaluation["target"]
            if evaluation["identity"] == C.IDENTITY_WOLF and target in counts:
                counts[target] += 1
    return counts


# =====================================================================
# 投票
# =====================================================================
def guard_vote(
    state: GameStateDict,
    pid: str,
    chosen: str,
    valid_candidates: list[str],
) -> tuple[str, list[GuardCorrection]]:
    """投票校验。返回 ``(最终目标, 纠正记录)``。

    **硬约束**（违背已知信息，必须纠正）：
    - 预言家/守墓人：不得投给自己查验为"好人"的人
    - 狼阵营：不得投队友（除非候选里全是队友）

    **软倾向**（有更优选择时改投）：
    - 预言家/守墓人：手上有确认的狼人且在候选中，应优先投他
    """
    corrections: list[GuardCorrection] = []
    target = chosen
    player = find_player(state, pid)
    if player is None:
        return target, corrections

    # === 1. 查验类角色：绝不投已确认的好人 ===
    verified = _all_verified(state, pid)
    if verified:
        known_wolves = [c for c in valid_candidates if verified.get(c) == "evil"]

        if verified.get(target) == "good":
            replacement = known_wolves[0] if known_wolves else next(
                (c for c in valid_candidates if verified.get(c) != "good"), None
            )
            if replacement:
                corrections.append(
                    GuardCorrection(
                        field="vote",
                        before=_seat_label(state, target),
                        after=_seat_label(state, replacement),
                        reason="原目标是本人查验确认的好人，违背私有信息",
                    )
                )
                target = replacement
        elif known_wolves and target not in known_wolves:
            corrections.append(
                GuardCorrection(
                    field="vote",
                    before=_seat_label(state, target),
                    after=_seat_label(state, known_wolves[0]),
                    reason="本人已查验出狼人且在候选中，应优先投出",
                )
            )
            target = known_wolves[0]

    # === 2. 狼阵营：不投队友 ===
    teammates = teammate_ids(state, pid)
    if teammates and target in teammates:
        outsiders = [c for c in valid_candidates if c not in teammates]
        if outsiders:
            # 优先投被标记为"狼人"次数最多的非队友（顺势推锅）
            wolf_marks = count_wolf_marks(state, outsiders)
            outsiders.sort(key=lambda c: wolf_marks.get(c, 0), reverse=True)
            corrections.append(
                GuardCorrection(
                    field="vote",
                    before=_seat_label(state, target),
                    after=_seat_label(state, outsiders[0]),
                    reason="原目标是狼人队友，违背阵营利益",
                )
            )
            target = outsiders[0]
        # 候选里全是队友时保留原选择（规则允许，属于必然情形）

    return target, corrections


# =====================================================================
# 夜间行动
# =====================================================================
def guard_night_action(
    state: GameStateDict,
    pid: str,
    action: str,
    target: str | None,
    valid_targets: list[str],
    *,
    rng: random.Random | None = None,
) -> tuple[str | None, list[GuardCorrection]]:
    """夜间行动校验（硬约束）：

    - 狼人不得袭击队友
    - 预言家不得重复查验同一目标（浪费回合）
    - 守墓人不得重复验尸同一目标

    ``action`` 用**角色 key**（``C.WEREWOLF`` / ``C.SEER`` / ``C.GRAVEDIGGER``）。
    """
    corrections: list[GuardCorrection] = []
    if not target:
        return target, corrections

    rand = rng or random
    result = target

    # === 狼人不刀队友 ===
    if action in C.WOLF_ROLES:
        teammates = teammate_ids(state, pid)
        if result in teammates:
            outsiders = [t for t in valid_targets if t not in teammates]
            if outsiders:
                replacement = rand.choice(outsiders)
                corrections.append(
                    GuardCorrection(
                        field="night_attack",
                        before=_seat_label(state, result),
                        after=_seat_label(state, replacement),
                        reason="袭击目标是狼人队友",
                    )
                )
                result = replacement

    # === 预言家不重复查验 ===
    if action == C.SEER:
        checked = collect_seer_results(state, pid)
        if result in checked:
            unchecked = [t for t in valid_targets if t not in checked]
            if unchecked:
                replacement = rand.choice(unchecked)
                corrections.append(
                    GuardCorrection(
                        field="night_investigate",
                        before=_seat_label(state, result),
                        after=_seat_label(state, replacement),
                        reason="该目标已在此前查验过，重复查验浪费回合",
                    )
                )
                result = replacement

    # === 守墓人不重复验尸 ===
    if action == C.GRAVEDIGGER:
        checked = collect_gravedigger_results(state, pid)
        if result in checked:
            unchecked = [t for t in valid_targets if t not in checked]
            if unchecked:
                corrections.append(
                    GuardCorrection(
                        field="night_autopsy",
                        before=_seat_label(state, result),
                        after=_seat_label(state, unchecked[0]),
                        reason="该死者已验尸过，重复验尸浪费回合",
                    )
                )
                result = unchecked[0]

    return result, corrections


# =====================================================================
# 死亡触发（猎人开枪 / 骑士决斗 / 白狼王带人）
# =====================================================================
def guard_trigger_action(
    state: GameStateDict,
    pid: str,
    trigger_type: str,
    target: str | None,
    valid_targets: list[str],
) -> tuple[str | None, list[GuardCorrection]]:
    """触发技能校验：**只实现白狼王"不带走队友"**。

    猎人、骑士在本规则里没有任何查验能力（查验结果只有预言家/守墓人自己知道），
    因此不存在"已被自己确认的好人"可用于校验 —— 源项目 502ef26 核实后删掉了那段
    永不触发的校验。这里同样不写，避免后人误以为"少移植了一条"。
    """
    corrections: list[GuardCorrection] = []
    if not target or trigger_type != TRIGGER_WOLF_KING_DRAG:
        return target, corrections

    teammates = teammate_ids(state, pid)
    if target in teammates:
        outsiders = [t for t in valid_targets if t not in teammates]
        if outsiders:
            corrections.append(
                GuardCorrection(
                    field="wolf_king_drag",
                    before=_seat_label(state, target),
                    after=_seat_label(state, outsiders[0]),
                    reason="带走目标是狼人队友",
                )
            )
            return outsiders[0], corrections
    return target, corrections


# =====================================================================
# 标记
# =====================================================================
def guard_marking(
    state: GameStateDict,
    pid: str,
    identity_mark: dict,
    evaluation_marks: list[dict],
) -> list[GuardCorrection]:
    """标记校验。**就地修改** ``identity_mark`` / ``evaluation_marks`` 并返回纠正记录。

    硬约束：
    1. 查验类角色的评价必须与自己的查验结论一致
    2. 狼阵营不得把队友标记为"狼人"
    3. 狼阵营的身份声称不得为"狼人"
    4. 特殊理由（查验结论 / 用药结果）必须匹配**公开声明的身份** ——
       允许狼人或平民诈称预言家/女巫，所以**不能按真实角色拦截**（源项目原注释）
    """
    corrections: list[GuardCorrection] = []
    player = find_player(state, pid)
    if player is None:
        return corrections

    # === 1. 狼人不得自曝身份 ===
    if player["faction"] == C.EVIL and identity_mark["identity"] == C.IDENTITY_WOLF:
        corrections.append(
            GuardCorrection(
                field="identity",
                before=C.IDENTITY_WOLF,
                after=C.IDENTITY_GOOD,
                reason="狼人阵营自曝身份，立刻暴露",
            )
        )
        identity_mark["identity"] = C.IDENTITY_GOOD

    # === 2. 查验结论一致性 ===
    verified = _all_verified(state, pid)
    for evaluation in evaluation_marks:
        result = verified.get(evaluation["target"])
        if not result:
            continue
        expected = C.IDENTITY_GOOD if result == "good" else C.IDENTITY_WOLF
        if evaluation["identity"] != expected:
            corrections.append(
                GuardCorrection(
                    field=f"eval:{_seat_label(state, evaluation['target'])}",
                    before=evaluation["identity"],
                    after=expected,
                    reason="与本人查验结论矛盾",
                )
            )
            evaluation["identity"] = expected
            evaluation["reason"] = C.REASON_INVESTIGATION
        elif evaluation["reason"] != C.REASON_INVESTIGATION:
            # 结论对了但理由没用查验，属于信息浪费，一并修正（源项目同处理）
            evaluation["reason"] = C.REASON_INVESTIGATION

    # === 3. 狼人不得指控队友为狼人 ===
    teammates = teammate_ids(state, pid)
    if teammates:
        for evaluation in evaluation_marks:
            if (
                evaluation["target"] in teammates
                and evaluation["identity"] == C.IDENTITY_WOLF
            ):
                corrections.append(
                    GuardCorrection(
                        field=f"eval:{_seat_label(state, evaluation['target'])}",
                        before=C.IDENTITY_WOLF,
                        after=C.IDENTITY_GOOD,
                        reason="指控自己的狼人队友，等于自曝关系",
                    )
                )
                evaluation["identity"] = C.IDENTITY_GOOD
                if evaluation["reason"] == C.REASON_INVESTIGATION:
                    evaluation["reason"] = C.REASON_INTUITION

    # === 4. 特殊理由必须匹配玩家公开声明的身份 ===
    claimed = identity_mark["identity"]
    if claimed not in C.INVESTIGATION_IDENTITIES:
        if identity_mark["reason"] == C.REASON_INVESTIGATION:
            corrections.append(
                GuardCorrection(
                    field="identity_reason",
                    before=C.REASON_INVESTIGATION,
                    after=C.REASON_INTUITION,
                    reason="公开声明的身份不是预言家或守墓人，不能使用查验结论理由",
                )
            )
            identity_mark["reason"] = C.REASON_INTUITION
        for evaluation in evaluation_marks:
            if evaluation["reason"] == C.REASON_INVESTIGATION:
                corrections.append(
                    GuardCorrection(
                        field=f"eval_reason:{_seat_label(state, evaluation['target'])}",
                        before=C.REASON_INVESTIGATION,
                        after=C.REASON_INTUITION,
                        reason="公开声明的身份不是预言家或守墓人，不能使用查验结论理由",
                    )
                )
                evaluation["reason"] = C.REASON_INTUITION

    # === 5. 用药结果必须匹配公开声明的女巫身份 ===
    if identity_mark["identity"] not in C.POTION_IDENTITIES:
        if identity_mark["reason"] == C.REASON_POTION_RESULT:
            identity_mark["reason"] = C.REASON_INTUITION
            corrections.append(
                GuardCorrection(
                    field="identity_reason",
                    before=C.REASON_POTION_RESULT,
                    after=C.REASON_INTUITION,
                    reason="公开声明的身份不是女巫，不能使用用药结果理由",
                )
            )
        for evaluation in evaluation_marks:
            if evaluation["reason"] == C.REASON_POTION_RESULT:
                evaluation["reason"] = C.REASON_INTUITION
                corrections.append(
                    GuardCorrection(
                        field=f"eval_reason:{_seat_label(state, evaluation['target'])}",
                        before=C.REASON_POTION_RESULT,
                        after=C.REASON_INTUITION,
                        reason="公开声明的身份不是女巫，不能使用用药结果理由",
                    )
                )

    return corrections
