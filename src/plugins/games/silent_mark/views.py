"""静夜标记 · 文本渲染（公告 / 面板 / 私聊卡片 / 结算）。

与 `syntax.py` 的分工：

- `syntax.py` 负责**输入提示**（与解析配对，必须与解析保持一致）；
- 本模块负责**游戏状态的可读表达**（公告、面板、结算、我的记录）。

两者共用 `syntax.player_label`，保证座位称谓处处一致。
本模块不产生玩家输入提示，也不解析任何输入。
"""

from __future__ import annotations

from .engine import constants as C  # noqa: N812
from .engine import private_info
from .engine.types import (
    DeathRecordDict,
    GameStateDict,
    ItemDict,
    PlayerDict,
    PlayerMarksDict,
    VoteRecordDict,
)
from .syntax import player_label

#: 各角色的能力速记（群里没有 UI，这一行决定了玩家知不知道自己能干什么）
ROLE_HINTS: dict[str, str] = {
    C.WEREWOLF: "夜里与同伴共同选择袭击目标；白天要伪装成好人。允许自刀。",
    C.WOLF_KING: "夜里同狼人行动；被放逐出局时可带走一名存活玩家。",
    C.SEER: "每夜查验一名玩家的阵营（好人/狼人）。",
    C.WITCH: "解药、毒药各一瓶；首夜可以自救，之后不能。同一晚只能用一瓶药。",
    C.HUNTER: "出局时可以选择开枪带走一人。**被女巫毒死则不能开枪**。",
    C.GUARD: "每夜守护一人（可守自己），不可连续两晚守护同一人。",
    C.GRAVEDIGGER: "每夜查验一名**已出局**玩家的阵营。",
    C.FOOL: "被投票放逐时免疫一次，之后失去投票权但仍可标记。",
    C.KNIGHT: "白天可决斗一名玩家（全局一次）：对方是狼则对方出局，否则你自己出局。",
    C.VILLAGER: "没有特殊能力，用标记和投票找出狼人。",
}

#: 胜利原因的展示文案（key 与 `engine.resolve` 返回的 reason 一一对应）
WIN_REASON_LABELS: dict[str, str] = {
    "wolves_eliminated": "所有狼人已出局",
    "good_eliminated": "所有好人已出局",
    "specials_eliminated": "所有神职已出局",
    "villagers_eliminated": "所有平民已出局",
}

FACTION_LABELS: dict[str, str] = {C.GOOD: "好人阵营", C.EVIL: "狼人阵营"}

WIN_CONDITION_LABELS: dict[str, str] = {
    C.WIN_EDGE: "屠边（杀光神职 或 杀光平民）",
    C.WIN_CITY: "屠城（杀光所有好人）",
}


# =====================================================================
# 小工具
# =====================================================================
def item_label(item: ItemDict) -> str:
    """物品/遗物的展示文案。存活时只暴露类型（内容未知）。"""
    name = C.ITEM_LABELS.get(item["type"], item["type"])
    if item["type"] == C.MOONSTONE:
        return f"{name}: {item['value']}"
    if item["type"] == C.BALANCE:
        value = "平衡" if item["value"] == "balanced" else "失衡"
        return f"{name}: {value}"
    if item["type"] == C.HOUND_WHISTLE:
        return f"{name}: {item['value']}"
    return f"{name}: {item['value']}"


def render_seat_list(state: GameStateDict, *, only_alive: bool = False) -> str:
    """座位表。存活 ✅ / 出局 💀。"""
    parts: list[str] = []
    for player in sorted(state["players"], key=lambda p: p["seat"]):
        if only_alive and not player["alive"]:
            continue
        mark = "✅" if player["alive"] else "💀"
        parts.append(f"{player['seat']}号 {player['nickname']}{mark}")
    return "　".join(parts) if parts else "（无）"


def render_phase(state: GameStateDict, title: str) -> str:
    """阶段标题 + 座位表（每一幕的开场白）。"""
    return f"{title}\n{render_seat_list(state)}"


