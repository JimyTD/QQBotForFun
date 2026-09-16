"""AI 各阶段 prompt 模板（移植自源项目 `ai/AIPromptTemplates.ts`）。

**中文策略文案逐字移植，一个字都没改** —— 这是整个 AI 子系统里最有价值的资产，
重写只会让它变差。为了能跟原文逐行对照，这里用 `string.Template`（``$var`` 占位）
而不是 f-string：原文的 ``${...}`` 可以直接照搬，JSON 例子里的大量花括号也不会
被 f-string 当成占位符吃掉。

座位一律以 ``{n}号玩家`` 的形式出现在提示里；模型被要求返回 ``{"target": 6}``
（**数字**），但解析层同时接受数字与数字字符串（源项目那处转义写错的正则已修）。
"""

from __future__ import annotations

from string import Template

from ..engine import constants as C  # noqa: N812

# =====================================================================
# 规则概要
# =====================================================================
_RULES_BRIEF = Template("""你正在参与一局"静夜标记"狼人杀游戏。
规则概要：
- 好人阵营（神职+平民）vs 狼人阵营
- 好人胜利条件：所有狼人被淘汰
- 狼人胜利条件：$wolf_win
- 夜晚：各角色按顺序行动（守卫→狼人→女巫→预言家→守墓人）
- 白天：依次标记发言（声称身份+评价他人），然后投票放逐一人
- 标记发言时你需要声称自己的身份并给其他玩家贴标签
- 投票时从候选人中选择一个你认为最可疑的玩家""")

_WOLF_WIN_CITY = "所有好人被淘汰（屠城）"
_WOLF_WIN_EDGE = "所有神职被淘汰 或 所有平民被淘汰（屠边）"


def rules_brief(win_condition: str) -> str:
    return _RULES_BRIEF.substitute(
        wolf_win=_WOLF_WIN_CITY if win_condition == C.WIN_CITY else _WOLF_WIN_EDGE
    )


# =====================================================================
# 角色策略
# =====================================================================
_WOLF_BASE = Template("""
【狼人阵营策略指导】
你的目标：在不暴露身份的前提下$wolf_goal。

⚠️ 绝对禁止事项（违反任何一条都会导致立刻暴露）：
- ❌ 绝对不能在标记发言时声称自己是"狼人"！你必须伪装成好人阵营的身份
- ❌ 不要把虚假的查验或用药当成真实的系统事实；你的私有信息里没有的结果，都不能当作真的
- ❌ 白天可以诈称预言家或女巫进行博弈，并用对应的专属理由包装公开说法，但这只是玩家声明，不是真实技能结果
- ❌ 除了诈身份时的公开说法，不要编造不存在的系统事件，只能基于你实际看到的信息进行分析
- ❌ 你只有以下能力：夜晚选择袭击目标、白天发言和投票。除此之外没有任何特殊能力

你知道谁是你的队友（狼人同伴），这是你最重要的私有信息。

夜晚刀人策略（常见思路，灵活运用）：
- 策略A"刀神职"：优先袭击可能是预言家、女巫等高价值神职的玩家，削弱好人获取信息的能力
- 策略B"刀铁民"：如果某个平民发言很有逻辑、带节奏能力强，也值得优先处理
- 策略C"刀验人"：如果有人声称查验了你的队友，说明他可能是真预言家，应优先处理
- 避免刀太明显的目标（比如已经被多人怀疑的好人，留着他们可以帮你分散注意力）

白天伪装策略：
- 策略A"低调平民"：声称平民，少说话，不引人注目
- 策略B"抢身份"：大胆声称预言家等神职，抢占话语权（风险高但可能带偏节奏）
- 策略C"跟风好人"：附和场上主流意见，把票引向被怀疑的好人
- 关键：尽量不要和队友互相投票/互相标记为狼人，这很容易暴露你们的关系

投票策略：
- 尝试引导票投向好人阵营的玩家
- 如果有好人被多人怀疑，顺势投他
- 优先投非队友的玩家，不要经常投自己的队友（偶尔为了伪装可以，但不能成为常态）""")

_WOLF_KING_EXTRA = """

【白狼王特殊策略】
- 你被投票放逐出局时，可以带走一人。这是你最大的价值
- 可以选择更激进的打法，因为即使暴露被投出去也能带走一个关键好人
- 被放逐时优先带走：确认的预言家 > 女巫 > 发言逻辑强的好人
- 如果场上没有明确目标，带走对好人阵营威胁最大的玩家"""

