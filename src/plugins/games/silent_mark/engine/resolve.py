"""静夜标记 · 结算与校验。

逐条转写自源项目 ``server/game/rules.ts``、``shared/validators.ts``，
以及 ``GameManager.handleSubmitMarks`` 中的标记合法性校验部分。

本模块是**服务端权威**：任何玩家动作（含 AI）最终都必须经过这里的校验。
"""

from __future__ import annotations

import random
from typing import Any

# 常量模块用短别名 C：本文件高频引用，长名会明显拖长行
from . import constants as C  # noqa: N812
from .types import (
    DeathRecordDict,
    GameStateDict,
    ItemDict,
    PlayerDict,
    PlayerMarksDict,
    VoteRecordDict,
)


# =====================================================================
# 胜负判定
# =====================================================================
def check_win_condition(
    state: GameStateDict, win_condition: str = C.WIN_EDGE
) -> dict[str, str] | None:
    """胜负判定。返回 ``{"winner": ..., "reason": ...}`` 或 None（游戏继续）。

    - 好人胜：所有狼人出局；
    - 狼人胜（两种模式共有）：所有好人出局（屠城语义，见下方说明）；
    - 狼人胜（仅屠边 ``edge``）：所有神职出局，或所有平民出局。

    ⚠️ 两条与源项目**同步修正**过的防御（源项目已在 502ef26 修复同类问题）：

    1. **"某一类全灭"只在板子里真的存在该类角色时才成立**。
       否则「1 狼 + 3 平民 + 屠边」这种板子会在首夜结算后立刻判狼人胜
       （"神职全灭"开局即成立，甚至无人死亡）。
    2. **"所有好人出局"不再只属于屠城**。若不加这条，屠边模式下"好人全灭"
       会两个条件都不满足而返回 None（真正的死局：场上只剩狼，游戏不结束）。
       正常的屠边局会在更早的时刻由屠边条件结束，所以这条只是防死局。
    """
    alive = [p for p in state["players"] if p["alive"]]
    alive_wolves = [p for p in alive if p["faction"] == C.EVIL]
    alive_good = [p for p in alive if p["faction"] == C.GOOD]

    if not alive_wolves:
        return {"winner": C.GOOD, "reason": "wolves_eliminated"}

    if not alive_good:
        return {"winner": C.EVIL, "reason": "good_eliminated"}

    if win_condition != C.WIN_CITY:
        board_roles = {p["role"] for p in state["players"]}
        alive_villagers = [p for p in alive if p["role"] == C.VILLAGER]
        alive_specials = [p for p in alive_good if p["role"] in C.SPECIAL_ROLES]

        # 只有当该类别**在板子里存在**时，"该类全灭"才构成屠边
        # 判断顺序与源项目 502ef26 的最终形态**逐字对齐**（神职在前、平民在后）。
        # 这两个条件不可能同时成立：能走到这里说明 alive_good > 0，
        # 而每个好人角色要么是神职、要么是平民，所以至多有一类"全灭"。
        if board_roles & C.SPECIAL_ROLES and not alive_specials:
            return {"winner": C.EVIL, "reason": "specials_eliminated"}
        if C.VILLAGER in board_roles and not alive_villagers:
            return {"winner": C.EVIL, "reason": "villagers_eliminated"}

    return None


