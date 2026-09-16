"""AI 信息上下文（移植自源项目 `ai/AIContextBuilder.ts`）。

**这是 AI 获取游戏信息的唯一出口** —— 严格按角色过滤，确保 AI 不能"开天眼"。

私有部分直接复用 `engine/private_info.build_my_private_info`：
源项目在那里踩过"AI 一套、真人一套，两边慢慢漂移"的坑，所以明确要求共用同一份推导。
本移植沿用：凡是给 AI 的私有信息，都必须能通过"真人也会看到这份"的检验。

死因走 ``C.to_public_death_cause``：夜间出局对外统一显示"被袭击"，
**AI 不可以知道是毒杀还是同守同救**（那是女巫/守卫的私有信息）。
"""

from __future__ import annotations

from typing import Any

from ..engine import constants as C  # noqa: N812
from ..engine import private_info
from ..engine.types import GameStateDict, PlayerDict, find_player


def _seat_of(state: GameStateDict, pid: str | None) -> int | None:
    player = find_player(state, pid)
    return player["seat"] if player else None


def _ref(player: PlayerDict) -> dict[str, Any]:
    return {
        "pid": player["pid"],
        "seat": player["seat"],
        "nickname": player["nickname"],
    }


def build_context(state: GameStateDict, pid: str) -> dict[str, Any]:
    """构建某个 AI 座位"能看到的一切"。"""
    me = find_player(state, pid)
    if me is None:
        raise ValueError(f"build_context: 找不到座位 {pid}")

    public_facts: dict[str, Any] = {
        "round": state["round"],
        "phase": state["phase"],
        "alive_players": [
            _ref(p) for p in sorted(state["players"], key=lambda p: p["seat"]) if p["alive"]
        ],
        "dead_players": [
            {
                "pid": death["pid"],
                "seat": death["seat"],
                "nickname": (find_player(state, death["pid"]) or {}).get("nickname", ""),
                # ⚠️ 公开死因：夜间出局一律"被袭击"，不泄露毒杀/同守同救
                "cause": C.to_public_death_cause(death["cause"]),
                "round": death["round"],
                "relics": [dict(item) for item in death["relics"] if item["revealed"]],
            }
            for death in state["history"]["deaths"]
        ],
        "vote_history": _vote_history(state),
    }

    private_facts: dict[str, Any] = {
        # 队友是狼阵营最重要的私有信息
        "teammates": [
            _ref(p)
            for p in sorted(state["players"], key=lambda p: p["seat"])
            if p["faction"] == C.EVIL and p["pid"] != pid
        ]
        if me["faction"] == C.EVIL
        else [],
        "investigations": [],
        "witch": None,
        "last_guard_target_seat": None,
        "wolf_attacks": [],
        "hunter_can_shoot": None,
        "knight_duel_used": None,
        "fool_immunity_used": None,
    }
    _fill_private(private_facts, state, me)

    return {
        "self": {
            **_ref(me),
            "role": me["role"],
            "faction": me["faction"],
        },
        "public_facts": public_facts,
        "private_facts": private_facts,
        "player_claims": {"marks": _marks(state)},
    }


def _vote_history(state: GameStateDict) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for index, round_votes in enumerate(state["history"]["votes"]):
        round_no = index + 1
        exiled = next(
            (
                death["seat"]
                for death in state["history"]["deaths"]
                if death["cause"] == C.DEATH_EXILED and death["round"] == round_no
            ),
            None,
        )
        history.append(
            {
                "round": round_no,
                "votes": [
                    {
                        "voter_seat": _seat_of(state, vote["voter"]),
                        "target_seat": _seat_of(state, vote["target"]),
                    }
                    for vote in round_votes
                ],
                "exiled": exiled,
            }
        )
    return history