def _reliquary_line(items: list[ItemDict]) -> str:
    if not items:
        return "　遗物：（无）"
    return "　遗物：" + "、".join(item_label(item) for item in items)


def compact_marks_line(state: GameStateDict, marks: PlayerMarksDict) -> str:
    """一条标记的**单行**表达（给看板用，不能丢理由）。"""
    identity = marks["identity_mark"]
    reason = C.REASON_LABELS.get(identity["reason"], identity["reason"])
    head = f"{player_label(state, marks['player'])} 声明{identity['identity']}（{reason}）"
    if not marks["evaluation_marks"]:
        return head
    evaluations = "、".join(
        f"{player_label(state, mark['target'])} 是 {mark['identity']}"
        f"（{C.REASON_LABELS.get(mark['reason'], mark['reason'])}）"
        for mark in marks["evaluation_marks"]
    )
    return f"{head} → {evaluations}"


def render_marks_log(state: GameStateDict) -> list[str]:
    """**本轮**标记记录（历史轮次不进看板，否则板子会无限长）。"""
    marks = [
        m
        for m in (state.get("history", {}).get("marks") or [])
        if m.get("round") == state.get("round")
    ]
    if not marks:
        return []
    return ["📝 本轮标记：", *(f"　{compact_marks_line(state, m)}" for m in marks)]


# =====================================================================
# 对局面板（群里唯一常驻的一条消息）
# =====================================================================
def render_board(
    state: GameStateDict,
    settings: dict,
    *,
    headline: str,
    tail_lines: list[str] | None = None,
    show_rules: bool = False,
) -> str:
    """群里的**唯一常驻面板**——一条消息，状态变了就原地更新（删旧发新）。

    这是"不让群友觉得刷屏"的核心手段（对齐 `deep_sea_mission` 的做法）：

    - **所有状态**（板子、座位、进度、本轮标记与投票记录）都塞进这一条，
      所以群消息条数**不随回合数增长**；
    - 只有"关键时刻"（死讯 / 开枪 / 放逐 / 结算）才另发新消息——
      因为那些是玩家要回看的独立事件，塞进板子反而会被下一次更新抹掉。

    ``show_rules=True`` 用于开局那一次（板子与胜负条件只在开局说一遍）。
    """
    lines = [headline]
    if show_rules:
        roles = settings.get("roles") or {}
        role_text = " · ".join(
            f"{C.ROLE_LABELS.get(role, role)}×{count}"
            for role, count in roles.items()
            if count
        )
        preset = settings.get("preset") or "custom"
        preset_label = C.PRESET_LABELS.get(preset, preset)
        win_condition = settings.get("win_condition", C.WIN_EDGE)
        items_cfg = settings.get("items") or {}
        item_text = (
            "、".join(C.ITEM_LABELS.get(i, i) for i in items_cfg.get("pool", []))
            if items_cfg.get("enabled", True)
            else "未启用"
        )
        lines.extend(
            [
                f"板子：{preset_label}（{role_text}）",
                f"狼人胜利条件：{WIN_CONDITION_LABELS.get(win_condition, win_condition)}",
                f"随身物品：{item_text}（出局后内容公开）",
                "📩 身份牌已私聊发出；@我 记录 随时查看你的身份与私有信息。",
            ]
        )

    lines.extend(["", render_seat_list(state)])

    marks_log = render_marks_log(state)
    if marks_log:
        lines.extend(["", *marks_log])
    if tail_lines:
        lines.extend(["", *tail_lines])
    return "\n".join(lines)