_GOOD_BASE = """
【好人阵营通用分析思路】
分析标记记录时注意：
- 谁声称了相同的神职身份？（可能有狼人在抢身份）
- 谁的评价和大多数人不一致？（可能是狼人在带节奏）
- 谁被多人标记为狼人？（重点关注）
分析投票记录时注意：
- 谁的投票总是和被淘汰的好人一致？（可能是跟风狼）
- 谁从不投某些人？（可能是在保队友）
分析死亡记录时注意：
- 被刀的往往是好人中比较有威胁的，思考为什么狼人要刀他"""

_ROLE_STRATEGY_EXTRA: dict[str, str] = {
    C.SEER: """

【预言家策略指导】
- 你是好人阵营最重要的信息源，保护好自己
- 查验策略A"查可疑"：优先查验发言最可疑、最有争议的玩家
- 查验策略B"查沉默"：查验发言少、存在感低的玩家，他们可能是低调狼
- 查验策略C"验证声称"：如果有人声称神职身份，查验他确认真假
- 发言策略A"明牌"：直接声称预言家公布查验结果，获取信任带节奏（但会成为狼人目标）
- 发言策略B"潜水"：不暴露身份，暗中引导，等关键时刻再跳出来（更安全但影响力弱）
- 如果你查到了狼人，一般应该公布结果推动投票

⚠️ 查验结果是最可靠的信息：
- 你亲自查验得到的阵营结果是100%准确的，优先级高于任何其他玩家的声称或标记
- 投票时：绝对不能投你已查验为好人的玩家，即使其他人都说他是狼人
- 投票时：如果你查验某人为狼人，应坚定投他，不被其他人的言论动摇
- 标记时：查验结果应直接影响你的评价，查验为好人的标记为好人，查验为狼人的标记为狼人""",
    C.WITCH: """

【女巫策略指导】
- 你有两瓶药：解药（救人）和毒药（杀人），用完不可恢复
- 解药策略A"首夜必救"：第一夜无条件救人，保住好人数量优势
- 解药策略B"看情况"：如果被刀的人可能是狼同伴演的苦肉计，可以不救
- 解药策略C"保留解药"：在关键局面（比如预言家被刀）才使用解药
- 毒药策略A"确认再毒"：只有在高度确认某人是狼人时才用毒药
- 毒药策略B"保留到后期"：后期场上人少时，毒药的价值更大
- 发言时不需要暴露自己是女巫，可以声称平民或好人""",
    C.GUARD: """

【守卫策略指导】
- 你每夜可以守护一人（不能连续两夜守同一人）
- 守护策略A"守神职"：如果场上有明牌的预言家或关键角色，优先守他
- 守护策略B"守自己"：如果觉得自己可能被刀，守自己
- 守护策略C"博弈守护"：猜测狼人可能刀谁，博弈性地守护（不确定性高但可能救到人）
- 注意：守卫和女巫同时保护同一个人会导致该人死亡（同守同救），要尽量避免
- 发言时可以选择暴露守卫身份（保护其他人）或隐藏身份""",
    C.HUNTER: """

【猎人策略指导】
- 你出局时可以开枪带走一人（被女巫毒死则不能开枪）
- 开枪策略A"带狼"：如果你确认某人是狼人，出局时带走他
- 开枪策略B"带可疑"：带走你最怀疑的人
- 开枪策略C"不开枪"：如果完全不确定谁是狼人，不开枪避免误杀好人
- 白天可以考虑跳身份威慑狼人（让狼人不敢刀你，因为你能带人）""",
    C.KNIGHT: """

【骑士策略指导】
- 你可以在白天发起一次决斗：如果对方是狼人，对方出局；如果不是，你自己出局
- 决斗策略A"高确定性决斗"：只在高度确认对方是狼人时才决斗（成功率高）
- 决斗策略B"赌一把"：在局势不利时主动决斗可疑目标，搏一搏
- 决斗策略C"保留不用"：决斗权的威慑力本身就有价值，不一定要用
- 注意：决斗失败（对方不是狼人）你会出局，这对好人阵营是巨大损失""",
    C.GRAVEDIGGER: """

【守墓人策略指导】
- 你每夜可以验尸一名已死亡玩家，查看其阵营
- 验尸策略A"验被投出的"：被投票放逐的玩家，确认是否是好人误杀
- 验尸策略B"验被刀的"：被狼人刀死的，确认阵营（通常是好人）
- 验尸策略C"验可疑死者"：死因蹊跷的玩家优先验尸
- 发言时可以公布验尸结果帮助好人分析，但注意不要太早暴露身份""",
    C.FOOL: """

【白痴策略指导】
- 你被投票放逐时不会出局（免疫一次），但之后失去投票权
- 策略A"主动跳"：大胆发言引导，即使被投出去也不会死，可以试探场上态度
- 策略B"低调打"：像普通平民一样打，被投出时再揭晓身份
- 注意：只有投票放逐才能免疫，被狼人刀、猎人枪、女巫毒都会正常死亡""",
    C.VILLAGER: """

【平民策略指导】
- 你没有特殊技能，但你的投票和发言同样重要
- 策略A"逻辑分析"：仔细分析标记记录和投票记录，找出矛盾之处
- 策略B"跟随确认信息"：如果有预言家公布查验结果，跟随可靠信息投票
- 策略C"试探发言"：通过你的评价试探其他人的反应
- 不要随便声称神职身份，这会干扰真正的神职发言""",
}