# =====================================================================
# 夜晚结算
# =====================================================================
def resolve_night(state: GameStateDict) -> list[DeathRecordDict]:
    """结算一夜。返回本夜死亡列表，并就地执行死亡（关 alive、公开遗物）。

    结算顺序（源项目规则）：

    1. 狼人袭击：被守 → 存活；被解药救 → 存活；**同守同救 → 死亡**；
    2. 女巫毒药：无视守护，直接死亡（已在死亡列表里的不重复记）；
    3. 更新月光石（"被夜间行动造访"计数）；
    4. 应用死亡并把物品公开为遗物。
    """
    deaths: list[DeathRecordDict] = []
    night = state["night_actions"]
    round_no = state["round"]

    wolves = night.get("wolves")
    wolf_target = wolves.get("target") if wolves else None
    guard = night.get("guard")
    guard_target = guard.get("target") if guard else None
    witch = night.get("witch")
    witch_action = witch.get("action") if witch else "none"
    witch_target = witch.get("target") if witch else None

    if wolf_target:
        victim = _find(state, wolf_target)
        if victim is not None:
            guarded = guard_target == wolf_target
            saved = witch_action == "antidote"

            if guarded and saved:
                # 同守同救 → 同归于尽，**只记一条** guardWitchClash。
                #
                # 源项目原本会记两条（第一个 if 漏写 else，把两个标志清成 false 后
                # 紧接着又记一条 attacked），导致同一玩家重复公告、重复进入死亡触发链。
                # 源项目已在 502ef26 改成 else if 结构，与本实现一致 ——
                # 两边口径**已对齐**，这里不再是"有意差异"。
                deaths.append(_new_death(victim, C.DEATH_GUARD_WITCH_CLASH, round_no))
            elif not guarded and not saved:
                deaths.append(_new_death(victim, C.DEATH_ATTACKED, round_no))

    if witch_action == "poison" and witch_target:
        poisoned = _find(state, witch_target)
        if (
            poisoned is not None
            and poisoned["alive"]
            and not any(d["pid"] == witch_target for d in deaths)
        ):
            deaths.append(_new_death(poisoned, C.DEATH_POISONED, round_no))

    _update_moonstone(state)

    for death in deaths:
        player = _find(state, death["pid"])
        if player is None:
            continue
        death["relics"] = record_death(state, player, death["cause"])["relics"]

    return deaths


def record_death(
    state: GameStateDict, player: PlayerDict, cause: str
) -> DeathRecordDict:
    """统一的出局处理：关 ``alive``、公开遗物、生成死亡记录。

    **不**写入 ``history["deaths"]``（由调用方负责 append，与源项目分工一致）。

    ⚠️ 所有出局路径（夜晚结算 / 放逐 / 触发链 / 骑士决斗 / 认输）都必须走这里。
    源项目 502ef26 修的正是"认输路径漏公开遗物"——那类漏洞的根因就是多条出局路径
    各写一遍。以后加新出局方式（遗言、猎犬哨快照等）也只改这一处。
    """
    player["alive"] = False
    for item in player["items"]:
        item["revealed"] = True

    # 猎犬哨快照：**出局那一刻**场上还剩几只狼（此刻自己的 alive 已置 false，
    # 所以死者是狼时不会把自己算进去）。
    # 源项目只在客户端标签里承诺了这条信息（"场上存活 N 只狼"），服务端从未赋值，
    # 于是它永远显示空值——语义在这里定下来，并由 `record_death` 这个唯一出局出口保证。
    alive_wolves = sum(
        1 for p in state["players"] if p["alive"] and p["faction"] == C.EVIL
    )
    for item in player["items"]:
        if item["type"] == C.HOUND_WHISTLE:
            item["value"] = alive_wolves
    return {
        "pid": player["pid"],
        "seat": player["seat"],
        "cause": cause,
        "round": state["round"],
        "relics": [dict(item) for item in player["items"]],
    }


def _update_moonstone(state: GameStateDict) -> None:
    """更新月光石计数。

    源项目用**集合**去重，所以是「该玩家今夜是否被任何夜间行动造访」——一夜最多 +1，
    即使被刀同时被查验也只 +1（与设计文档的"每次 +1"措辞不同，以代码行为为准）。
    """
    night = state["night_actions"]
    visited: set[str] = set()

    wolves = night.get("wolves")
    if wolves and wolves.get("target"):
        visited.add(wolves["target"])
    guard = night.get("guard")
    if guard and guard.get("target"):
        visited.add(guard["target"])
    seer = night.get("seer")
    if seer and seer.get("target"):
        visited.add(seer["target"])
    witch = night.get("witch")
    if witch and witch.get("target") and witch.get("action") != "none":
        visited.add(witch["target"])

    for pid in visited:
        player = _find(state, pid)
        if player is None:
            continue
        for item in player["items"]:
            if item["type"] == C.MOONSTONE and isinstance(item["value"], int):
                item["value"] += 1