def render_role_card(state: GameStateDict, player: PlayerDict) -> str:
    """私聊身份牌。只包含该玩家有权知道的信息。"""
    role = player["role"]
    lines = [
        "🎭 你的身份牌",
        f"座位：{player['seat']}号 {player['nickname']}",
        f"身份：{C.ROLE_LABELS.get(role, role)}（{FACTION_LABELS.get(player['faction'], player['faction'])}）",
    ]

    if role in C.WOLF_ROLES:
        mates = [
            f"{p['seat']}号 {p['nickname']}"
            for p in state["players"]
            if p["faction"] == C.EVIL and p["pid"] != player["pid"]
        ]
        lines.append(f"同伴：{'、'.join(mates) if mates else '（无，你独自一人）'}")

    lines.append(f"能力：{ROLE_HINTS.get(role, '（无特殊能力）')}")

    if player["items"]:
        lines.append(
            "随身物品：" + "、".join(item_label(item) for item in player["items"])
            + "（内容未知，出局后公开）"
        )
    else:
        lines.append("随身物品：（无）")

    win_condition = state.get("win_condition", C.WIN_EDGE)
    lines.append(f"狼人胜利条件：{WIN_CONDITION_LABELS.get(win_condition, win_condition)}")
    lines.append("")
    lines.append("💡 夜里按私聊提示行动；白天在群里按提示标记发言（@我 记录 可随时查看你的记录）")
    return "\n".join(lines)


# =====================================================================
# 夜晚 / 白天公告
# =====================================================================
def render_night_start(state: GameStateDict) -> str:
    return render_phase(state, f"🌙 第 {state['round']} 夜 —— 天黑请闭眼")


def render_night_result(
    state: GameStateDict, deaths: list[DeathRecordDict]
) -> str:
    """夜晚结算公告。

    只公布**谁出局**，不公布死因（夜间死因会泄露女巫用药与守卫守护），
    也不能透露"是被守住的"——平安夜与"守住了"在公告上必须一样。
    """
    header = f"☀️ 第 {state['round']} 夜结算"
    if not deaths:
        return f"{header}\n平安夜，无人出局。"

    lines = [header]
    for death in deaths:
        lines.append(f"⚠️ {player_label(state, death['pid'])} 出局")
        lines.append(_reliquary_line(death["relics"]))
    return "\n".join(lines)


def render_exile(state: GameStateDict, record: DeathRecordDict) -> str:
    """放逐公告（白天事件，可以公布死因）。"""
    return "\n".join(
        [
            f"⚖️ {player_label(state, record['pid'])} 被放逐出局",
            _reliquary_line(record["relics"]),
        ]
    )


def render_death_notice(
    state: GameStateDict, record: DeathRecordDict, headline: str
) -> str:
    """白天各类出局的通用公告（开枪 / 带人 / 决斗 / 认输）。"""
    return "\n".join(
        [
            f"{headline} → {player_label(state, record['pid'])} 出局",
            _reliquary_line(record["relics"]),
        ]
    )


def render_vote_detail(
    state: GameStateDict, votes: list[VoteRecordDict], result: dict
) -> str:
    """投票明细 + 结果（投票结束后一次性公开）。"""
    lines = [f"🗳 第 {state['round']} 轮投票结果"]
    if not votes:
        lines.append("（没有有效投票）")
    for vote in votes:
        lines.append(
            f"　{player_label(state, vote['voter'])} → {player_label(state, vote['target'])}"
        )
    if result.get("tie"):
        lines.append("结果：平票，无人出局")
    elif result.get("exiled"):
        lines.append(f"结果：{player_label(state, result['exiled'])} 得票最高，将被放逐")
    else:
        lines.append("结果：无人出局")
    return "\n".join(lines)


def render_fool_immunity(state: GameStateDict, pid: str) -> str:
    return (
        f"🤪 {player_label(state, pid)} 是【白痴】，本次放逐免疫（身份公开，"
        "此后失去投票权但仍可标记发言）"
    )