def _marks(state: GameStateDict) -> list[dict[str, Any]]:
    return [
        {
            "round": marks["round"],
            "seat": _seat_of(state, marks["player"]),
            "identity": marks["identity_mark"]["identity"],
            "reason": marks["identity_mark"]["reason"],
            "evaluations": [
                {
                    "target_seat": _seat_of(state, evaluation["target"]),
                    "identity": evaluation["identity"],
                    "reason": evaluation["reason"],
                }
                for evaluation in marks["evaluation_marks"]
            ],
        }
        for marks in state["history"]["marks"]
    ]


def _fill_private(
    private_facts: dict[str, Any], state: GameStateDict, me: PlayerDict
) -> None:
    """把 `build_my_private_info` 的产物摊成"按座位"的可读形式。"""
    info = private_info.build_my_private_info(state, me)

    for record in info.get("investigations") or []:
        private_facts["investigations"].append(
            {
                "round": record["round"],
                "kind": record["kind"],
                "target_seat": _seat_of(state, record["target"]),
                "faction": record["faction"],
            }
        )

    witch = info.get("witch")
    if witch:
        wolves = (state.get("night_actions") or {}).get("wolves") or {}
        private_facts["witch"] = {
            "antidote_used": bool(witch["antidote_used"]),
            "poison_used": bool(witch["poison_used"]),
            "current_victim_seat": _seat_of(state, wolves.get("target")),
            "potion_history": [
                {
                    "round": record["round"],
                    "potion": record["potion"],
                    "target_seat": _seat_of(state, record["target"]),
                }
                for record in witch["potion_history"]
            ],
        }

    guard = info.get("guard")
    if guard:
        private_facts["last_guard_target_seat"] = _seat_of(
            state, guard.get("last_guard_target")
        )

    for record in info.get("wolf_attacks") or []:
        private_facts["wolf_attacks"].append(
            {"round": record["round"], "target_seat": _seat_of(state, record["target"])}
        )

    if "hunter_can_shoot" in info:
        private_facts["hunter_can_shoot"] = bool(info["hunter_can_shoot"])
    if "knight_duel_used" in info:
        private_facts["knight_duel_used"] = bool(info["knight_duel_used"])
    if "fool_immunity_used" in info:
        private_facts["fool_immunity_used"] = bool(info["fool_immunity_used"])


# =====================================================================
# 文本化
# =====================================================================
_RELIC_NOTE = (
    "（遗物说明：月光石数值=该玩家被夜间行动造访的总次数，包括被刀、被查验、被守护、被用药；"
    '天平徽章"平衡"=左右邻座同阵营，"失衡"=左右邻座不同阵营；'
    "猎犬哨数值=该玩家死亡时存活的狼人数量）"
)


def _relic_label(item: dict) -> str:
    """遗物文案 —— 复用给真人看的那份渲染，避免两边措辞漂移。"""
    from .. import views

    return views.item_label(item)


