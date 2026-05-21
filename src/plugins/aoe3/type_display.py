"""AoE3 兵种类型显示工具。

负责把 Unit.type 的原始标签列表过滤、翻译、去重，得到适合展示给玩家的中文列表。

设计原则（来自项目讨论 2026-05）：
1. 翻译层（i18n_zh.json type 表）保留 **完整字典**，所有 94 个 type 标签都有中文，
   便于搜索/调试/未来扩展。
2. 显示层从字典里 **挑出有展示价值的子集**。一个标签该显示，要么是
   "玩家能 get 的玩法大类"，要么是 "明确身份标识"，要么 "对克制系统有贡献"。
3. 两个调用方（`formatter.py` 兵种卡片 / `lineup.py:_type_str_zh` 斗蛐蛐阵容）
   共用本模块，保证显示口径一致。

参考决策记录：MEMORY 里 "斗蛐蛐：tag 显示不一致" 的相关讨论。
"""

from __future__ import annotations

from src.plugins.aoe3.i18n import t
from src.plugins.aoe3.models import Unit

# ---------------------------------------------------------------------------
# 显示时需要 skip 掉的 type 标签
# ---------------------------------------------------------------------------
# 把"该 skip 的标签"集中放这里，按理由分组便于维护。
TYPE_DISPLAY_SKIP: frozenset[str] = frozenset({
    # ---- 纯框架/逻辑分类（所有/绝大多数单位都有，纯噪音）----
    "Unit",
    "UnitClass",
    "Military",
    "Ranged",  # type 里的 Ranged 是"远程攻击"元属性，与卡片"🏹 远程攻击"区块重复
    "Herdable",
    "LogicalTypeLandMilitary",
    "LogicalTypeLandEconomy",

    # ---- 能力开关类（不是兵种身份，是行为标签）----
    "AbstractCanSeeStealth",
    "AbstractFindHealer",
    "AbstractFindScout",
    "AbstractCountAsGatherer",
    "AbstractDoubleVillager",
    "AbstractEmpowerer",
    "AbstractFreeBuilder",
    "AbstractMansabdar",

    # ---- 招募/机制来源标记（"从哪儿造的兵"，斗蛐蛐不关心）----
    "AbstractConsulateUnit",
    "AbstractConsulateUnitColonial",
    "AbstractConsulateSiegeIndustrial",
    "AbstractConsulateSiegeFortress",
    "AbstractBannerArmy",
    "AbstractBasilicaUnit",
    "AbstractTrainingShip",
    "AbstractFishingBoat",

    # ---- 时代/玩法模式标记（对 18 世纪殖民玩法无意义）----
    "AbstractArchaicInfantry",  # 古风步兵——共享加强卡用，显示无价值

    # ---- 极小众身份独占标签（一两个兵独占 + 不被克制系统引用）----
    # 这些标签既不是大类、也不参与 vs 克制，显示出来玩家也 get 不到。
    "AbstractAbusGun",
    "AbstractBerberNomad",
    "AbstractDacoit",
    "AbstractHowdah",
    "AbstractMahout",
    "AbstractMercFlailiphant",
    "AbstractGurkha",
    "AbstractRajput",
    "AbstractSepoy",
    "AbstractSowar",
    "AbstractUrumi",
    "AbstractZamburak",
    "AbstractWokou",
    "AbstractDaimyo",
    "AbstractPistolero",
    "AbstractCrossbowman",
    "AbstractIrregular",
    "AbstractBovine",
    "AbstractWagon",
})


def format_unit_types(unit: Unit) -> list[str]:
    """把 unit.type 转成展示用的中文标签列表（已过滤 + 翻译 + 去重，保持原顺序）。

    >>> # 假设 unit.type = ["Unit","UnitClass","AbstractInfantry","AbstractMusketeer","Military","Ranged"]
    >>> # 返回 ["步兵","火枪兵"]
    """
    seen: set[str] = set()
    result: list[str] = []
    for tag in unit.type:
        if tag in TYPE_DISPLAY_SKIP:
            continue
        zh = t("type", tag)
        if zh in seen:
            continue
        seen.add(zh)
        result.append(zh)
    return result