# =====================================================================
# 结算
# =====================================================================
def render_game_over(state: GameStateDict, verdict: dict | None) -> str:
    """终局：胜负 + 全部身份公开。"""
    winner = (verdict or {}).get("winner") or state.get("winner")
    reason = (verdict or {}).get("reason") or ""
    faction_text = FACTION_LABELS.get(winner, str(winner))

    lines = [f"🏆 游戏结束 —— {faction_text}胜利"]
    if reason:
        lines.append(f"（{WIN_REASON_LABELS.get(reason, reason)}）")
    lines.append("")
    lines.append("全部身份：")
    for player in sorted(state["players"], key=lambda p: p["seat"]):
        status = "" if player["alive"] else "（出局）"
        role = C.ROLE_LABELS.get(player["role"], player["role"])
        lines.append(
            f"　{player['seat']}号 {player['nickname']} — {role}{status}"
        )
    return "\n".join(lines)


def render_aborted(state: GameStateDict, reason_label: str) -> str:
    return "\n".join(
        [
            f"🏳 本局静夜标记已结束（{reason_label}）",
            f"进行到第 {state.get('round', 1)} 轮 · {C.PHASE_LABELS.get(state.get('phase', ''), '')}",
            render_seat_list(state),
        ]
    )


# =====================================================================
# 复盘（@我 复盘）
# =====================================================================
def render_replay(
    state: GameStateDict, settings: dict, *, reveal_all: bool
) -> list[str]:
    """按轮次回看整局：**一页一轮**（列表长度 = 1 概览 + 轮数）。

    ``reveal_all``：对局**结束**后为 True —— 只有那时才写**真实死因**
    （被毒死 / 同守同救 / 猎人射杀）。进行中一律用公开口径「被袭击」，
    否则一句"被毒死"就等于把女巫当晚的用药摊在群里（信息防火墙）。
    """
    deaths = state["history"]["deaths"]
    marks = state["history"]["marks"]
    votes = state["history"]["votes"]

    head = [
        "🌙 静夜标记 · 复盘",
        f"板子：{_preset_line(settings)}",
        render_seat_list(state),
    ]
    winner = state.get("winner")
    if winner:
        reason = WIN_REASON_LABELS.get(state.get("end_reason_code") or "", "对局结束")
        side = "好人" if winner == C.GOOD else "狼人"
        head.append(f"🏆 {side}阵营胜利（{reason}）")
        if reveal_all:
            head.append(_all_roles_line(state))
    pages = ["\n".join(head)]

    for round_no in range(1, max(1, state["round"]) + 1):
        lines = [f"—— 第 {round_no} 轮 ——"]
        night = [record for record in deaths if record["round"] == round_no]
        if night:
            lines.extend(_death_line(state, record, reveal_all=reveal_all) for record in night)
        else:
            lines.append("（无出局）")

        round_marks = [m for m in marks if m["round"] == round_no]
        if round_marks:
            lines.append("标记发言：")
            lines.extend(f"　{compact_marks_line(state, m)}" for m in round_marks)

        if round_no - 1 < len(votes) and votes[round_no - 1]:
            pairs = "，".join(
                f"{player_label(state, vote['voter'])}→{player_label(state, vote['target'])}"
                for vote in votes[round_no - 1]
            )
            lines.append(f"投票：{pairs}")
        pages.append("\n".join(lines))

    return pages


def _preset_line(settings: dict) -> str:
    roles = settings.get("roles") or {}
    role_text = " · ".join(
        f"{C.ROLE_LABELS.get(role, role)}×{count}" for role, count in roles.items() if count
    )
    name = settings.get("preset") if settings.get("mode") == "preset" else None
    label = C.PRESET_LABELS.get(name, name) if name else "自定义"
    return f"{label}（{role_text}）" if role_text else str(label)


def _death_line(
    state: GameStateDict, record: DeathRecordDict, *, reveal_all: bool
) -> str:
    raw = record["cause"] if reveal_all else C.to_public_death_cause(record["cause"])
    cause = C.DEATH_CAUSE_LABELS.get(raw, record["cause"])
    relics = "、".join(item_label(item) for item in record["relics"] if item["revealed"])
    tail = f"（遗物：{relics}）" if relics else ""
    return f"出局：{player_label(state, record['pid'])} · {cause}{tail}"