def _new_death(player: PlayerDict, cause: str, round_no: int) -> DeathRecordDict:
    return {
        "pid": player["pid"],
        "seat": player["seat"],
        "cause": cause,
        "round": round_no,
        "relics": [],
    }


def _find(state: GameStateDict, pid: str | None) -> PlayerDict | None:
    if not pid:
        return None
    for player in state["players"]:
        if player["pid"] == pid:
            return player
    return None


# =====================================================================
# 投票结算
# =====================================================================
def resolve_voting(votes: list[VoteRecordDict]) -> dict[str, Any]:
    """放逐投票结算。返回 ``{"exiled": pid | None, "tie": bool}``。

    得票最高者被放逐；**平票则无人出局**；无票也无人出局。
    """
    if not votes:
        return {"exiled": None, "tie": False}

    counts: dict[str, int] = {}
    for vote in votes:
        counts[vote["target"]] = counts.get(vote["target"], 0) + 1

    best: list[str] = []
    max_votes = 0
    for target, count in counts.items():
        if count > max_votes:
            max_votes = count
            best = [target]
        elif count == max_votes:
            best.append(target)

    if len(best) > 1:
        return {"exiled": None, "tie": True}
    return {"exiled": best[0], "tie": False}


# =====================================================================
# 标记：数量与选项
# =====================================================================
def get_evaluation_mark_count(alive_count: int) -> int:
    """评价标记数量随存活人数动态调整：4~6 人 2 个 / 7~9 人 3 个 / 10 人以上 4 个。"""
    if alive_count >= 10:
        return 4
    if alive_count >= 7:
        return 3
    return 2


def get_available_identities(state: GameStateDict) -> list[str]:
    """身份声明可选的身份标签。

    固定两项「神职」「好人」，再按**当局参与的职业**动态追加。
    顺序与源项目一致，改动即视为改产品行为。
    """
    identities = [C.IDENTITY_ROLE_FIRST, C.IDENTITY_GOOD]
    roles_in_game = {p["role"] for p in state["players"]}
    for label, role in C.IDENTITY_TO_ROLE.items():
        if role in roles_in_game:
            identities.append(label)
    return identities


def get_available_eval_identities(state: GameStateDict) -> list[str]:
    """评价标记可选的身份标签（比身份声明多一个「狼人」）。"""
    return [*get_available_identities(state), C.IDENTITY_WOLF]


def is_mark_reason_allowed_for_identity(identity: str, reason: str) -> bool:
    """标记理由是否与**公开声明的身份**匹配。

    玩家可以诈身份；特殊理由只要求声明的身份匹配，**不校验真实职业**。
    """
    if reason in C.COMMON_REASONS:
        return True
    if reason == C.REASON_INVESTIGATION:
        return identity in C.INVESTIGATION_IDENTITIES
    if reason == C.REASON_POTION_RESULT:
        return identity in C.POTION_IDENTITIES
    return False