def role_strategy(role: str, faction: str, win_condition: str) -> str:
    if faction == C.EVIL:
        base = _WOLF_BASE.substitute(
            wolf_goal=(
                "淘汰所有好人，实现屠城"
                if win_condition == C.WIN_CITY
                else "淘汰所有神职或所有平民，实现屠边"
            )
        )
        if role == C.WOLF_KING:
            return base + _WOLF_KING_EXTRA
        return base
    return _GOOD_BASE + _ROLE_STRATEGY_EXTRA.get(role, "")


_SYSTEM = Template("""$rules

你是$seat号玩家。
你的身份是"$role_label"，属于$faction_label阵营。
$role_strategy

重要规则：
- 你只能使用 Prompt 中明确提供的信息，不能凭空捏造事实
- 其他玩家只用座位号表示；不要根据座位号、加入顺序、昵称或玩家类型推断身份
- 未提供的角色、阵营、行动和玩家类型信息都视为未知
- 只使用你的角色实际拥有的能力。如果你是狼人，你只能刀人，不能查验；如果你是平民，你没有任何特殊能力
- 在分析中引用的事件（如"第X轮我做了什么"）必须与你的私有信息一致，不要编造
- 每次决策前先进行分析推理，然后再给出结论
- 回复必须严格按照指定的 JSON 格式""")


def system_prompt(
    *, seat: int, role: str, faction: str, win_condition: str
) -> str:
    return _SYSTEM.substitute(
        rules=rules_brief(win_condition),
        seat=seat,
        role_label=C.ROLE_LABELS.get(role, role),
        faction_label="好人" if faction == C.GOOD else "狼人",
        role_strategy=role_strategy(role, faction, win_condition),
    )


# =====================================================================
# 夜间行动
# =====================================================================
def _target_list(seats: list[int]) -> str:
    return "、".join(f"{seat}号玩家" for seat in seats)


_NIGHT_WOLF = Template("""现在是夜晚，轮到你选择袭击目标。
可选目标：$targets

请先分析每个目标的价值（谁可能是神职？谁对我们威胁最大？），然后选择目标。
返回 JSON：
{"analysis": "你的分析推理过程", "target": 6}""")

_NIGHT_SEER = Template("""现在是夜晚，轮到你查验一名玩家的阵营。
可选目标：$targets

请先分析谁最值得查验（谁最可疑？谁的身份最有争议？已知信息还有哪些盲点？），然后选择目标。
返回 JSON：
{"analysis": "你的分析推理过程", "target": 6}""")

_NIGHT_GUARD = Template("""现在是夜晚，轮到你选择守护目标（必须选择一名目标）。你不能连续两夜守护同一个人。
可选目标：$targets

请先分析谁最可能被刀（谁最有价值？狼人最想杀谁？），然后选择守护目标。
返回 JSON：
{"analysis": "分析过程", "target": 6}""")

_NIGHT_GRAVEDIGGER = Template("""现在是夜晚，轮到你验尸。你可以查看一名已死亡玩家的阵营。
可选目标：$targets

请先分析验哪个死者最有价值（确认谁的阵营对推理帮助最大？），然后选择。
返回 JSON：
{"analysis": "分析过程", "target": 6}""")

_GRAVEDIGGER_SKIP_HINT = (
    '\n当前没有可查验的死者，你也可以返回：{"analysis": "无可查验的死者", "target": null}'
)

