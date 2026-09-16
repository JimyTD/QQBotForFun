"""静夜标记 · 常量层。

逐条转写自源项目 ``shared/constants.ts``。所有中文标签用于玩家可见输出，
与源项目**逐字一致**（改文案等于改产品行为，不要顺手润色）。
"""

from __future__ import annotations

from dataclasses import dataclass

# =====================================================================
# 角色
# =====================================================================
WEREWOLF = "werewolf"
WOLF_KING = "wolfKing"
SEER = "seer"
WITCH = "witch"
HUNTER = "hunter"
GUARD = "guard"
GRAVEDIGGER = "gravedigger"
FOOL = "fool"
KNIGHT = "knight"
VILLAGER = "villager"

ROLE_LABELS: dict[str, str] = {
    WEREWOLF: "狼人",
    SEER: "预言家",
    WITCH: "女巫",
    HUNTER: "猎人",
    GUARD: "守卫",
    GRAVEDIGGER: "守墓人",
    FOOL: "白痴",
    KNIGHT: "骑士",
    WOLF_KING: "白狼王",
    VILLAGER: "平民",
}

# 创造房间时可供房主自定义的角色（源项目 AVAILABLE_ROLES_FOR_CUSTOM，顺序即 UI 顺序）
AVAILABLE_ROLES_FOR_CUSTOM: tuple[str, ...] = (
    WEREWOLF,
    WOLF_KING,
    SEER,
    WITCH,
    HUNTER,
    GUARD,
    GRAVEDIGGER,
    FOOL,
    KNIGHT,
    VILLAGER,
)

# =====================================================================
# 阵营
# =====================================================================
GOOD = "good"
EVIL = "evil"

ROLE_FACTION: dict[str, str] = {
    WEREWOLF: EVIL,
    WOLF_KING: EVIL,
    SEER: GOOD,
    WITCH: GOOD,
    HUNTER: GOOD,
    GUARD: GOOD,
    GRAVEDIGGER: GOOD,
    FOOL: GOOD,
    KNIGHT: GOOD,
    VILLAGER: GOOD,
}

# 神职（非平民的好人）。屠边判定用。
SPECIAL_ROLES: frozenset[str] = frozenset(
    {SEER, WITCH, HUNTER, GUARD, GRAVEDIGGER, FOOL, KNIGHT}
)

# 狼人阵营角色。狼人合议与「不刀队友」判定共用。
WOLF_ROLES: frozenset[str] = frozenset({WEREWOLF, WOLF_KING})

# =====================================================================
# 阶段
# =====================================================================
PHASE_NIGHT = "night"
PHASE_DAY_ANNOUNCEMENT = "day_announcement"
PHASE_DAY_HUNTER = "day_hunter"  # 源项目的枚举成员，实际流程未使用（保留以保持枚举完整）
PHASE_DAY_KNIGHT = "day_knight"
PHASE_DAY_MARKING = "day_marking"
PHASE_DAY_VOTING = "day_voting"
PHASE_DAY_TRIGGER = "day_trigger"
PHASE_GAME_OVER = "game_over"

PHASES: tuple[str, ...] = (
    PHASE_NIGHT,
    PHASE_DAY_ANNOUNCEMENT,
    PHASE_DAY_HUNTER,
    PHASE_DAY_KNIGHT,
    PHASE_DAY_MARKING,
    PHASE_DAY_VOTING,
    PHASE_DAY_TRIGGER,
    PHASE_GAME_OVER,
)

PHASE_LABELS: dict[str, str] = {
    PHASE_NIGHT: "夜晚",
    PHASE_DAY_ANNOUNCEMENT: "白天公告",
    PHASE_DAY_HUNTER: "猎人阶段",
    PHASE_DAY_KNIGHT: "骑士阶段",
    PHASE_DAY_MARKING: "标记发言",
    PHASE_DAY_VOTING: "投票",
    PHASE_DAY_TRIGGER: "特殊触发",
    PHASE_GAME_OVER: "游戏结束",
}

# 夜晚行动顺序（严格）：守卫 → 狼人 → 女巫 → 预言家 → 守墓人
NIGHT_ACTION_ORDER: tuple[str, ...] = (GUARD, WEREWOLF, WITCH, SEER, GRAVEDIGGER)

# =====================================================================
# 人数
# =====================================================================
MIN_PLAYERS = 4
MAX_PLAYERS = 12