def validate_player_marks(
    state: GameStateDict, pid: str, marks: PlayerMarksDict
) -> list[str]:
    """校验一次标记提交是否合法。返回问题列表（空列表 = 合法）。

    返回多条而不是单条，是为了 QQ 侧能给玩家一条**可操作的纠错提示**
    （计划 §4.3：解析/校验失败要说明错在哪）。

    判定口径与源项目 ``GameManager.handleSubmitMarks`` 一致（**合法性结论等价**）。
    唯一的实现差异：源项目遇到第一个问题就 ``return false``，
    本实现会把所有问题一次列全，只为让纠错文案更完整。
    """
    problems: list[str] = []

    if state["phase"] != C.PHASE_DAY_MARKING:
        return [f"当前不是标记阶段（phase={state['phase']}）"]

    order = state["marking_order"]
    current = state["marking_current"]
    if current >= len(order) or order[current] != pid:
        who = order[current] if current < len(order) else "（无）"
        return [f"还没轮到你发言，当前轮到 {who}"]

    identity_mark = marks["identity_mark"]
    available = get_available_identities(state)
    if identity_mark["identity"] not in available:
        problems.append(
            f"身份「{identity_mark['identity']}」不在可选范围：{'、'.join(available)}"
        )
    if not is_mark_reason_allowed_for_identity(
        identity_mark["identity"], identity_mark["reason"]
    ):
        problems.append(
            f"理由「{C.REASON_LABELS.get(identity_mark['reason'], identity_mark['reason'])}」"
            f"不能用于你声明的身份「{identity_mark['identity']}」"
        )

    alive_count = len([p for p in state["players"] if p["alive"]])
    max_eval = get_evaluation_mark_count(alive_count)
    evaluations = marks["evaluation_marks"]
    if len(evaluations) > max_eval:
        problems.append(f"评价标记最多 {max_eval} 个，收到 {len(evaluations)} 个")

    eval_identities = set(get_available_eval_identities(state))
    seen: set[str] = set()
    for mark in evaluations:
        target = _find(state, mark["target"])
        if target is None:
            problems.append(f"评价目标不存在：{mark['target']}")
            continue
        if not target["alive"]:
            problems.append(f"{target['seat']} 号已出局，不能评价")
        if target["pid"] == pid:
            problems.append("不能评价自己")
        if target["pid"] in seen:
            problems.append(f"{target['seat']} 号被评价了两次")
        if mark["identity"] not in eval_identities:
            problems.append(
                f"评价身份「{mark['identity']}」不在可选范围："
                f"{'、'.join(sorted(eval_identities))}"
            )
        if not is_mark_reason_allowed_for_identity(
            identity_mark["identity"], mark["reason"]
        ):
            problems.append(
                f"{target['seat']} 号的理由「"
                f"{C.REASON_LABELS.get(mark['reason'], mark['reason'])}」"
                f"与声明身份「{identity_mark['identity']}」不符"
            )
        seen.add(target["pid"])

    return problems


# =====================================================================
# 房间配置校验
# =====================================================================
def get_roles_from_settings(settings: dict[str, Any]) -> list[str]:
    """把配置摊平成角色列表（每个角色按数量重复）。"""
    roles: list[str] = []
    for role, count in _role_config(settings).items():
        roles.extend([role] * int(count))
    return roles


def get_total_players_from_settings(settings: dict[str, Any]) -> int:
    return sum(int(v) for v in _role_config(settings).values())