def _all_roles_line(state: GameStateDict) -> str:
    parts = [
        f"{player['seat']}号{player['nickname']}={C.ROLE_LABELS.get(player['role'], player['role'])}"
        for player in sorted(state["players"], key=lambda p: p["seat"])
    ]
    return "全部身份：" + "　".join(parts)


# =====================================================================
# 我的记录（私聊 / @我 记录）
# =====================================================================
def render_my_records(state: GameStateDict, player: PlayerDict) -> str:
    """按角色裁剪的私有记录。数据来源是 `engine.private_info`（唯一出口）。"""
    info = private_info.build_my_private_info(state, player)
    role = player["role"]

    lines = [
        f"📋 我的记录 — {player['seat']}号 {player['nickname']}"
        f"（{C.ROLE_LABELS.get(role, role)}）",
    ]
    if player["items"]:
        lines.append("随身物品：" + "、".join(item_label(i) for i in player["items"]))
    lines.append("")

    investigations = info.get("investigations")
    if investigations is not None:
        if investigations:
            for record in investigations:
                kind = "查验" if record["kind"] == "seer" else "验尸"
                faction = "好人" if record["faction"] == C.GOOD else "狼人"
                lines.append(
                    f"　第{record['round']}夜 {kind}："
                    f"{player_label(state, record['target'])} → {faction}阵营"
                )
        else:
            lines.append("　（还没有查验记录）")

    witch = info.get("witch")
    if witch is not None:
        lines.append(
            f"　解药：{'已用完' if witch['antidote_used'] else '未使用'}"
            f"　毒药：{'已用完' if witch['poison_used'] else '未使用'}"
        )
        for record in witch["potion_history"]:
            potion = "解药救" if record["potion"] == "antidote" else "毒药毒"
            target = (
                player_label(state, record["target"]) if record["target"] else "（未指定）"
            )
            lines.append(f"　第{record['round']}夜 {potion} {target}")

    guard = info.get("guard")
    if guard is not None:
        last = guard["last_guard_target"]
        lines.append(
            "　上一夜守护："
            + (player_label(state, last) if last else "（无）")
            + "（不可连续守护同一人）"
        )
        for record in guard["history"]:
            lines.append(f"　第{record['round']}夜 守护 {player_label(state, record['target'])}")

    wolf_attacks = info.get("wolf_attacks")
    if wolf_attacks is not None:
        for record in wolf_attacks:
            lines.append(f"　第{record['round']}夜 袭击 {player_label(state, record['target'])}")
        lines.append("　（狼人同伴：" + _mate_line(state, player) + "）")

    if "hunter_can_shoot" in info:
        lines.append(f"　开枪状态：{'仍可开枪' if info['hunter_can_shoot'] else '已无法开枪'}")
    if "knight_duel_used" in info:
        lines.append(f"　决斗状态：{'已发动' if info['knight_duel_used'] else '未发动'}")
    if "fool_immunity_used" in info:
        lines.append(f"　免疫状态：{'已消耗' if info['fool_immunity_used'] else '未消耗'}")

    if not any(
        key in info
        for key in ("investigations", "witch", "guard", "wolf_attacks",
                    "hunter_can_shoot", "knight_duel_used", "fool_immunity_used")
    ):
        lines.append("　你的角色没有需要记录的私有信息。")

    return "\n".join(lines)


def _mate_line(state: GameStateDict, player: PlayerDict) -> str:
    mates = [
        f"{p['seat']}号 {p['nickname']}"
        for p in state["players"]
        if p["faction"] == C.EVIL and p["pid"] != player["pid"]
    ]
    return "、".join(mates) if mates else "（无）"


__all__ = [
    "ROLE_HINTS",
    "WIN_REASON_LABELS",
    "item_label",
    "render_aborted",
    "render_death_notice",
    "render_board",
    "render_exile",
    "render_fool_immunity",
    "render_game_over",
    "render_marks_log",
    "render_my_records",
    "render_night_result",
    "render_night_start",
    "render_phase",
    "render_role_card",
    "render_seat_list",
    "render_vote_detail",
    "compact_marks_line",
]
