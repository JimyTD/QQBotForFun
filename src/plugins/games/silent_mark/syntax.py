"""静夜标记 · 玩家输入语法（解析 ↔ 渲染）。

这是 CLI 与 QQ Bot **唯一共用**的输入层（`docs/13-cli-bot-parity.md` 铁律）：
两边必须用同一份解析 + 同一份提示文案，否则"CLI 跑通 ≠ 群里跑通"。

分层（不要越界）：

- **语法层**（本模块）：分词、别名归一、座位号 → pid、把玩家文本变成结构化动作，
  以及生成与语法**配对**的提示文案。纯函数，不 import `core` / `nonebot`。
- **语义层**（`engine.resolve.validate_player_marks`）：身份是否可选、理由是否匹配
  申报身份、评价数量上限。本模块**不重复**做这些判断，避免两套真相。
- **IO 层**（`game.py`）：谁该发言、超时、广播、撤回消息。

刻意的严格化差异（已记入计划 §0.4）：本模块要求人类输入**至少给 1 个评价标记**
（产品要求"必须使用"），而 `validate_player_marks` 保持源项目口径（允许更少，
因为 AI 与超时兜底路径可能产生更少的评价）。层不同，口径可以不同，但不能互相覆盖。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .engine import constants as C  # noqa: N812
from .engine.resolve import (
    get_available_eval_identities,
    get_available_identities,
)
from .engine.types import GameStateDict, PlayerDict, PlayerMarksDict

# =====================================================================
# 词表
# =====================================================================
#: 身份别名 → 标准中文标签（标准标签即 `constants.IDENTITY_TO_ROLE` 的键）
IDENTITY_ALIASES: dict[str, str] = {
    **{label: label for label in C.IDENTITY_TO_ROLE},
    C.IDENTITY_ROLE_FIRST: C.IDENTITY_ROLE_FIRST,
    "神": C.IDENTITY_ROLE_FIRST,
    C.IDENTITY_GOOD: C.IDENTITY_GOOD,
    C.IDENTITY_WOLF: C.IDENTITY_WOLF,
    "狼": C.IDENTITY_WOLF,
    "民": "平民",
}

#: 理由别名（中文名 / 英文 key / 常用简写）→ 理由 key
REASON_ALIASES: dict[str, str] = {
    **{key: key for key in (*C.COMMON_REASONS, *C.SPECIAL_REASONS)},
    **{label: key for key, label in C.REASON_LABELS.items()},
    "直觉": C.REASON_INTUITION,
    "投票": C.REASON_VOTE_ANALYSIS,
    "日志": C.REASON_LOG_REASONING,
    "查验": C.REASON_INVESTIGATION,
    "用药": C.REASON_POTION_RESULT,
}

#: 表示"本回合跳过/不使用"
PASS_TOKENS: frozenset[str] = frozenset(
    {"跳过", "过", "pass", "skip", "不用", "否", "no", "n"}
)

#: 允许出现在目标前面的动词（`刀 3` / `守 3号` / `投 3` 都能吃）
VERB_PREFIXES: frozenset[str] = frozenset(
    {
        "刀",
        "袭击",
        "杀",
        "守",
        "守护",
        "查",
        "查验",
        "验",
        "验尸",
        "投",
        "投票",
        "票",
        "带",
        "带走",
        "开枪",
        "打",
        "救",
        "毒",
    }
)

#: 只发这些内容 → 走引导式（逐个 choose），而不是报错
GUIDE_TRIGGERS: frozenset[str] = frozenset({"", "标记", "发言", "帮助", "help", "?", "？"})

_SEGMENT_SPLIT = re.compile(r"[|｜]")
_TOKEN_SPLIT = re.compile(r"[\s,，、]+")
_GLUED_SPLIT = re.compile(r"^([^\d\s]+)(\d.*)$")
_SEAT_HEAD = "@＠#pP"
_SEAT_TAIL = ("号玩家", "玩家", "号", "位")

REASON_LABEL_LIST = "、".join(C.REASON_LABELS.values())


# =====================================================================
# 归一化
# =====================================================================
def normalize_identity(token: str) -> str | None:
    """把玩家写的身份归一成标准中文标签。无法识别返回 None。"""
    return IDENTITY_ALIASES.get(token.strip())


def normalize_reason(token: str) -> str | None:
    """把玩家写的理由归一成理由 key（中文名/英文 key 都吃）。无法识别返回 None。"""
    text = token.strip()
    return REASON_ALIASES.get(text) or REASON_ALIASES.get(text.lower())


def parse_seat(token: str) -> int | None:
    """解析座位号：``3`` / ``3号`` / ``@3`` / ``P3`` 均可。无法识别返回 None。"""
    text = token.strip()
    while text and text[0] in _SEAT_HEAD:
        text = text[1:]
    for tail in _SEAT_TAIL:
        if text.endswith(tail):
            text = text[: -len(tail)]
            break
    return int(text) if text.isdigit() else None


def tokenize(text: str) -> list[str]:
    """把一段文本切成 token。

    额外处理"粘在一起"的写法：``毒3`` → ``['毒', '3']``（玩家很自然会这么打）。
    """
    tokens = [t for t in _TOKEN_SPLIT.split(text.strip()) if t]
    if len(tokens) == 1:
        glued = _GLUED_SPLIT.match(tokens[0])
        # 前缀是座位号标记（@ / ＠ / # / p / P）时不能拆，否则 "@2" 会被拆成 ["@", "2"]
        if glued and glued.group(1)[0] not in _SEAT_HEAD:
            return [glued.group(1), glued.group(2)]
    return tokens


def seat_to_player(state: GameStateDict) -> dict[int, PlayerDict]:
    return {p["seat"]: p for p in state["players"]}


def player_label(state: GameStateDict, pid: str) -> str:
    """``3号 小明`` 形式的展示名。"""
    for player in state["players"]:
        if player["pid"] == pid:
            return f"{player['seat']}号 {player['nickname']}"
    return pid


def _alive_others(state: GameStateDict, pid: str) -> list[PlayerDict]:
    """存活的其他玩家，**按座位顺序**——提示里的名单要照着座位表读。"""
    return sorted(
        (p for p in state["players"] if p["alive"] and p["pid"] != pid),
        key=lambda p: p["seat"],
    )


# =====================================================================
# 解析结果类型
# =====================================================================
@dataclass(frozen=True)
class TargetResult:
    """单目标输入（夜间行动 / 投票）。"""

    pid: str | None = None
    skipped: bool = False
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class WitchResult:
    """女巫用药输入。``potion`` 取 ``antidote`` / ``poison`` / ``none``。"""

    potion: str | None = None
    target: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class MarkResult:
    """标记输入结果。

    - ``marks`` 非空 → 语法解析成功，可交给 `validate_player_marks` 做语义校验；
    - ``needs_guide`` → 玩家只发了「标记」，应走引导式选择；
    - ``problems`` 非空 → 语法错误，应把问题回给玩家并重问。
    """

    marks: PlayerMarksDict | None = None
    problems: list[str] = field(default_factory=list)
    needs_guide: bool = False

    @property
    def ok(self) -> bool:
        return self.marks is not None and not self.problems


# =====================================================================
# 解析
# =====================================================================
def parse_target(
    text: str,
    state: GameStateDict,
    *,
    allowed_pids: list[str] | None = None,
) -> TargetResult:
    """解析一个目标（座位号）。``allowed_pids`` 给定时还会校验目标是否在可选范围内。"""
    tokens = tokenize(text)
    if not tokens:
        return TargetResult(problems=["没有识别到内容，请回复座位号（如 3）"])

    if len(tokens) == 1 and tokens[0].lower() in PASS_TOKENS:
        return TargetResult(skipped=True)

    if len(tokens) >= 2 and tokens[0] in VERB_PREFIXES:
        tokens = tokens[1:]

    if len(tokens) != 1:
        return TargetResult(
            problems=[f"只能指定一个目标，收到 {len(tokens)} 个：{' '.join(tokens)}"]
        )

    seat = parse_seat(tokens[0])
    if seat is None:
        return TargetResult(
            problems=[f"看不懂目标「{tokens[0]}」，请回复座位号（如 3）或「跳过」"]
        )

    player = seat_to_player(state).get(seat)
    if player is None:
        return TargetResult(problems=[f"没有 {seat} 号座位"])

    if allowed_pids is not None and player["pid"] not in allowed_pids:
        return TargetResult(problems=[f"{seat} 号不在本次可选范围内"])

    return TargetResult(pid=player["pid"])


def parse_witch_action(
    text: str,
    state: GameStateDict,
    *,
    poison_targets: list[str] | None = None,
) -> WitchResult:
    """解析女巫用药：``救`` / ``解药`` / ``毒 3`` / ``不用``。"""
    tokens = tokenize(text)
    if not tokens:
        return WitchResult(problems=["没有识别到内容，请回复「救」「毒 3」或「不用」"])

    head = tokens[0].lower()
    rest = tokens[1:]

    if head in {"救", "解药", "救药", "antidote"}:
        return WitchResult(potion="antidote")
    if head in {"不救", "不救药"}:
        return WitchResult(potion="none")
    if head in PASS_TOKENS or head in {"不用药", "不使用", "none"}:
        return WitchResult(potion="none")

    if head in {"毒", "毒药", "poison"}:
        if not rest:
            return WitchResult(problems=["毒谁？请回复座位号，如「毒 3」"])
        target = parse_target(" ".join(rest), state, allowed_pids=poison_targets)
        if not target.ok:
            return WitchResult(problems=target.problems)
        if target.pid is None:
            return WitchResult(problems=["毒药必须指定一个目标，如「毒 3」"])
        return WitchResult(potion="poison", target=target.pid)

    return WitchResult(
        problems=[f"看不懂「{tokens[0]}」，请回复「救」「毒 3」或「不用」"]
    )


def parse_marks(text: str, state: GameStateDict, pid: str) -> MarkResult:
    """解析标记发言。

    格式：``<身份> <理由> | <座位> <评价身份> <理由> | ...``
    （命令词「标记」由调用方剥掉；这里也容忍它还在文本里。）
    """
    raw = text.strip()
    if raw in GUIDE_TRIGGERS:
        return MarkResult(needs_guide=True)

    segments = [s.strip() for s in _SEGMENT_SPLIT.split(raw) if s.strip()]
    if not segments:
        return MarkResult(needs_guide=True)

    problems: list[str] = []

    # ---- 第 1 段：身份声明 ----
    head = tokenize(segments[0])
    # 容忍命令词还在文本里（CLI 传原始行、群里传参数时都可能出现）
    if head and head[0] in {"标记", "发言"}:
        head = head[1:]
    identity_token = head[0] if head else ""
    identity = normalize_identity(identity_token)
    if identity is None:
        return MarkResult(
            problems=[
                f"看不懂身份「{identity_token}」。可选身份："
                f"{'、'.join(get_available_identities(state))}"
            ]
        )

    reason = C.REASON_INTUITION
    if len(head) >= 2:
        normalized = normalize_reason(head[1])
        if normalized is None:
            return MarkResult(
                problems=[f"看不懂理由「{head[1]}」。可选理由：{REASON_LABEL_LIST}"]
            )
        reason = normalized
    if len(head) > 2:
        problems.append(
            "身份声明段多了内容：「"
            + " ".join(head[2:])
            + "」。评价标记要用「|」分隔，例如："
            + f"标记 {identity} {C.REASON_LABELS[reason]} | 3号 狼人 标记分析"
        )

    # ---- 第 2 段起：评价标记 ----
    others = _alive_others(state, pid)
    min_evals = 1 if others else 0
    if len(segments) - 1 < min_evals:
        problems.append(
            f"至少要评价 {min_evals} 名其他玩家，用「|」分隔，例如："
            f"标记 {identity} {C.REASON_LABELS[reason]} | 3号 狼人 标记分析"
        )

    seats = seat_to_player(state)
    evaluations: list[dict[str, str]] = []
    seen: set[int] = set()

    for segment in segments[1:]:
        parts = tokenize(segment)
        seat = parse_seat(parts[0]) if parts else None
        if seat is None:
            problems.append(
                f"看不懂评价目标「{parts[0] if parts else ''}」，"
                "请用座位号开头，如「3号 狼人」"
            )
            continue
        if seat in seen:
            problems.append(f"{seat} 号被评价了两次")
            continue

        target = seats.get(seat)
        if target is None:
            problems.append(f"没有 {seat} 号座位")
            continue
        if not target["alive"]:
            problems.append(f"{seat} 号已出局，不能评价")
            continue
        if target["pid"] == pid:
            problems.append("不能评价自己")
            continue
        seen.add(seat)

        eval_identity = C.IDENTITY_GOOD
        if len(parts) >= 2:
            normalized = normalize_identity(parts[1])
            if normalized is None:
                problems.append(f"看不懂 {seat} 号的评价身份「{parts[1]}」")
                continue
            eval_identity = normalized

        eval_reason = C.REASON_INTUITION
        if len(parts) >= 3:
            normalized = normalize_reason(parts[2])
            if normalized is None:
                problems.append(f"看不懂 {seat} 号的评价理由「{parts[2]}」")
                continue
            eval_reason = normalized
        if len(parts) > 3:
            problems.append(f"{seat} 号那段多了内容：「{' '.join(parts[3:])}」")
            continue

        evaluations.append(
            {"target": target["pid"], "identity": eval_identity, "reason": eval_reason}
        )

    if problems:
        return MarkResult(problems=problems)

    marks: PlayerMarksDict = {
        "player": pid,
        "round": state["round"],
        "identity_mark": {"identity": identity, "reason": reason},
        "evaluation_marks": evaluations,
    }
    return MarkResult(marks=marks)


# =====================================================================
# 渲染（与上面的解析配对；CLI 与群内使用同一份文案）
# =====================================================================
def render_mark_prompt(
    state: GameStateDict, pid: str, *, at_prefix: bool = False, first_time: bool = False
) -> str:
    """标记发言阶段、轮到某玩家时的提示。

    **刻意保持短**：这条提示每轮都要发一遍，而群里同时只留一条
    （下一个玩家开始时旧提示会被撤回）。太长就变成刷屏。

    ``at_prefix``：群聊里只有 @机器人 的消息才会被路由到游戏（`docs/13` 列为
    允许的机制差异——CLI 不需要 @）。开启后示例会带上 `@我`。
    ``first_time``：本局第一次标记，额外教一句"不会写就让我带你"。
    """
    others = _alive_others(state, pid)
    identities = get_available_identities(state)
    eval_identities = get_available_eval_identities(state)
    labels = [player_label(state, p["pid"]) for p in others]
    prefix = "@我 " if at_prefix else ""
    sample = " | ".join(f"{p['seat']}号 好人 直觉判断" for p in others[:2]) or "3号 狼人 标记分析"

    lines = [
        f"📝 轮到 {player_label(state, pid)} 标记发言",
        f"　存活：{'、'.join(labels) if labels else '（无）'}",
        f"　身份：{'/'.join(identities)}　评价：{'/'.join(eval_identities)}",
        f"　理由：{REASON_LABEL_LIST}（可省略，默认「直觉判断」）",
        f"　格式：{prefix}标记 <身份> <理由> | <座位> <评价身份> <理由> | …",
        f"　例：{prefix}标记 好人 直觉判断 | {sample}",
    ]
    if first_time:
        lines.append(f"　不会写？只发「{prefix}标记」，我在私聊里带你一步步来")
    return "\n".join(lines)


#: 各夜间/白天动作的提示标题
TARGET_PROMPT_TITLES: dict[str, str] = {
    "guard": "🛡 请选择今晚的守护目标（不可与上一晚相同）",
    "wolves": "🐺 请选择今晚的袭击目标（可以自刀）",
    "seer": "🔮 请选择今晚要查验的玩家",
    "gravedigger": "⚰️ 请选择要验尸的已出局玩家",
    "vote": "🗳 请选择要放逐的玩家",
    "hunter_shoot": "🔫 请选择开枪带走的目标",
    "wolf_king_drag": "👑 请选择带走的目标",
    "knight_duel": "⚔️ 请选择决斗目标",
}


def render_target_prompt(
    state: GameStateDict,
    pid: str,
    kind: str,
    *,
    allowed_pids: list[str],
    extra_lines: list[str] | None = None,
    allow_skip: bool = False,
) -> str:
    """单目标动作的提示（夜间技能 / 投票 / 触发）。"""
    title = TARGET_PROMPT_TITLES.get(kind, "请选择目标")
    seat_of = {p["pid"]: p["seat"] for p in state["players"]}
    # 可选目标一律按**座位顺序**列出（源项目的 UI 就是座位环，玩家按座位找人）
    options = [
        player_label(state, other)
        for other in sorted(
            (pid_ for pid_ in allowed_pids if pid_ in seat_of),
            key=lambda pid_: seat_of[pid_],
        )
    ]

    lines = [title, f"（{player_label(state, pid)}）"]
    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)
    lines.append("")
    lines.append(f"可选：{'、'.join(options) if options else '（无可选目标）'}")
    lines.append("回复座位号（如 3）" + ("，或回复「跳过」" if allow_skip else ""))
    return "\n".join(lines)


def render_witch_prompt(
    state: GameStateDict, pid: str, *, victim_pid: str | None
) -> str:
    """女巫用药提示：明确告知"今夜被刀的是谁"这一私有信息。"""
    role_state = next(p["role_state"] for p in state["players"] if p["pid"] == pid)
    antidote_used = bool(role_state.get("antidote_used"))
    poison_used = bool(role_state.get("poison_used"))

    victim_line = (
        f"🩸 今晚被袭击的是：{player_label(state, victim_pid)}"
        if victim_pid
        else "🩸 今晚无人被袭击"
    )
    lines = [
        "🧪 女巫用药",
        f"（{player_label(state, pid)}）",
        "",
        victim_line,
        f"解药：{'已用完' if antidote_used else '未使用'}"
        f"　毒药：{'已用完' if poison_used else '未使用'}",
        "",
        "回复：",
        "  救　　　　使用解药救被袭击者",
        "  毒 3　　　 使用毒药毒 3 号",
        "  不用　　　 今晚不使用药物",
    ]
    if antidote_used and poison_used:
        lines.append("")
        lines.append("（两瓶药都已用完，请回复「不用」）")
    return "\n".join(lines)


def render_marks_line(state: GameStateDict, marks: PlayerMarksDict) -> str:
    """把一份标记渲染成公开播报（群内广播 / CLI 打印共用）。"""
    reason = C.REASON_LABELS.get(marks["identity_mark"]["reason"], marks["identity_mark"]["reason"])
    lines = [
        f"📌 {player_label(state, marks['player'])} 声明身份："
        f"{marks['identity_mark']['identity']}（{reason}）"
    ]
    for mark in marks["evaluation_marks"]:
        mark_reason = C.REASON_LABELS.get(mark["reason"], mark["reason"])
        lines.append(
            f"　 → 认为 {player_label(state, mark['target'])} 是 "
            f"{mark['identity']}（{mark_reason}）"
        )
    return "\n".join(lines)