def validate_game_settings(settings: dict[str, Any]) -> tuple[bool, str]:
    """校验房间配置合法性。返回 ``(是否合法, 错误文案)``。

    规则（源项目 ``shared/validators.ts``，含 502ef26 同步的一层补充）：
    人数 4~12、至少 1 个狼人、好人数量必须多于狼人、角色名必须已知、数量必须是非负整数，
    以及**屠边模式下神职与平民都必须存在**（否则"某一类全灭"开局即成立）。
    """
    if settings.get("mode") == "preset":
        preset = settings.get("preset")
        if not preset or preset not in C.PRESETS:
            return False, "无效的预设模板"

    roles = _role_config(settings)
    total = sum(int(v) for v in roles.values())

    if total < C.MIN_PLAYERS:
        return False, f"总人数不能少于 {C.MIN_PLAYERS} 人"
    if total > C.MAX_PLAYERS:
        return False, f"总人数不能超过 {C.MAX_PLAYERS} 人"

    wolf_count = int(roles.get(C.WEREWOLF, 0)) + int(roles.get(C.WOLF_KING, 0))
    if wolf_count < 1:
        return False, "至少需要 1 个狼人"

    good_count = total - wolf_count
    if good_count <= wolf_count:
        return False, "好人数量必须多于狼人数量"

    for role, count in roles.items():
        if role not in C.ROLE_FACTION:
            return False, f"未知角色：{role}"
        # 排除 bool（Python 里 bool 是 int 的子类）
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return False, f"角色数量不合法：{role}"

    # 屠边模式必须两类角色都存在。否则「1 狼 + 3 平民 + 屠边」会让"神职全灭"
    # 在开局就成立，首夜结算后直接判狼人胜（甚至无人死亡）。
    # 这一层必须放在角色名/数量校验之后，保证「未知角色」等更基础的错误先被报出来。
    if _win_condition_of(settings) != C.WIN_CITY:
        if not any(role in C.SPECIAL_ROLES for role in roles):
            return False, "屠边模式至少需要 1 个神职"
        if C.VILLAGER not in roles:
            return False, "屠边模式至少需要 1 个平民"

    return True, ""


def _role_config(settings: dict[str, Any]) -> dict[str, Any]:
    """取出生效的角色配置：预设板子优先，否则用自定义 roles。"""
    if settings.get("mode") == "preset":
        preset = settings.get("preset")
        config = C.PRESETS.get(preset) if preset else None
        return dict(config.roles) if config else {}
    return dict(settings.get("roles") or {})


def _win_condition_of(settings: dict[str, Any]) -> str:
    """取出生效的胜负条件：预设板子自带，自定义板子读 settings。"""
    if settings.get("mode") == "preset":
        preset = settings.get("preset")
        config = C.PRESETS.get(preset) if preset else None
        if config is not None:
            return config.win_condition
    return settings.get("win_condition") or C.WIN_EDGE


# =====================================================================
# 物品
# =====================================================================
def assign_items(
    settings: dict[str, Any], rng: random.Random | None = None
) -> list[ItemDict]:
    """开局随机分配一件随身物品（源项目 ``GameManager.assignItems``）。

    存活时玩家只知道类型、看不到内容（``revealed=False``）；
    天平徽章的 ``value`` 由 ``calculate_balance_badges`` 在座位确定后填。
    """
    items_cfg = settings.get("items") or {}
    if not items_cfg.get("enabled"):
        return []

    # ⚠️ 不能写成 `items_cfg.get("pool") or BASIC_ITEM_POOL`：
    # Python 里空列表是 falsy，会把"房主清空了物品池"误解成"用默认池"。
    # 源项目（JS）的 `||` 则把 [] 当 truthy，于是会写出 type=undefined 的物品——
    # 两种都不对，这里明确取"空池 = 不发物品"。
    pool_cfg = items_cfg.get("pool")
    pool = list(C.BASIC_ITEM_POOL) if pool_cfg is None else list(pool_cfg)
    if not pool:
        return []

    rand = rng or random
    item_type = rand.choice(pool)
    return [
        {
            "type": item_type,
            "value": 0 if item_type == C.MOONSTONE else "",
            "revealed": False,
        }
    ]


def calculate_balance_badges(players: list[PlayerDict]) -> None:
    """计算天平徽章：左右邻座是否同阵营（开局定死，按原始座位环形计算）。

    同阵营 → ``balanced``；不同阵营 → ``unbalanced``。
    """
    ordered = sorted(players, key=lambda p: p["seat"])
    count = len(ordered)
    if count == 0:
        return

    index_of = {p["pid"]: i for i, p in enumerate(ordered)}
    for player in players:
        for item in player["items"]:
            if item["type"] != C.BALANCE:
                continue
            i = index_of[player["pid"]]
            left = ordered[(i - 1) % count]["faction"]
            right = ordered[(i + 1) % count]["faction"]
            item["value"] = "balanced" if left == right else "unbalanced"