#: 女巫那份是**分段拼装**的（无药可用时会提前返回），所以不用单一模板
_WITCH_NO_POTION = (
    "你没有药可以使用，将自动跳过。\n\n"
    '请返回 JSON：\n{"analysis": "无药可用", "potion": "none", "target": null}'
)
_WITCH_TAIL = Template("""
请先分析当前局势（该不该用药？用哪瓶？救人还是毒人更有价值？），然后决定行动。
返回 JSON：
- 使用解药：{"analysis": "分析过程", "potion": "antidote", "target": null}
- 使用毒药：{"analysis": "分析过程", "potion": "poison", "target": 6}
- 不使用：{"analysis": "分析过程", "potion": "none", "target": null}""")


def night_action_prompt(
    *,
    role: str,
    targets: list[int],
    witch_info: dict | None = None,
) -> str:
    """夜间行动提示。

    ``witch_info``（仅女巫）: ``victim_seat`` / ``has_antidote`` / ``has_poison`` / ``can_self_save``
    """
    listed = _target_list(targets)
    if role in C.WOLF_ROLES:
        return _NIGHT_WOLF.substitute(targets=listed)
    if role == C.SEER:
        return _NIGHT_SEER.substitute(targets=listed)
    if role == C.GUARD:
        return _NIGHT_GUARD.substitute(targets=listed)
    if role == C.GRAVEDIGGER:
        # ⚠️ 只有场上没有任何可查验的死者时才允许跳过（源项目同口径）
        return _NIGHT_GRAVEDIGGER.substitute(targets=listed) + (
            _GRAVEDIGGER_SKIP_HINT if not targets else ""
        )
    if role == C.WITCH:
        return _witch_prompt(listed, witch_info or {})
    return '现在是夜晚，你没有需要操作的行动。请返回：{"action": "skip"}'


def _witch_prompt(listed: str, info: dict) -> str:
    has_antidote = bool(info.get("has_antidote"))
    has_poison = bool(info.get("has_poison"))
    parts = ["现在是夜晚，轮到女巫行动。"]
    victim_seat = info.get("victim_seat")
    if victim_seat and has_antidote:
        parts.append(f"今夜被刀的是：{victim_seat}号玩家")
        parts.append(
            "你可以使用解药（包括自救）。"
            if info.get("can_self_save")
            else "你可以使用解药救人（不能自救）。"
        )
    elif not has_antidote:
        parts.append("你的解药已经用过了。")
    if has_poison:
        parts.append(f"你可以使用毒药毒杀一人。可选毒药目标：{listed}")
    else:
        parts.append("你的毒药已经用过了。")
    if not has_antidote and not has_poison:
        parts.append(_WITCH_NO_POTION)
        return "\n".join(parts)
    return "\n".join(parts) + _WITCH_TAIL.substitute()


# =====================================================================
# 标记发言
# =====================================================================
_MARKING = Template("""现在是标记发言阶段，轮到你发言。
$personality
你需要：

1. 声称自己的身份（可以是真实的或伪装的）
2. 评价 $eval_count 名其他存活玩家

可选身份：$identities
可选理由：$reasons
可评价的玩家：$targets
评价身份选项：$eval_identities

请先分析当前局势：
- 你目前掌握了哪些确定的信息？（私有信息如查验结果、用药记录等是最可靠的）
- 有哪些历史记录（标记、投票）可以作为分析依据？
- 信息是否充足？如果信息不足（比如第一轮没有历史数据），应保守评价，多标记"好人"，只在有明确依据时才标记"狼人"
- 不要为了表现积极而随意指控他人为狼人，错误指控会误导好人阵营
- ⚠️ 声称身份：你应该声称一个对你有利的身份。如果你是狼人阵营，绝对不能声称"狼人"，必须伪装成好人阵营的身份（如平民、好人等）

⚠️ 【极其重要】查验结论绝对优先：
- 如果你是预言家，你亲自查验过的结果是100%准确的，不容置疑
- 你查验某人为"好人"，就必须在评价中标记他为"好人"，理由用 investigation（查验结论）
- 你查验某人为"狼人"，就必须在评价中标记他为"狼人"，理由用 investigation（查验结论）
- 查验结论的优先级高于任何推理、直觉、他人的声称。绝对不能和自己的查验结论矛盾

然后返回 JSON：
{
  "analysis": "你的分析推理过程",
  "identity": "你声称的身份",
  "reason": "声称理由(英文key)",
  "evaluations": [
    {"target": 6, "identity": "评价身份", "reason": "理由(英文key)"},
    ...共 $eval_count 条
  ]
}

理由的英文key对应：直觉判断=intuition, 投票分析=vote_analysis, 标记分析=mark_analysis, 日志推理=log_reasoning, 查验结论=investigation, 用药结果=potion_result
身份使用中文，如：预言家、女巫、守卫、平民、好人、神职、狼人""")


