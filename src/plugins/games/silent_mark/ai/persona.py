"""AI 人格注册表（移植自源项目 `ai/AIPersona.ts`）。

源项目的三条设计原则原样保留，因为它们都是为了"不可预测"：

1. 人格是**纯 AI 实现细节**，与游戏规则无关 → 不写进 `PlayerDict`，
   只在 `ctx.state["ai"]` 里登记（避免污染规则层类型）。
2. 人格在**开局时分配、整局固定**。源项目早期用座位号当人格下标，导致
   "同一座位每局人格相同、相邻座位人格也相邻"，可预测性太强 → 必须洗牌。
3. 同局尽量不重复分配同一种人格，保证场上分析视角多样。

``analysisPreference`` 是**注入 prompt 的文案**，逐字照抄，一个字都没改。
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    """人格：只影响分析视角与行为节奏，**不改变任何游戏规则**。"""

    id: str
    label: str
    #: 注入 prompt 的分析偏好描述
    analysis_preference: str
    #: 决策速度倾向：模拟思考延迟的基准倍率（<1 偏快，>1 偏慢）
    pace_factor: float
    #: 直觉倾向 0~1：越高越倾向用"直觉"当理由，越低越倾向分析类理由
    intuition_bias: float


AI_PERSONAS: tuple[Persona, ...] = (
    Persona(
        id="mark_reader",
        label="标记细读型",
        analysis_preference=(
            "你更擅长从标记发言内容中找矛盾。重点关注：谁的声称前后不一致？"
            "谁的评价和事实对不上？有人声称相同的身份吗？"
        ),
        pace_factor=1.15,
        intuition_bias=0.15,
    ),
    Persona(
        id="vote_tracker",
        label="投票追踪型",
        analysis_preference=(
            "你更擅长分析投票行为模式。重点关注：谁的投票总是和结果一致（可能是跟风狼）？"
            "谁从不投某些人（可能在保队友）？有没有可疑的投票同盟？"
        ),
        pace_factor=1.2,
        intuition_bias=0.1,
    ),
    Persona(
        id="silence_watcher",
        label="关注低调型",
        analysis_preference=(
            "你倾向于关注低调的玩家。重点关注：谁说的话最少、评价最模糊？"
            "低调可能是在伪装。不要只看被多人指控的热门目标，也要考虑被忽略的玩家。"
        ),
        pace_factor=0.9,
        intuition_bias=0.35,
    ),
    Persona(
        id="death_reader",
        label="死亡线索型",
        analysis_preference=(
            "你更擅长从死亡记录和遗物中推理。重点关注：谁被狼人刀了——"
            "说明他可能对狼人有威胁，他之前指控过谁？遗物透露了什么信息？"
        ),
        pace_factor=1.05,
        intuition_bias=0.2,
    ),
    Persona(
        id="contrarian",
        label="独立思考型",
        analysis_preference=(
            "你倾向于独立思考，不轻易从众。如果很多人都指向同一个目标，你要想："
            "这是因为证据确凿，还是被带节奏了？也许真正的狼人正在利用多数人的判断来甩锅。"
        ),
        pace_factor=1.1,
        intuition_bias=0.25,
    ),
    Persona(
        id="gut_player",
        label="直觉流",
        analysis_preference=(
            "你不喜欢复杂推理，更相信第一感觉。你会快速给出判断，不会反复权衡。"
            "如果没有明确证据，你就凭感觉选一个，不强求理由充分。"
        ),
        pace_factor=0.7,
        intuition_bias=0.6,
    ),
)

_BY_ID: dict[str, Persona] = {p.id: p for p in AI_PERSONAS}


def stable_hash(text: str) -> int:
    """源项目那套 31 进制哈希。

    ⚠️ 不能用 Python 内置 `hash()`：它按进程随机加盐，同一局里跨进程/重启后
    同一个人会拿到不同人格（源项目注释强调"这轮急性子下轮慢性子"是要避免的）。
    """
    value = 0
    for char in text:
        value = (value * 31 + ord(char)) % 100000
    return value


def assign_personas(
    ai_pids: Iterable[str], rng: random.Random
) -> dict[str, Persona]:
    """给一局的所有 AI 座位分人格（整局固定）。

    ``rng`` 由调用方给：用对局 seed 建出来的话，整局可复现（测试要用）。
    """
    pool = list(AI_PERSONAS)
    rng.shuffle(pool)
    # 按 pid 排序后再依次发，保证"分配结果只取决于 rng 与座位集合"，与报名顺序无关
    return {
        pid: pool[index % len(pool)]
        for index, pid in enumerate(sorted(ai_pids))
    }


def persona_of(state: dict, pid: str) -> Persona:
    """取某座位本局人格。

    没登记（例如中途加入、或老状态没带 ``persona``）时按 pid 稳定哈希兜底——
    兜底的**唯一要求是稳定**，绝不能随机抽。
    """
    entry = (state.get("ai") or {}).get(pid) or {}
    persona = _BY_ID.get(str(entry.get("persona") or ""))
    if persona is not None:
        return persona
    return AI_PERSONAS[stable_hash(pid) % len(AI_PERSONAS)]


def persona_id_of(state: dict, pid: str) -> str:
    return persona_of(state, pid).id