# =====================================================================
# 物品 / 遗物
# =====================================================================
MOONSTONE = "moonstone"
BALANCE = "balance"
HOUND_WHISTLE = "houndWhistle"

ITEM_LABELS: dict[str, str] = {
    MOONSTONE: "月光石",
    BALANCE: "天平徽章",
    HOUND_WHISTLE: "猎犬哨",
}

# 只使用「基础物品」的局型上限（7 人及以上才默认追加猎犬哨）
BASIC_ITEM_POOL: tuple[str, ...] = (MOONSTONE, BALANCE)
LARGE_GAME_ITEM_POOL: tuple[str, ...] = (MOONSTONE, BALANCE, HOUND_WHISTLE)
LARGE_GAME_MIN_PLAYERS = 7

# =====================================================================
# 标记理由
# =====================================================================
REASON_INTUITION = "intuition"
REASON_VOTE_ANALYSIS = "vote_analysis"
REASON_MARK_ANALYSIS = "mark_analysis"
REASON_LOG_REASONING = "log_reasoning"
REASON_INVESTIGATION = "investigation"
REASON_POTION_RESULT = "potion_result"

COMMON_REASONS: tuple[str, ...] = (
    REASON_INTUITION,
    REASON_VOTE_ANALYSIS,
    REASON_MARK_ANALYSIS,
    REASON_LOG_REASONING,
)

SPECIAL_REASONS: tuple[str, ...] = (
    REASON_INVESTIGATION,
    REASON_POTION_RESULT,
)

REASON_LABELS: dict[str, str] = {
    REASON_INTUITION: "直觉判断",
    REASON_VOTE_ANALYSIS: "投票分析",
    REASON_MARK_ANALYSIS: "标记分析",
    REASON_LOG_REASONING: "日志推理",
    REASON_INVESTIGATION: "查验结论",
    REASON_POTION_RESULT: "用药结果",
}

# 「查询结论」理由只对这两种**公开声明**身份开放（不校验真实角色，允许诈身份）
INVESTIGATION_IDENTITIES: tuple[str, ...] = ("预言家", "守墓人")
POTION_IDENTITIES: tuple[str, ...] = ("女巫",)

# 身份声明（给自己）可选的固定项；「狼人」只出现在评价标记里
IDENTITY_ROLE_FIRST = "神职"
IDENTITY_GOOD = "好人"
IDENTITY_WOLF = "狼人"

# 标记身份选项的中文标签 → 角色 key（当局包含该角色时才出现）
IDENTITY_TO_ROLE: dict[str, str] = {
    "预言家": SEER,
    "女巫": WITCH,
    "猎人": HUNTER,
    "守卫": GUARD,
    "守墓人": GRAVEDIGGER,
    "白痴": FOOL,
    "骑士": KNIGHT,
    "平民": VILLAGER,
}

# =====================================================================
# 死因
# =====================================================================
DEATH_ATTACKED = "attacked"
DEATH_POISONED = "poisoned"
DEATH_EXILED = "exiled"
DEATH_SHOT = "shot"
DEATH_WOLF_KING_DRAG = "wolfKingDrag"
DEATH_DUEL = "duel"
DEATH_GUARD_WITCH_CLASH = "guardWitchClash"
DEATH_RESIGNED = "resigned"

# 完整死因标签（复盘 / AI 上下文用）
DEATH_CAUSE_LABELS: dict[str, str] = {
    DEATH_ATTACKED: "被狼人袭击",
    DEATH_POISONED: "被毒死",
    DEATH_EXILED: "被放逐",
    DEATH_SHOT: "被猎人射杀",
    DEATH_WOLF_KING_DRAG: "被白狼王带走",
    DEATH_DUEL: "决斗出局",
    DEATH_GUARD_WITCH_CLASH: "同守同救出局",
    DEATH_RESIGNED: "认输",
}

# 白天公开事件（放逐/开枪/带人/决斗/认输）才显示死因；夜间出局一律不显示死因
PUBLIC_DEATH_CAUSE_LABELS: dict[str, str] = {
    DEATH_EXILED: "放逐",
    DEATH_SHOT: "猎人射杀",
    DEATH_WOLF_KING_DRAG: "白狼王带走",
    DEATH_DUEL: "决斗",
    DEATH_RESIGNED: "认输",
}


def is_night_death_cause(cause: str) -> bool:
    """该死因是否属于「夜间出局」。

    夜间出局的具体死因（毒药、同守同救）属于女巫/守卫的私有信息，不对外公开。
    """
    return cause in (DEATH_ATTACKED, DEATH_POISONED, DEATH_GUARD_WITCH_CLASH)


