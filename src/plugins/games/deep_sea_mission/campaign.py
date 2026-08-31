"""深海任务 · 战役模式数据层。

32 关 + Epilogue 的关卡数据与查询，纯数据模块（不 import NoneBot / session / game 逻辑），
可被 game.py 与 CLI adapter 复用。数据来源见
``docs/games/deep-sea-mission-campaign.md`` §四（已三方核对定稿）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .tasks import TASK_CARDS, TaskCard


# =====================================================================
# 沟通符号（modifiers）
# =====================================================================
MOD_CURRENTS = "currents"          # ❓ 通信中断：声呐不公开 marker
MOD_RAPTURE = "rapture"            # -2 深海狂喜：声呐全队共享 quota
MOD_UNFAMILIAR = "unfamiliar"      # 🔴 陌生地形：发牌前抽颜色卡定声呐规则
MOD_REALTIME = "realtime"          # 🕒 限时：面板提示 + 默认走替代规则（不做真实倒计时）
MOD_FREE_SELECTION = "free_selection"  # 🐙 自由选任务：可自由讨论任务分配
MOD_DISTRESS = "distress"          # ⚓ 求救信号：开局可选传牌（本关尝试数 +1，简化为提示）
MOD_SILENCE = "silence"            # 禁止交流（M16 替代规则）

# 任务分配规则（assignment）
ASG_ALL_ONE_CREW = "all_one_crew"           # M6：所有任务给一名船员（自荐包揽）
ASG_CAPTAIN_ALL = "captain_all"             # M10/M13：队长拿全部任务
ASG_SELF_NOMINATE_1 = "self_nominate_1"     # M14/15/16：一人自荐包揽
ASG_SELF_NOMINATE_2 = "self_nominate_2"     # M26：两人自荐包揽
ASG_HARDEST_TO_CAPTAIN = "hardest_to_captain"  # M19：最难任务给队长
ASG_CAPTAIN_NO_TASK = "captain_no_task"     # M25：队长不接任务


@dataclass(frozen=True)
class Mission:
    no: int
    difficulty: int | None = None        # None = 无难度数字（M8/12/21/23/27/32）
    modifiers: tuple[str, ...] = ()
    assignment: str | None = None        # None = 现有轮流选
    task_source: str = "draw"            # draw | fixed | none
    special: str | None = None           # task_source=="none" 时的胜利约束文本
    note: str = ""                       # 附加说明


CAMPAIGN_MISSIONS: dict[int, Mission] = {
    1: Mission(1, 1),
    2: Mission(2, 2),
    3: Mission(3, 3),
    4: Mission(4, 4),
    5: Mission(5, 5),
    6: Mission(6, 5, assignment=ASG_ALL_ONE_CREW, note="所有任务给一名船员（自荐包揽）"),
    7: Mission(7, 6),
    8: Mission(
        8,
        difficulty=None,
        task_source="none",
        special="不得有玩家比其他玩家多赢 2 张 9",
    ),
    9: Mission(9, 7, modifiers=(MOD_CURRENTS,)),
    10: Mission(
        10,
        4,
        assignment=ASG_CAPTAIN_ALL,
        note="队长拿全部任务；若分出去，则首墩前完成全部交流",
    ),
    11: Mission(11, 8, modifiers=(MOD_RAPTURE,)),
    12: Mission(
        12,
        difficulty=None,
        task_source="none",
        special="不得用粉牌或潜艇开墩",
    ),
    13: Mission(
        13,
        5,
        assignment=ASG_CAPTAIN_ALL,
        note="队长拿全部任务；若分出去，则首墩前完成全部交流",
    ),
    14: Mission(
        14,
        6,
        modifiers=(MOD_REALTIME, MOD_CURRENTS),
        assignment=ASG_SELF_NOMINATE_1,
        note="🕒 3:30 限时（不计时则 ❓ Currents）",
    ),
    15: Mission(
        15,
        6,
        modifiers=(MOD_REALTIME, MOD_RAPTURE),
        assignment=ASG_SELF_NOMINATE_1,
        note="🕒 3:00 限时（不计时则 -2 Rapture）",
    ),
    16: Mission(
        16,
        6,
        modifiers=(MOD_REALTIME, MOD_SILENCE),
        assignment=ASG_SELF_NOMINATE_1,
        note="🕒 2:30 限时（不计时则禁止交流）",
    ),
    17: Mission(17, 9, modifiers=(MOD_FREE_SELECTION,)),
    18: Mission(18, 9),
    19: Mission(19, 9, assignment=ASG_HARDEST_TO_CAPTAIN, note="最难任务给队长"),
    20: Mission(20, 10, modifiers=(MOD_UNFAMILIAR,)),
    21: Mission(
        21,
        difficulty=None,
        task_source="none",
        modifiers=(MOD_UNFAMILIAR,),
        special="🔴 + 不得有玩家比其他玩家多赢 2 张 1",
    ),
    22: Mission(22, 11, modifiers=(MOD_UNFAMILIAR,)),
    23: Mission(
        23,
        difficulty=None,
        task_source="none",
        modifiers=(MOD_UNFAMILIAR,),
        special="🔴 + 赢首墩者须始终领先赢墩数 + 第二墩前禁止交流",
    ),
    24: Mission(24, 12, modifiers=(MOD_UNFAMILIAR,)),
    25: Mission(
        25,
        12,
        modifiers=(MOD_UNFAMILIAR,),
        assignment=ASG_CAPTAIN_NO_TASK,
        note="队长不接任务",
    ),
    26: Mission(
        26,
        12,
        modifiers=(MOD_REALTIME,),
        assignment=ASG_SELF_NOMINATE_2,
        note="🕒 5:00 限时（10 tasks），不计时则 12 tasks",
    ),
    27: Mission(
        27,
        difficulty=None,
        task_source="none",
        modifiers=(MOD_UNFAMILIAR,),
        special="🔴 + 黄 5 须作为最后一墩的最后一张牌",
    ),
    28: Mission(28, 14, modifiers=(MOD_FREE_SELECTION,)),
    29: Mission(29, 15, modifiers=(MOD_FREE_SELECTION,)),
    30: Mission(30, 16, modifiers=(MOD_FREE_SELECTION,)),
    31: Mission(31, 17, modifiers=(MOD_FREE_SELECTION,)),
    32: Mission(32, difficulty=None, task_source="fixed", note="固定 4 张任务，不抽卡"),
}

EPILOGUE_START_DIFFICULTY = 18
EPILOGUE_MODIFIERS = (MOD_FREE_SELECTION,)

# 战役关卡进度持久化 key（存 group_config）。值形如 "5" 或 "epilogue:18"。
CAMPAIGN_LEVEL_KEY = "deep_sea_mission.campaign.level"


def parse_campaign_progress(raw: str) -> tuple[int | None, int | None]:
    """解析进度值，返回 (mission_no, epilogue_difficulty)。"""
    raw = (raw or "").strip()
    if raw.startswith("epilogue:"):
        try:
            return None, int(raw.split(":", 1)[1])
        except ValueError:
            return None, EPILOGUE_START_DIFFICULTY
    try:
        no = int(raw)
    except ValueError:
        return 1, None
    if not 1 <= no <= 32:
        no = 1
    return no, None


def parse_campaign_arg(text: str) -> tuple[int | None, int | None] | None:
    """解析「@我 深海战役 N」的显式关卡参数；无法识别返回 None。

    支持：``5``（第 5 关）、``epilogue:18``（Epilogue 难度 18）。
    """
    text = (text or "").strip()
    if text.startswith("epilogue:"):
        try:
            return None, int(text.split(":", 1)[1])
        except ValueError:
            return None
    if text.isdigit():
        no = int(text)
        if 1 <= no <= 32:
            return no, None
    return None


# M32 固定任务卡 ID（顺序按官方 Logbook）
_M32_TASK_IDS = ("T074", "T088", "T085", "T080")


def get_mission(no: int) -> Mission:
    """按关卡号查表。1..32 合法，越界抛 ValueError。"""
    mission = CAMPAIGN_MISSIONS.get(no)
    if mission is None:
        raise ValueError(f"战役关卡 {no} 不存在（仅支持 1-32）")
    return mission


def fixed_tasks_m32(player_count: int) -> list[dict[str, int | str | bool | None]]:
    """M32 固定任务：不抽卡，返回固定 4 张任务卡（复用 TASK_CARDS）。"""
    by_id: dict[str, TaskCard] = {card.id: card for card in TASK_CARDS}
    return [
        {
            "id": card.id,
            "text": card.text,
            "difficulty": card.difficulty_for(player_count),
            "assigned_to": None,
            "completed": False,
        }
        for task_id in _M32_TASK_IDS
        for card in [by_id[task_id]]
    ]