def context_to_text(context: dict[str, Any]) -> str:
    """把上下文摊成给模型看的文本（段落顺序与源项目一致）。"""
    public = context["public_facts"]
    private = context["private_facts"]
    me = context["self"]
    lines: list[str] = []

    lines.append("=== 你的真实身份（仅你可知） ===")
    lines.append(
        f"你是 {me['seat']}号玩家，身份：{C.ROLE_LABELS.get(me['role'], me['role'])}，"
        f"阵营：{'好人' if me['faction'] == C.GOOD else '狼人'}"
    )
    lines.append("")

    lines.append("=== 公开系统事实（所有玩家可见，以此为准） ===")
    lines.append(
        f"第 {public['round']} 轮，当前阶段：{C.PHASE_LABELS.get(public['phase'], public['phase'])}"
    )
    lines.append("存活玩家：")
    for player in public["alive_players"]:
        lines.append(f"{player['seat']}号玩家{'（你）' if player['pid'] == me['pid'] else ''}")

    if public["dead_players"]:
        lines.append("死亡记录：")
        for death in public["dead_players"]:
            relics = (
                f"，遗物：{'、'.join(_relic_label(item) for item in death['relics'])}"
                if death["relics"]
                else ""
            )
            cause = C.DEATH_CAUSE_LABELS.get(death["cause"], death["cause"])
            lines.append(f"第{death['round']}轮 {death['seat']}号玩家 {cause}{relics}")
        if any(death["relics"] for death in public["dead_players"]):
            lines.append(_RELIC_NOTE)

    if public["vote_history"]:
        lines.append("投票记录：")
        for record in public["vote_history"]:
            summary = "，".join(
                f"{vote['voter_seat']}号→{vote['target_seat']}号" for vote in record["votes"]
            )
            result = (
                f"→ {record['exiled']}号玩家被放逐"
                if record["exiled"]
                else "→ 平票无人出局"
            )
            lines.append(f"第{record['round']}轮：{summary} {result}")
    lines.append("")

    private_lines = _private_lines(private)
    if private_lines:
        lines.append("=== 你的私有系统事实（仅你可知） ===")
        lines.extend(f"- {line}" for line in private_lines)
        lines.append("")

    claims = context["player_claims"]["marks"]
    if claims:
        lines.append("=== 玩家公开声明（不等于真实身份或系统确认） ===")
        for marks in claims:
            lines.append(f"第{marks['round']}轮 - {marks['seat']}号玩家：")
            claim_reason = C.REASON_LABELS.get(marks["reason"], marks["reason"])
            lines.append(f"  声称身份：{marks['identity']}（{claim_reason}）")
            for evaluation in marks["evaluations"]:
                eval_reason = C.REASON_LABELS.get(
                    evaluation["reason"], evaluation["reason"]
                )
                lines.append(
                    f"  评价：{evaluation['target_seat']}号玩家 = "
                    f"{evaluation['identity']}（{eval_reason}）"
                )
        lines.append("")

    return "\n".join(lines)


def _private_lines(private: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if private["teammates"]:
        seats = "、".join(f"{t['seat']}号玩家" for t in private["teammates"])
        lines.append(f"狼人队友：{seats}")
    for record in private["investigations"]:
        kind = "查验" if record["kind"] == "seer" else "验尸"
        side = "好人" if record["faction"] == C.GOOD else "狼人"
        lines.append(
            f"第{record['round']}轮{kind}：{record['target_seat']}号玩家 → {side}阵营"
        )
    witch = private["witch"]
    if witch:
        lines.append(f"解药：{'已使用' if witch['antidote_used'] else '未使用'}")
        lines.append(f"毒药：{'已使用' if witch['poison_used'] else '未使用'}")
        if witch["current_victim_seat"] is not None:
            lines.append(f"今夜被刀：{witch['current_victim_seat']}号玩家")
        for potion in witch["potion_history"]:
            name = "解药" if potion["potion"] == "antidote" else "毒药"
            target = (
                "无" if potion["target_seat"] is None else f"{potion['target_seat']}号玩家"
            )
            lines.append(f"第{potion['round']}轮用药：{name} → {target}")
    if private["last_guard_target_seat"] is not None:
        lines.append(f"上轮守护：{private['last_guard_target_seat']}号玩家（不可连守）")
    for attack in private["wolf_attacks"]:
        lines.append(f"第{attack['round']}轮刀人：{attack['target_seat']}号玩家")
    if private["hunter_can_shoot"] is not None:
        lines.append(
            f"开枪状态：{'可开枪' if private['hunter_can_shoot'] else '不可开枪（被毒死）'}"
        )
    if private["knight_duel_used"] is not None:
        lines.append(
            f"决斗状态：{'已使用' if private['knight_duel_used'] else '可决斗'}"
        )
    if private["fool_immunity_used"] is not None:
        lines.append(
            f"免疫状态：{'已使用' if private['fool_immunity_used'] else '未使用'}"
        )
    return lines