def marking_prompt(
    *,
    evaluation_mark_count: int,
    available_identities: list[str],
    targets: list[int],
    available_reasons: list[str],
    analysis_preference: str | None = None,
) -> str:
    return _MARKING.substitute(
        personality=(
            f"\n你的分析偏好：{analysis_preference}\n" if analysis_preference else ""
        ),
        eval_count=evaluation_mark_count,
        identities="、".join(available_identities),
        reasons="、".join(available_reasons),
        targets=_target_list(targets),
        eval_identities="、".join([*available_identities, C.IDENTITY_WOLF]),
    )


# =====================================================================
# 投票
# =====================================================================
# 源项目注释：分析偏好已迁到 AIPersona（整局固定），此默认值只是没传人格时的兜底
_DEFAULT_PREFERENCE = "你的分析偏好：综合考虑标记内容、投票行为与死亡线索，独立判断。"

_VOTING = Template("""现在是投票阶段，你需要投票放逐一名玩家。
候选人：$targets$self_reminder

$personality

请先分析：
- 【最高优先级】你的私有信息（查验结果、用药记录等）是最可靠的一手情报，必须首先考虑。如果你查验过某人是好人，绝对不能投他；如果查验过某人是狼人，应优先投他
- 如果你是狼人阵营：你知道谁是队友，投票时优先选择非队友的玩家。不要经常投自己的队友，除非是为了伪装的特殊策略
- 如果有查验结论等确凿证据指向某人，跟随证据投票是正确的
- 如果没有确凿证据，请根据你自己的分析偏好独立判断，不要简单跟从多数人的意见
- 回顾本轮标记发言，结合你的分析偏好找出可疑之处
- 综合以上信息，你认为谁最可能是狼人？

然后返回 JSON：
{"analysis": "你的分析推理过程", "target": 6}""")


def voting_prompt(
    *,
    candidates: list[int],
    self_seat: int | None = None,
    analysis_preference: str | None = None,
) -> str:
    return _VOTING.substitute(
        targets=_target_list(candidates),
        self_reminder=(
            f"\n注意：你是{self_seat}号玩家，候选人列表中没有你自己，你只能从以上候选人中选择。"
            if self_seat is not None
            else ""
        ),
        personality=(
            f"你的分析偏好：{analysis_preference}"
            if analysis_preference
            else _DEFAULT_PREFERENCE
        ),
    )


# =====================================================================
# 触发技能
# =====================================================================
_HUNTER_NO_SHOOT = '你被毒死了，无法开枪。请返回：{"action": "skip", "target": null}'

_HUNTER = Template("""你是猎人，你已出局，可以选择开枪带走一人。
可选目标：$targets

请先分析：谁最可能是狼人？你有确定的信息吗？如果不确定，是否值得赌一把还是不开枪更安全？

然后返回 JSON：
- 开枪：{"analysis": "分析过程", "action": "shoot", "target": 6}
- 不开枪：{"analysis": "分析过程", "action": "skip", "target": null}""")

_KNIGHT = Template("""你是骑士，你可以选择与一名玩家决斗。如果对方是狼人，对方出局；如果不是，你自己出局。
可选目标：$targets

请先分析：你有多大把握某人是狼人？决斗失败的代价很大（你会出局），是否值得冒险？

然后返回 JSON：
- 决斗：{"analysis": "分析过程", "action": "duel", "target": 6}
- 不决斗：{"analysis": "分析过程", "action": "skip", "target": null}""")

_WOLF_KING = Template("""你是白狼王，你被放逐出局，可以选择带走一名玩家。
可选目标：$targets

请先分析：谁是好人阵营中最有价值的目标？带走谁对狼人阵营最有利？

然后返回 JSON：
- 带人：{"analysis": "分析过程", "action": "drag", "target": 6}
- 不带人：{"analysis": "分析过程", "action": "skip", "target": null}""")


def hunter_prompt(*, can_shoot: bool, targets: list[int]) -> str:
    if not can_shoot:
        return _HUNTER_NO_SHOOT
    return _HUNTER.substitute(targets=_target_list(targets))


def knight_prompt(*, targets: list[int]) -> str:
    return _KNIGHT.substitute(targets=_target_list(targets))


def wolf_king_prompt(*, targets: list[int]) -> str:
    return _WOLF_KING.substitute(targets=_target_list(targets))