def to_public_death_cause(cause: str) -> str:
    """对外公开的死因：夜间出局统一显示为「被袭击」。

    避免通过死因泄露女巫是否用药、守卫是否触发同守同救。
    仅用于对外广播与 AI 公开信息；结算复盘仍使用真实死因。
    """
    return DEATH_ATTACKED if is_night_death_cause(cause) else cause


# =====================================================================
# 默认时长（秒）。QQ 侧的实际取值在 config.py / 房间配置里覆盖。
# =====================================================================
DEFAULT_TIMERS: dict[str, int] = {
    "marking": 60,
    "voting": 30,
    "night_action": 20,
}

# =====================================================================
# 预设板子
# =====================================================================
@dataclass(frozen=True)
class PresetConfig:
    """一套预设板子。``roles`` 是「角色 → 数量」。"""

    roles: dict[str, int]
    win_condition: str  # "edge"（屠边）| "city"（屠城）


WIN_EDGE = "edge"
WIN_CITY = "city"

PRESETS: dict[str, PresetConfig] = {
    "4standard": PresetConfig(
        {WEREWOLF: 1, GUARD: 1, WITCH: 1, VILLAGER: 1}, WIN_EDGE
    ),
    "5standard": PresetConfig(
        {WEREWOLF: 1, SEER: 1, WITCH: 1, VILLAGER: 2}, WIN_EDGE
    ),
    # 6 人标准局是唯一默认屠城的板子（人数少时屠边过于容易达成）
    "6standard": PresetConfig(
        {WEREWOLF: 2, SEER: 1, WITCH: 1, VILLAGER: 2}, WIN_CITY
    ),
    "6gods": PresetConfig(
        {WEREWOLF: 2, SEER: 1, WITCH: 1, HUNTER: 1, VILLAGER: 1}, WIN_EDGE
    ),
    "7standard": PresetConfig(
        {WEREWOLF: 2, SEER: 1, WITCH: 1, HUNTER: 1, VILLAGER: 2}, WIN_EDGE
    ),
    "8wolfking": PresetConfig(
        {WOLF_KING: 1, WEREWOLF: 2, SEER: 1, WITCH: 1, HUNTER: 1, VILLAGER: 2},
        WIN_EDGE,
    ),
    "8knight": PresetConfig(
        {WEREWOLF: 2, SEER: 1, WITCH: 1, KNIGHT: 1, FOOL: 1, VILLAGER: 2},
        WIN_EDGE,
    ),
    "9standard": PresetConfig(
        {WEREWOLF: 3, SEER: 1, WITCH: 1, HUNTER: 1, VILLAGER: 3}, WIN_EDGE
    ),
    "9grave": PresetConfig(
        {WEREWOLF: 3, SEER: 1, WITCH: 1, HUNTER: 1, GRAVEDIGGER: 1, VILLAGER: 2},
        WIN_EDGE,
    ),
    "10guard": PresetConfig(
        {WEREWOLF: 3, SEER: 1, WITCH: 1, HUNTER: 1, GUARD: 1, VILLAGER: 3},
        WIN_EDGE,
    ),
    "12standard": PresetConfig(
        {WEREWOLF: 4, SEER: 1, WITCH: 1, HUNTER: 1, GUARD: 1, VILLAGER: 4},
        WIN_EDGE,
    ),
    "12full": PresetConfig(
        {
            WOLF_KING: 1,
            WEREWOLF: 3,
            SEER: 1,
            WITCH: 1,
            HUNTER: 1,
            GRAVEDIGGER: 1,
            KNIGHT: 1,
            FOOL: 1,
            VILLAGER: 2,
        },
        WIN_EDGE,
    ),
}

# 展示名（与源项目 CreateRoomModal.PRESET_LABELS 逐字一致）
PRESET_LABELS: dict[str, str] = {
    "4standard": "4 人标准",
    "5standard": "5 人标准",
    "6standard": "6 人标准",
    "6gods": "6 人神职",
    "7standard": "7 人标准",
    "8wolfking": "8 人白狼王",
    "8knight": "8 人骑士",
    "9standard": "9 人标准",
    "9grave": "9 人守墓人",
    "10guard": "10 人守卫",
    "12standard": "12 人标准",
    "12full": "12 人全角色",
}
