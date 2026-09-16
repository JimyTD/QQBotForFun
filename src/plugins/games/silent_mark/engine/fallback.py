"""静夜标记 · 玩家未行动时的服务端兜底。

来源：源项目 ``GameManager.submitDisconnectedFallback``（真人断线/超时代打）
与 ``AIPlayerController.fallbackNightAction``（角色专属确定性兜底）。

QQ 侧的对应场景是**逐动作超时**（计划 §8.3）：某个玩家 60/120 秒内没有输入时，
游戏本体调用这里的函数拿到一个默认行动，保证对局一定能继续推进。

**契约（比源项目更严，务必遵守）**：

1. 返回值一定**能通过规则层校验**（``roles.*.perform_night_action`` 会返回 True）。
   返回 None 表示"当前状态下该角色**没有任何合法行动**"，此时调用方必须
   **直接推进阶段**（记录一条代打事件），绝不允许原地等待。
2. 一定是确定性或受控随机的（不在这里做"聪明决策"，那是 AI 的事）。
3. 可选技能一律不使用：女巫不用药；猎人 / 白狼王 / 骑士在触发阶段默认跳过
   （触发阶段的跳过由状态机直接决定，本模块不提供 `fallback_trigger_action`）。

为什么与源项目的 ``fallbackNightAction`` 不同：源项目在守卫没有合法目标时返回
``{action:'guard'}``（不带 target），而 ``Guard.performNightAction`` 要求必须有 target
→ 提交被拒 → 触发一次无谓的兜底重试；若兜底再次被拒，源项目只打日志、**阶段会永久卡住**
（该问题源项目已在 502ef26 一轮修复中处理）。本模块用「返回 None + 调用方直接推进」
从根上消除这条路径，不引入任何无效动作。

前置条件：``valid_targets`` 必须来自 ``create_role(role).get_available_targets(state, player)``。
"""

from __future__ import annotations

import random
from typing import Any

from . import constants as C  # noqa: N812
from .resolve import get_available_identities, get_evaluation_mark_count
from .types import GameStateDict, PlayerMarksDict


def _pick(valid_targets: list[str]) -> str | None:
    return random.choice(valid_targets) if valid_targets else None


def fallback_night_action(role: str, valid_targets: list[str]) -> dict[str, Any] | None:
    """夜晚行动的确定性兜底。返回 None = 无合法行动，调用方应直接推进阶段。

    - 狼人 / 预言家 / 守卫：从合法目标里随机选一个；**没有合法目标时返回 None**
      （退无可退的残局，硬造动作只会被规则层拒绝）；
    - 守墓人：有死者就随机验一个；没死者时返回不带 target 的 ``autopsy``
      （这在规则层是合法的"自动跳过"）;
    - 女巫：**永远不使用药物**（源项目明确如此，避免误用解药/毒药）；
    - 无夜晚行动的角色：返回 skip（调用方据此直接跳到下一角色）。
    """
    target = _pick(valid_targets)

    if role in C.WOLF_ROLES:
        return {"action": "attack", "target": target} if target else None
    if role == C.SEER:
        return {"action": "investigate", "target": target} if target else None
    if role == C.GUARD:
        return {"action": "guard", "target": target} if target else None
    if role == C.WITCH:
        return {"action": "usePotion", "potion": "none"}
    if role == C.GRAVEDIGGER:
        # 没有死者 → 规则层接受无 target 的验尸（自动跳过）
        return {"action": "autopsy", "target": target} if target else {"action": "autopsy"}
    return {"action": "skip"}


def fallback_marks(state: GameStateDict, pid: str) -> PlayerMarksDict | None:
    """标记阶段的兜底（源项目断线代打逻辑）。

    身份声明取「好人」（若当局选项里没有则取第一个），理由一律「直觉判断」，
    评价对象按玩家列表顺序取前 N 个存活的其他玩家（N = 当局要求的评价标记数）。

    当**存活的其他玩家为 0** 时返回 None（无合法标记可提交，源项目同样直接放弃）——
    此时调用方应跳过该玩家的标记回合并继续下一位，不能卡住。
    """
    identities = get_available_identities(state)
    identity = C.IDENTITY_GOOD if C.IDENTITY_GOOD in identities else (
        identities[0] if identities else None
    )
    count = get_evaluation_mark_count(len([p for p in state["players"] if p["alive"]]))
    targets = [
        p for p in state["players"] if p["alive"] and p["pid"] != pid
    ][:count]

    if not identity or not targets:
        return None

    return {
        "player": pid,
        "round": state["round"],
        "identity_mark": {"identity": identity, "reason": C.REASON_INTUITION},
        "evaluation_marks": [
            {
                "target": t["pid"],
                "identity": C.IDENTITY_GOOD,
                "reason": C.REASON_INTUITION,
            }
            for t in targets
        ],
    }


def fallback_vote(candidates: list[str], pid: str) -> str | None:
    """投票阶段的兜底：候选里第一个不是自己的（源项目的 ``allowedTargets.find``）。

    返回 None 表示候选里只有自己（无法投票）——调用方应记为弃票并继续推进。
    """
    for candidate in candidates:
        if candidate != pid:
            return candidate
    return None
