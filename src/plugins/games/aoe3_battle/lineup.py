"""AoE3 斗蛐蛐 —— 阵容生成器。

负责兵种池筛选、随机抽取、数量计算。

设计文档：docs/games/aoe3-battle.md §二
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Sequence

from src.plugins.aoe3.formatter import append_unit_tooltip
from src.plugins.aoe3.models import Unit
from src.plugins.aoe3.repository import UnitRepo, is_excluded_unit
from src.plugins.aoe3.upgrades import apply_upgrades

logger = logging.getLogger("aoe3_battle.lineup")

# =====================================================================
# 常量
# =====================================================================
BUDGET = 10000               # 默认资源预算（与 game.py BUDGET_DEFAULT 一致）

# 时代名 → 游戏时代号（与 units.json age 字段口径一致）
AGE_NAME_TO_NUM = {
    "Exploration Age": 1,
    "Commerce Age": 2,
    "Fortress Age": 3,
    "Industrial Age": 4,
    "Imperial Age": 5,
}


def unit_game_age(unit: Unit) -> int:
    """单位登场时代号（1~5）；缺失视为 1（始终可用）。"""
    return AGE_NAME_TO_NUM.get(unit.age, 1)


def _age_filter(pool: list[Unit], age: int | None) -> list[Unit]:
    """按 `unit.age ≤ age` 过滤兵池；age 为 None 不过滤。"""
    if age is None:
        return pool
    return [u for u in pool if unit_game_age(u) <= age]


def _apply_age_to_lineup(lineup: "Lineup", age: int | None) -> "Lineup":
    """对阵容每个槽位的兵叠加该时代改良（出副本）。age=None 原样返回。"""
    if age is None:
        return lineup
    lineup.slots = [UnitSlot(apply_upgrades(s.unit, age), s.count) for s in lineup.slots]
    return lineup

# 兵种数量权重（§2.2.3）
SLOT_WEIGHTS = [0, 50, 50]   # 1种0%, 2种50%, 3种50%

# LCM 预算浮动范围（§2.2.4）
LCM_BUDGET_TOLERANCE = 0.3   # ±30%

# 抽兵最大重试次数
MAX_DRAW_RETRIES = 20

# 黑名单：按兵种 id 排除（两种模式统一生效）
# 发现数据异常、表现极端、或不适合斗蛐蛐的兵种直接加 id
BLACKLIST: set[str] = {
    # 作弊单位（Cheat unit）— 数据完全离谱
    "mediocrebombard",           # 中型火炮，攻击力 5000，cost 16
    "learicorn",                 # 利尔厉（独角兽），近战 800

    # 假炮 — InflictsNoDamage 单位，attack_ranged=500 是假数据，实际不打伤害
    "dequakergun",               # 木制假炮

    # 翻译缺失 + 不认识的奇怪单位
    "yppeasantindians",          # ypPeasantIndians，无中文名
    "ypirregularindians",        # ypIrregularIndians，无中文名
}


# 普通对战黑名单：彩蛋 / 作弊码 / 怪物战役兵
#
# 这些都是**真单位**（玩家能 ``/帝国3 xxx`` 查到），但数据离谱、不该
# 出现在普通斗蛐蛐对战池里。它们专为"黑名单乱斗"模式（计划中）准备：
# 该模式从这个池子里抽兵，让群友体验一把怪物互殴。
#
# 与 ``BLACKLIST`` 的区别：
#   - ``BLACKLIST``：数据 broken / 无法模拟，**永久禁用**（火船、假炮等）
#   - ``BATTLE_BLACKLIST``：数据虽离谱但能跑，**仅普通对战禁用**，
#     黑名单乱斗模式专属菜谱
#
# 战役兵分级标准（2026-05-21 重新整理）：
#   - **怪物级战役兵** → 进这里（hp ≥ 500 / 攻击数据离谱 / 有名有姓的英雄）
#   - **菜鸡级战役兵**（普通一人口兵换皮，hp ≤ 280）→ ``repository.py``
#     ``_EXCLUDED_IDS`` 全局屏蔽，连黑名单乱斗都不配进
#   - NATIVE 客兵（``spcaztecchief`` 等 5 个）→ 留在常规池（原住民部落能合法获取）
BATTLE_BLACKLIST: dict[str, str] = {
    # —— 作弊码 / 复活节彩蛋 ——
    "lazerbear":           "彩蛋·镭射熊",            # hp 106106，cheat: tuck tuck tuck
    "georgecrushington":   "彩蛋·乔治垮盛顿",        # hp 999999
    "monstertrucka":       "彩蛋·怪兽卡车-大安迪",   # hp 60000
    "monstertruckt":       "彩蛋·怪兽卡车-汤米",     # hp 60000
    "ypeggicecreamtruck":  "彩蛋·冰淇淋大脚车",      # hp 60000
    "fluffy":              "彩蛋·毛毛",              # hp 600 melee=800，cost 12（极端超模）
    "flyingpurpletapir":   "彩蛋·会飞的紫貘",        # hp 600 melee=800
    "deeggleonardostank":  "彩蛋·莱昂纳多的战车",    # hp 5000 ranged=800，DE 彩蛋 DLC

    # —— 弃用 / 老版本兵种 ——
    "legacygatlingcamel":  "祖传·加特林骆驼",        # hp 9001，legacy 前缀

    # —— 战役大佬 · 大名 / 武将（hp 1000+ 超模） ——
    "ypspcdaimyokiyomasa":  "剧情·加藤清正大名",     # hp 1000 atk siege=40
    "ypspcdaimyomasamune":  "剧情·伊达政宗大名",     # hp 1000 atk siege=40
    "ypspcdaimyotadaoki":   "剧情·细川忠兴大名",     # hp 1000 atk siege=40
    "ypspcishida":          "剧情·石田大名",         # hp 1250

    # —— 战役英雄（有名有姓的剧情主角，普通对战不可造） ——
    "despckassahailu":      "剧情·卡萨·海卢",       # 埃塞俄比亚战役英雄 hp 650
    "despcmansur":          "剧情·艾哈迈德·曼苏尔", # 摩洛哥战役英雄 hp 1000 atk siege=40
    "spcdeunclefrankhorse": "剧情·法兰克叔叔",       # hp 1000
    "spcxpcrazyhorse":      "剧情·疯马",             # hp 1000

    # —— 战役酋长（原住民英雄级，hp ≥ 475） ——
    "spcxpchiefbravewolf":  "剧情·狼勇士酋长",       # hp 500
    "spcxpchiefbullbear":   "剧情·巨熊酋长",         # hp 475
    "spcxpchieftwomoon":    "剧情·双月酋长",         # hp 500
    "despcmilitiaofficer":  "剧情·民兵军官",         # hp 500

    # —— 攻击数据离谱的特殊机械 / 强兵 ——
    "spcxpredoubtcannon":     "剧情·防卫据点加农炮", # hp 1000 atk ranged=650（离谱）
    "despcgreatbombardnopop": "剧情·重型火炮(无人口)", # hp 475 atk ranged=500
    "despcoutlawlandsknecht": "剧情·亡命之徒德国步兵", # hp 430 atk siege=72（普通兵 atk 顶天 32）
}


# 纯治疗师攻击力阈值：≤ 此值视为"打不动人的辅助单位"，排除出池
# - 0 攻击：审判官（1 个）
# - 4-5 攻击：神父/传教士/伊玛目/女祭司/军医/婆罗门... 约 13 个
# - 8 攻击：弓僧兵（数据偏弱，一起排）
# - 10 攻击：随军神父（一起排）
# - 15 攻击：说书人（保留）
# - 30 攻击：少林大师（保留）
PURE_HEALER_ATTACK_THRESHOLD = 10


# =====================================================================
# 黑名单乱斗常量（详见设计文档 §2.4）
# =====================================================================
# 兵种数权重：黑名单池只有 18 个兵种，3 兵种局展示拥挤、节目效果分散，
# 因此只保留 1 / 2 兵种概率。
# 1 种 50%（神仙打架：N 镭射熊 vs N 垮盛顿）
# 2 种 50%（搭配节目效果）
SLOT_WEIGHTS_BLACKLIST = [50, 50, 0]

# 浮动倍率 r：target = max(双方最强单兵分) × r，r ~ U(R_MIN, R_MAX)
#
# 含义：让两边都 ramp 到接近相同的总战力 target。
#
# 设计要点（详见 §2.4）：
#
# - 用 max(双方 max_score) 作为 anchor：双方都按同一个 target 配兵，
#   总战力自然对齐（强方保底 1 只，弱方按总战力对齐 ramp）。
# - **无个体数上限**：与押注/单挑一致，数量完全由战力分决定。
#   1 镭射熊 vs 500 民兵这种"超人打蚂蚁"局是黑名单乱斗的常规节目效果。
# - r 范围 3~6：强方最强单兵 ramp 到 r 只（其 score 通常 ≥ target/r 即可），
#   弱方按 r×anchor 总战力 ramp 出几十到几百只。倍率取高让局面更壮观。
BLACKLIST_R_MIN = 3.0
BLACKLIST_R_MAX = 6.0

# ---- 战力公式参数（power_score）----
#
# 公式概念：score = sqrt(HP_eff × DPS_eff)
#
#   HP_eff  = hp × (1 + max_armor × ARMOR_WEIGHT)      ← 护甲轻微增益
#   DPS_eff = soft(max(soft(hit_r), soft(hit_m)) / rof, DPS_BASELINE)
#              ← 单次伤害 + DPS 双层"溢出减益"
#   hit_x   = atk_x × (1 + aoe_x × AOE_HIT_MULT)        ← AOE 加成
#
# soft(x, base) = x ≤ base 时线性；x > base 时按 sqrt 收敛（边际递减）。
#
# 用几何平均（sqrt）的原因：HP 与 DPS 同等重要，单独任一项极端高不应
# 让总战力线性爆炸（"血厚但打不动" / "高射炮打蚊子"），用 sqrt 让两边都
# 受边际递减约束。
#
# 实测标定（1 镭射熊 = N X 的均衡点）：
#   vs 重型火炮(无人口)：公式 ~19:1，实测 ~15:1（差距 1.2×）
#   vs 防卫据点炮：     公式 ~12:1，实测  ~7:1（差距 1.8×）
#   vs 民兵长：         公式 ~55:1，实测 ~30:1（差距 1.8×）
#
# 跨档差距仍存在（剪刀石头布、armor 实际抵消等无法用单兵公式覆盖），
# 但已从旧版"几十~几千倍偏差"压缩到 1~2 倍量级。
ARMOR_WEIGHT = 0.3              # 护甲增益系数：hp × (1 + armor × 0.3)
BLACKLIST_AOE_DPS_MULT = 0.3    # AOE 加成：单次伤害每 1 半径 +30%
HIT_BASELINE = 50.0             # 单击伤害基准：超出部分按 sqrt 减益
DPS_BASELINE = 20.0             # DPS 基准：超出部分按 sqrt 减益


# =====================================================================
# 阵容数据
# =====================================================================
@dataclass
class UnitSlot:
    """阵容中的一个兵种槽位。"""
    unit: Unit
    count: int

    @property
    def unit_cost(self) -> int:
        """单个单位的资源消耗。"""
        return sum(self.unit.cost.values())

    @property
    def total_cost(self) -> int:
        """该槽位的总资源消耗。"""
        return self.unit_cost * self.count


@dataclass
class Lineup:
    """一方的阵容（支持多兵种）。"""
    slots: list[UnitSlot]

    @property
    def total_cost(self) -> int:
        """总资源消耗。"""
        return sum(s.total_cost for s in self.slots)

    @property
    def total_pop(self) -> int:
        """总人口。"""
        return sum(s.unit.pop * s.count for s in self.slots)

    @property
    def total_count(self) -> int:
        """总个体数。"""
        return sum(s.count for s in self.slots)

    # ---- 向后兼容：单兵种场景的便捷属性 ----
    @property
    def unit(self) -> Unit:
        """第一个（或唯一）兵种。"""
        return self.slots[0].unit

    @property
    def count(self) -> int:
        """第一个（或唯一）兵种的数量。"""
        return self.slots[0].count

    @property
    def pop(self) -> int:
        """总人口（兼容旧接口）。"""
        return self.total_pop

    @property
    def is_multi(self) -> bool:
        """是否为多兵种阵容。"""
        return len(self.slots) > 1

    @property
    def total_power(self) -> float:
        """总战力分（仅用于黑名单乱斗展示与平衡计算）。"""
        return sum(power_score(s.unit) * s.count for s in self.slots)


@dataclass
class MatchLineup:
    """一局对阵的双方阵容。"""
    red: Lineup
    blue: Lineup
    mode: str                  # "bet" | "duel" | "rival" | ...
    rival_theme: str | None = None   # 王中王展示名，如「散兵王」
    age: int | None = None     # 本局时代（2~5）；None = 未启用改良/时代限定
    generic_tech_lines: list[str] = field(default_factory=list)


# =====================================================================
# 兵种池筛选
# =====================================================================
def _is_building(unit: Unit) -> bool:
    """判断是否为建筑（排除建筑马车等）。"""
    tags = set(unit.type)
    return bool(tags & {"Building", "AbstractBuilding", "AbstractWagon"})


def _is_hero(unit: Unit) -> bool:
    """判断是否为英雄。"""
    return "Hero" in unit.type


def _is_pet(unit: Unit) -> bool:
    """判断是否为宠物（仅 AbstractPet；Guardian 由 ``is_excluded_unit`` 全局排除）。"""
    return "AbstractPet" in unit.type


def _is_ship(unit: Unit) -> bool:
    """判断是否为船只。"""
    return "Ship" in unit.type or "AbstractWarShip" in unit.type


def _is_villager(unit: Unit) -> bool:
    """判断是否为村民类单位。"""
    return "AbstractVillager" in unit.type


def _is_pure_healer(unit: Unit) -> bool:
    """判断是否为"打不动人的纯治疗师"。

    规则：标签含 ``AbstractHealer`` 且最大攻击力 ≤ ``PURE_HEALER_ATTACK_THRESHOLD``。
    斗蛐蛐里没有治疗机制，这些单位拉进池子就是纯纯拖后腿（教皇打拳 5 点伤害）。

    保留有真实战斗力的"和尚"（说书人 15、少林大师 30）。
    """
    if "AbstractHealer" not in unit.type:
        return False
    max_atk = max(unit.attack_ranged or 0, unit.attack_melee or 0)
    return max_atk <= PURE_HEALER_ATTACK_THRESHOLD


def get_bet_pool(repo: UnitRepo, age: int | None = None) -> list[Unit]:
    """押注模式兵种池。

    规则（§2.2.2）：
    - cost > 0 且 has_attack 且 hp > 0
    - 保留雇佣兵、英雄、宠物、侦察兵（节目效果 / 有倍率机制）
    - 排除建筑马车、船只、村民
    - 排除纯治疗师（``AbstractHealer`` 且攻击 ≤ 10）
    - 排除召唤占位符（``*batch``）和 PVE 守护者（``is_excluded_unit``）
    - 排除 ``BLACKLIST``（数据 broken）和 ``BATTLE_BLACKLIST``（彩蛋/作弊兵）
    - ``age`` 给定时按 ``unit.age ≤ age`` 限定（§3.10.6）
    """
    pool = []
    blacklisted = 0
    excluded = 0
    for u in repo.all_units:
        # 必须有费用和攻击力
        if not u.cost or not u.has_attack:
            continue
        # 全局排除：召唤占位符 / PVE 守护者
        if is_excluded_unit(u):
            excluded += 1
            continue
        # 排除建筑
        if _is_building(u):
            continue
        # 排除船只
        if _is_ship(u):
            continue
        # 排除村民
        if _is_villager(u):
            continue
        # 排除纯治疗师（打不动人的辅助单位）
        if _is_pure_healer(u):
            continue
        # 必须有 HP
        if u.hp <= 0:
            continue
        # 黑名单（永久禁用 + 普通对战禁用）
        if u.id in BLACKLIST or u.id in BATTLE_BLACKLIST:
            blacklisted += 1
            continue
        pool.append(u)

    pool = _age_filter(pool, age)
    logger.info(
        "押注模式兵种池：%d 个兵种（总 %d，全局排除 %d，黑名单排除 %d，时代≤%s）",
        len(pool), len(repo.all_units), excluded, blacklisted, age,
    )
    return pool


def get_blacklist_pool(repo: UnitRepo) -> list[Unit]:
    """黑名单乱斗兵种池。

    规则（详见设计文档 §2.6）：

    - 来源：``BATTLE_BLACKLIST``（彩蛋 / 作弊码 / 怪物级战役兵）
    - 必须 ``has_attack``（即 ``attack_ranged`` 或 ``attack_melee`` 有值），
      模拟器才打得动；只有 ``attack_siege`` 的会被自动剔除
    - 必须 ``hp > 0``
    - 防御性地过一次 ``is_excluded_unit``，以防黑名单里混了被全局排除的 id

    池子小（~20 个），日志按 INFO 打出来便于追踪。
    """
    pool: list[Unit] = []
    skipped: list[str] = []
    for unit_id in BATTLE_BLACKLIST:
        u = repo.get_by_id(unit_id)
        if u is None:
            skipped.append(f"{unit_id}(数据库找不到)")
            continue
        if is_excluded_unit(u):
            skipped.append(f"{unit_id}(被全局排除)")
            continue
        if not u.has_attack:
            skipped.append(f"{unit_id}(无 melee/ranged 攻击)")
            continue
        if u.hp <= 0:
            skipped.append(f"{unit_id}(hp ≤ 0)")
            continue
        pool.append(u)

    if skipped:
        logger.warning(
            "黑名单乱斗池：跳过 %d 个 id（%s）",
            len(skipped), ", ".join(skipped),
        )
    logger.info(
        "黑名单乱斗池：%d 个兵种（BATTLE_BLACKLIST 共 %d）",
        len(pool), len(BATTLE_BLACKLIST),
    )
    return pool


def get_duel_pool(repo: UnitRepo, age: int | None = None) -> list[Unit]:
    """单挑模式兵种池。

    规则（§2.3）：
    - 所有有攻击力的兵种（含英雄、特殊单位、雇佣兵、宠物）
    - 排除建筑、船只、村民
    - 排除纯治疗师（``AbstractHealer`` 且攻击 ≤ 10）
    - 排除召唤占位符（``*batch``）和 PVE 守护者（``is_excluded_unit``）
    - 排除 ``BLACKLIST``（数据 broken）和 ``BATTLE_BLACKLIST``（彩蛋/作弊兵）
    - ``age`` 给定时按 ``unit.age ≤ age`` 限定（§3.10.6）
    """
    pool = []
    blacklisted = 0
    excluded = 0
    for u in repo.all_units:
        if not u.has_attack:
            continue
        if is_excluded_unit(u):
            excluded += 1
            continue
        if _is_building(u):
            continue
        if _is_ship(u):
            continue
        if _is_villager(u):
            continue
        if _is_pure_healer(u):
            continue
        if u.hp <= 0:
            continue
        # 黑名单（永久禁用 + 普通对战禁用）
        if u.id in BLACKLIST or u.id in BATTLE_BLACKLIST:
            blacklisted += 1
            continue
        pool.append(u)

    pool = _age_filter(pool, age)
    logger.info(
        "单挑模式兵种池：%d 个兵种（总 %d，全局排除 %d，黑名单排除 %d，时代≤%s）",
        len(pool), len(repo.all_units), excluded, blacklisted, age,
    )
    return pool


# =====================================================================
# 资源分配算法
# =====================================================================

def _unit_cost(unit: Unit) -> int:
    """获取单位总资源消耗。"""
    return sum(unit.cost.values())


def _soft_diminish(value: float, baseline: float) -> float:
    """边际递减软上限。

    - ``value ≤ baseline``：线性返回 ``value``
    - ``value > baseline``：``baseline + sqrt((value - baseline) × baseline)``

    意义：在 baseline 内贡献全额，超出部分按 sqrt 收益。
    用于战力公式里两层"溢出减益"——单次伤害和最终 DPS。
    """
    if value <= baseline:
        return value
    return baseline + math.sqrt(max(0.0, (value - baseline) * baseline))


def power_score(unit: Unit) -> float:
    """单兵战力分（黑名单乱斗专用）。

    公式：``score = sqrt(HP_eff × DPS_eff)``

    三要素（详见 ``BLACKLIST_AOE_DPS_MULT`` / ``HIT_BASELINE`` /
    ``DPS_BASELINE`` 注释）：

    - **HP**：``hp × (1 + max_armor × ARMOR_WEIGHT)``。
      单调递增，护甲只做轻微增益（``armor=0.9`` 仅 ×1.27）。
    - **DPS**：双层"溢出减益"。
      单击伤害 ``hit = atk × (1 + aoe × AOE_HIT_MULT)`` 先 soft 一次（治
      "800 攻击打民兵"的浪费），除以 rof 得 dps 再 soft 一次（治"机关枪打
      蚊子"的浪费）。
    - **几何平均**：``sqrt(HP × DPS)`` 让 HP/DPS 同等加权，避免单项极端
      数据让总战力线性爆炸。

    设计原则（与设计文档 §3.9 一致）：

    - 只看模拟器实际会用的 ``attack_ranged`` / ``attack_melee``；
      ``attack_siege`` 模拟器不读，不计入。
    - 倍率（multipliers）不计——克制由模拟器自然发挥。
    - 不计 speed / 射程，1v1 静态战力公式无法量化"接战阶段"的影响。
    """
    eff_armor = max(unit.armor_ranged or 0.0, unit.armor_melee or 0.0)
    hp_eff = unit.hp * (1.0 + eff_armor * ARMOR_WEIGHT)

    rof_r = unit.rof_ranged or 3.0
    rof_m = unit.rof_melee or 1.5

    hit_r = (unit.attack_ranged or 0.0) * (unit.num_projectiles_ranged or 1) * (
        1.0 + (unit.aoe_radius_ranged or 0) * BLACKLIST_AOE_DPS_MULT
    )
    hit_m = (unit.attack_melee or 0.0) * (unit.num_projectiles_melee or 1) * (
        1.0 + (unit.aoe_radius_melee or 0) * BLACKLIST_AOE_DPS_MULT
    )
    eff_hit_r = _soft_diminish(hit_r, HIT_BASELINE)
    eff_hit_m = _soft_diminish(hit_m, HIT_BASELINE)

    dps_raw = max(
        eff_hit_r / max(0.1, rof_r),
        eff_hit_m / max(0.1, rof_m),
    )
    dps_eff = _soft_diminish(dps_raw, DPS_BASELINE)

    return math.sqrt(hp_eff * dps_eff)


def approx_lcm_budget(cost_a: int, cost_b: int, base_budget: int) -> int:
    """近似 LCM 算法（§2.2.4）：让双方资源尽量相等。

    返回调整后的预算（双方共用）。
    """
    ca = max(1, round(cost_a))
    cb = max(1, round(cost_b))

    lcm_val = abs(ca * cb) // math.gcd(ca, cb)

    # LCM 太大 → 退化为基础预算
    if lcm_val > base_budget * (1 + LCM_BUDGET_TOLERANCE):
        return base_budget

    # 取最接近 base_budget 的 LCM 倍数
    n = round(base_budget / lcm_val)
    n = max(1, n)
    actual = n * lcm_val

    # clamp 到 ±30% 范围
    lo = int(base_budget * (1 - LCM_BUDGET_TOLERANCE))
    hi = int(base_budget * (1 + LCM_BUDGET_TOLERANCE))
    actual = max(lo, min(hi, actual))

    return actual


def greedy_fill(budget: int, unit_costs: list[int]) -> list[int]:
    """贪心填充三步法（§2.2.3）：多兵种资源分配。

    输入：总预算 budget，兵种 cost 列表
    输出：每个兵种的数量列表
    """
    n = len(unit_costs)
    if n == 0:
        return []

    # Step 1 — 保底：每种兵各 1 个
    counts = [1] * n
    remaining = budget - sum(unit_costs)
    if remaining < 0:
        # 保底就超预算（不应该发生，抽兵约束应拦截）
        logger.warning("贪心填充：保底超预算！budget=%d, costs=%s", budget, unit_costs)
        return counts

    # Step 2 — 均分：剩余预算均分给每个兵种
    per_budget = remaining // n
    for i in range(n):
        extra = per_budget // unit_costs[i]
        counts[i] += extra

    # Step 3 — 贪心零头：最后的零头逐个加最便宜的兵
    remaining = budget - sum(c * cost for c, cost in zip(counts, unit_costs))
    while remaining > 0:
        best = None
        for i in range(n):
            if unit_costs[i] <= remaining:
                if best is None or unit_costs[i] < unit_costs[best]:
                    best = i
        if best is None:
            break
        counts[best] += 1
        remaining -= unit_costs[best]

    return counts


# =====================================================================
# 阵容生成
# =====================================================================

def _draw_units(
    pool: list[Unit],
    slot_count: int,
    budget: int,
    rng: random.Random,
) -> list[Unit] | None:
    """从池中抽取 slot_count 个不同兵种，满足抽兵约束。

    抽兵约束：各出 1 个的总 cost ≤ 预算。
    返回 None 表示重试次数耗尽。
    """
    for _ in range(MAX_DRAW_RETRIES):
        chosen = rng.sample(pool, min(slot_count, len(pool)))
        total_min_cost = sum(_unit_cost(u) for u in chosen)
        if total_min_cost <= budget:
            return chosen
    return None


def _generate_side_lineup(
    pool: list[Unit],
    budget: int,
    rng: random.Random,
    *,
    defer_counts: bool = False,
) -> Lineup:
    """为一方生成阵容（支持 1~3 兵种）。

    ``defer_counts=True`` 时只选兵种、不分配数量（count=1 占位），
    由调用方在升级/科技应用后调用 ``allocate_lineup_counts`` 一次性分配。
    """
    # 抽兵种数
    slot_count = rng.choices([1, 2, 3], weights=SLOT_WEIGHTS, k=1)[0]

    # 确保池子够大
    slot_count = min(slot_count, len(pool))

    # 抽兵种（带约束）
    chosen = _draw_units(pool, slot_count, budget, rng)
    if chosen is None:
        # 约束满足不了，降级到 1 个兵种
        logger.warning("抽兵约束多次失败，降级为单兵种。budget=%d", budget)
        chosen = [rng.choice(pool)]

    if defer_counts:
        slots = [UnitSlot(unit=u, count=1) for u in chosen]
        lineup = Lineup(slots=slots)
        logger.info("阵容选兵（延迟分配）：%d 兵种: %s",
                     len(slots), ", ".join(u.name for u in chosen))
        return lineup

    # 分配数量
    costs = [_unit_cost(u) for u in chosen]

    if len(chosen) == 1:
        # 单兵种：简单除法
        count = max(1, budget // costs[0])
        slots = [UnitSlot(unit=chosen[0], count=count)]
    else:
        # 多兵种：贪心填充
        counts = greedy_fill(budget, costs)
        slots = [UnitSlot(unit=u, count=c) for u, c in zip(chosen, counts)]

    lineup = Lineup(slots=slots)

    logger.info(
        "阵容生成：%d 兵种，总花费 %d/%d (浪费 %d)，总人数 %d",
        len(slots), lineup.total_cost, budget,
        budget - lineup.total_cost, lineup.total_count,
    )
    for s in slots:
        logger.debug("  %s ×%d (cost=%d, 小计=%d)", s.unit.name, s.count, s.unit_cost, s.total_cost)

    return lineup


def allocate_lineup_counts(lineup: "Lineup", budget: int) -> None:
    """按当前 unit.cost 为 lineup 的每个槽位分配数量。

    用于「选兵种→升级→分配数量」流程的最后一步，
    在 tier / 通用科技都已应用（cost 可能已被修改）后调用。
    """
    costs = [_unit_cost(s.unit) for s in lineup.slots]
    if len(lineup.slots) == 1:
        lineup.slots[0] = UnitSlot(lineup.slots[0].unit,
                                   max(1, budget // costs[0]))
    else:
        counts = greedy_fill(budget, costs)
        lineup.slots = [UnitSlot(s.unit, c)
                        for s, c in zip(lineup.slots, counts)]

    logger.info(
        "数量分配：%d 兵种，总花费 %d/%d (浪费 %d)，总人数 %d",
        len(lineup.slots), lineup.total_cost, budget,
        budget - lineup.total_cost, lineup.total_count,
    )
    for s in lineup.slots:
        logger.debug("  %s ×%d (cost=%d, 小计=%d)",
                     s.unit.name, s.count, s.unit_cost, s.total_cost)


def _apply_lcm_balance(
    red: "Lineup", blue: "Lineup", budget: int,
) -> None:
    """单兵种 vs 单兵种时用 LCM 算法平衡资源并重新分配数量。"""
    if red.is_multi or blue.is_multi:
        return
    cost_a = red.slots[0].unit_cost
    cost_b = blue.slots[0].unit_cost
    lcm_budget = approx_lcm_budget(cost_a, cost_b, budget)

    red.slots[0] = UnitSlot(
        unit=red.slots[0].unit,
        count=max(1, lcm_budget // cost_a),
    )
    blue.slots[0] = UnitSlot(
        unit=blue.slots[0].unit,
        count=max(1, lcm_budget // cost_b),
    )

    logger.info(
        "LCM 平衡：预算 %d → %d，🔴 %s ×%d (%d) vs 🔵 %s ×%d (%d) 差=%d",
        budget, lcm_budget,
        red.unit.name, red.count, red.total_cost,
        blue.unit.name, blue.count, blue.total_cost,
        abs(red.total_cost - blue.total_cost),
    )


def generate_bet_lineup(
    repo: UnitRepo,
    *,
    budget: int = BUDGET,
    age: int | None = None,
    rng: random.Random | None = None,
    defer_counts: bool = False,
) -> MatchLineup:
    """生成押注模式阵容（v2 复合阵容）。

    规则（§2.2.3）：
    - 红蓝双方各独立生成 1~3 个兵种的阵容
    - 单兵种 vs 单兵种时使用 LCM 算法平衡资源
    - 多兵种时使用贪心填充
    - ``age`` 给定时兵池按时代限定，并对双方叠加该时代改良（§3.10.6）

    ``defer_counts=True``：只选兵种 + 叠时代改良，不分配数量（count=1 占位）、
    不做 LCM 平衡。调用方在通用科技等修改 cost 后，自行调
    ``allocate_lineup_counts`` + ``_apply_lcm_balance``。
    """
    if rng is None:
        rng = random.Random()

    pool = get_bet_pool(repo, age=age)
    if len(pool) < 2:
        raise ValueError(f"兵种池不足：仅 {len(pool)} 个兵种")

    # 红蓝双方独立生成
    red = _generate_side_lineup(pool, budget, rng, defer_counts=defer_counts)
    blue = _generate_side_lineup(pool, budget, rng, defer_counts=defer_counts)

    # tier 升级（不改 cost，只改 HP/Damage）
    _apply_age_to_lineup(red, age)
    _apply_age_to_lineup(blue, age)

    if not defer_counts:
        _apply_lcm_balance(red, blue, budget)

        logger.info(
            "押注阵容最终：🔴 %s (cost=%d, pop=%d) vs 🔵 %s (cost=%d, pop=%d)",
            " + ".join(f"{s.unit.name}×{s.count}" for s in red.slots),
            red.total_cost, red.total_pop,
            " + ".join(f"{s.unit.name}×{s.count}" for s in blue.slots),
            blue.total_cost, blue.total_pop,
        )

    return MatchLineup(red=red, blue=blue, mode="bet", age=age)


def _fill_to_target(
    target_score: float,
    scores: list[float],
) -> list[int]:
    """按战力分填充数量，让 ``sum(counts × scores)`` 逼近 ``target_score``。

    输入：
      - ``target_score``：目标总战力分（双方共用）
      - ``scores``：各兵种单兵战力分

    输出：每个兵种的数量列表，``count_i ≥ 1``，**无数量上限**。

    策略：
      1. 每种保底 1 个
      2. 若已超 target，直接返回（强方场景：怪兽 score >> target）
      3. 否则反复挑 ``counts[i] × scores[i]`` 最小的兵种 +1，
         直到总分 ≥ target × 1.05

    "挑当前总分最小的 +1" 实现弱方多兵种均匀 ramp。
    弱方对怪兽 anchor 时可能 ramp 到几百个个体——这与 §3.2 "无人口上限、
    数量完全由资源/战力决定" 的全局哲学一致，1 镭射熊 vs 500 民兵就是
    黑名单乱斗的常规节目效果。
    """
    n = len(scores)
    if n == 0:
        return []

    counts = [1] * n
    cur = sum(scores)
    if cur >= target_score:
        return counts

    overshoot_cap = target_score * 1.05
    while cur < target_score:
        best = 0
        best_val = counts[0] * scores[0]
        for i in range(1, n):
            v = counts[i] * scores[i]
            if v < best_val:
                best_val = v
                best = i
        counts[best] += 1
        cur += scores[best]
        if cur >= overshoot_cap:
            break

    return counts


def generate_blacklist_lineup(
    repo: UnitRepo,
    *,
    rng: random.Random | None = None,
) -> MatchLineup:
    """生成黑名单乱斗阵容。

    规则（详见设计文档 §2.4）：

    - 红蓝双方独立从 ``BATTLE_BLACKLIST`` 池随机抽 1~3 个兵种，
      权重 ``SLOT_WEIGHTS_BLACKLIST = [40, 40, 20]``
    - 完全无视 cost，按战力分平衡数量
    - **目标战力分 = max(双方最强单兵分) × r**，``r ~ U(R_MIN, R_MAX)``
    - 双方独立按 target 用 ``_fill_to_target`` ramp，无个体数上限
    - 战力相对对齐（实测多数局战力比 1~4×），但不强求等于；
      含怪兽的一方因数量上限仍会偏强（节目效果）
    """
    if rng is None:
        rng = random.Random()

    pool = get_blacklist_pool(repo)
    if len(pool) < 2:
        raise ValueError(f"黑名单乱斗池不足：仅 {len(pool)} 个兵种")

    def _draw(n_slots: int) -> list[Unit]:
        return rng.sample(pool, min(n_slots, len(pool)))

    red_slot_count = rng.choices([1, 2, 3], weights=SLOT_WEIGHTS_BLACKLIST, k=1)[0]
    blue_slot_count = rng.choices([1, 2, 3], weights=SLOT_WEIGHTS_BLACKLIST, k=1)[0]
    red_units = _draw(red_slot_count)
    blue_units = _draw(blue_slot_count)

    red_scores = [power_score(u) for u in red_units]
    blue_scores = [power_score(u) for u in blue_units]

    # 共用 anchor：双方最强单兵分的最大值 × r
    # 这样两边都向同一个 target 配兵，总战力自然对齐
    anchor = max(max(red_scores), max(blue_scores))
    r = rng.uniform(BLACKLIST_R_MIN, BLACKLIST_R_MAX)
    target = anchor * r

    red_counts = _fill_to_target(target, red_scores)
    blue_counts = _fill_to_target(target, blue_scores)

    red_slots = [UnitSlot(u, c) for u, c in zip(red_units, red_counts)]
    blue_slots = [UnitSlot(u, c) for u, c in zip(blue_units, blue_counts)]
    red = Lineup(slots=red_slots)
    blue = Lineup(slots=blue_slots)

    logger.info(
        "黑名单乱斗阵容：r=%.2f anchor=%.0f target=%.0f, "
        "🔴 %s (战力=%.0f, 总人数=%d) vs 🔵 %s (战力=%.0f, 总人数=%d)",
        r, anchor, target,
        " + ".join(f"{s.unit.name}×{s.count}" for s in red_slots),
        red.total_power, red.total_count,
        " + ".join(f"{s.unit.name}×{s.count}" for s in blue_slots),
        blue.total_power, blue.total_count,
    )
    for s in red_slots + blue_slots:
        logger.debug(
            "  %s ×%d (单兵分=%.0f, 小计=%.0f)",
            s.unit.name, s.count,
            power_score(s.unit),
            power_score(s.unit) * s.count,
        )

    return MatchLineup(red=red, blue=blue, mode="blacklist")


def generate_duel_lineup(
    repo: UnitRepo,
    *,
    age: int | None = None,
    rng: random.Random | None = None,
) -> MatchLineup:
    """生成单挑模式阵容。

    规则（§2.3）：
    - 两边各 1 个兵种，各 1 个单位
    - 不考虑资源平衡
    - ``age`` 给定时兵池按时代限定，并叠加该时代改良
    """
    if rng is None:
        rng = random.Random()

    pool = get_duel_pool(repo, age=age)
    if len(pool) < 2:
        raise ValueError(f"兵种池不足：仅 {len(pool)} 个兵种")

    red_unit, blue_unit = rng.sample(pool, 2)
    if age is not None:
        red_unit = apply_upgrades(red_unit, age)
        blue_unit = apply_upgrades(blue_unit, age)

    logger.info(
        "单挑阵容生成：🔴 %s (HP=%d) vs 🔵 %s (HP=%d)",
        red_unit.name, red_unit.hp,
        blue_unit.name, blue_unit.hp,
    )

    return MatchLineup(
        red=Lineup(slots=[UnitSlot(unit=red_unit, count=1)]),
        blue=Lineup(slots=[UnitSlot(unit=blue_unit, count=1)]),
        mode="duel",
        age=age,
    )


# =====================================================================
# 面板文本生成
# =====================================================================

def _atk_summary(u: Unit) -> str:
    """一行压缩攻击信息（仅显示模拟器实际使用的远程/近战攻击）。"""
    parts = []
    _dtype_label = {"Siege": "攻城伤害", "Hand": "近战伤害"}

    if u.attack_ranged:
        rng_str = f"射程{u.range}"
        if u.range_min:
            rng_str = f"射程{u.range_min}-{u.range}"
        dtype_tag = ""
        if u.damage_type_ranged and u.damage_type_ranged != "Ranged":
            dtype_tag = f",{_dtype_label.get(u.damage_type_ranged, u.damage_type_ranged)}"
        atk_str = f"{u.attack_ranged:.0f}"
        if u.num_projectiles_ranged > 1:
            atk_str = f"{u.attack_ranged:.0f}×{u.num_projectiles_ranged}发"
        parts.append(f"远程{atk_str}({rng_str}, {u.rof_ranged}s{dtype_tag})")
    if u.attack_melee:
        dtype_tag = ""
        if u.damage_type_melee and u.damage_type_melee != "Hand":
            dtype_tag = f",{_dtype_label.get(u.damage_type_melee, u.damage_type_melee)}"
        range_tag = ""
        if u.range_melee and u.range_melee > 1.5:
            range_tag = f",射程{u.range_melee}"
        parts.append(f"近战{u.attack_melee:.0f}({u.rof_melee}s{dtype_tag}{range_tag})")
    # 攻城攻击不在斗蛐蛐中使用，不显示
    return " | ".join(parts) if parts else "无攻击"


def _armor_str(u: Unit) -> str:
    """抗性摘要。"""
    parts = []
    if u.armor_ranged:
        parts.append(f"远防{u.armor_ranged:.0%}")
    if u.armor_melee:
        parts.append(f"近防{u.armor_melee:.0%}")
    return " ".join(parts)


def _type_str_zh(u: Unit) -> str:
    """兵种类型中文翻译（精简版，去掉冗余标签）。

    与 `src/plugins/aoe3/formatter.py` 的兵种卡片共用同一份过滤+翻译逻辑，
    保证 CLI/卡片/斗蛐蛐显示的兵种类型口径一致。
    """
    from src.plugins.aoe3.type_display import format_unit_types

    types_zh = format_unit_types(u)
    return " / ".join(types_zh) if types_zh else "未知"



def _find_counter_relations(
    unit: Unit, opponent_lineup: "Lineup", *, threshold: float = 1.5
) -> tuple[list[str], list[str]]:
    """分析一个兵种与对方阵容的克制关系。

    返回 (advantages, disadvantages):
      advantages: 己方克制对方的描述列表，如 "→ 克制 火枪手(重步兵 x3)"
      disadvantages: 己方被对方克制的描述列表，如 "← 被 散兵 克制(轻步兵 x2)"
    """
    from src.plugins.aoe3.i18n import t

    advantages: list[str] = []
    disadvantages: list[str] = []

    my_type_set = set(unit.type)
    my_mults = unit.multipliers_ranged + unit.multipliers_melee

    for slot in opponent_lineup.slots:
        opp = slot.unit
        opp_type_set = set(opp.type)

        # 己方克制对方：我的倍率 vs 匹配对方的 type
        best_adv: tuple[str, float] | None = None
        for m in my_mults:
            # 去掉倍率 vs 后面的 * 号再匹配
            vs_clean = m.vs.rstrip(" *")
            if vs_clean in opp_type_set and m.value >= threshold:
                if best_adv is None or m.value > best_adv[1]:
                    best_adv = (vs_clean, m.value)
        if best_adv:
            vs_zh = t("tags", best_adv[0])
            advantages.append(f"克制 {opp.name}({vs_zh} x{best_adv[1]:g})")

        # 对方克制己方：对方的倍率 vs 匹配我的 type
        opp_mults = opp.multipliers_ranged + opp.multipliers_melee
        best_dis: tuple[str, float] | None = None
        for m in opp_mults:
            vs_clean = m.vs.rstrip(" *")
            if vs_clean in my_type_set and m.value >= threshold:
                if best_dis is None or m.value > best_dis[1]:
                    best_dis = (vs_clean, m.value)
        if best_dis:
            vs_zh = t("tags", best_dis[0])
            disadvantages.append(f"被 {opp.name} 克制({vs_zh} x{best_dis[1]:g})")

    return advantages, disadvantages


def format_side_panel(
    lineup: Lineup, side: str, mode: str, opponent: "Lineup | None" = None
) -> str:
    """生成单方的详情面板文本（配合 icon 图片发送）。

    side: "red" | "blue"
    opponent: 对方阵容（用于标注克制关系）
    """
    emoji = "🔴" if side == "red" else "🔵"
    label = "1号" if side == "red" else "2号"

    lines: list[str] = []

    is_blacklist = mode == "blacklist"

    if mode == "duel":
        # 单挑模式：简洁
        lines.append(f"{emoji} {label} · {lineup.unit.name}")
        u = lineup.unit
        lines.append(f"类型：{_type_str_zh(u)}")
        lines.append(f"❤️{u.hp} 🦶{u.speed}")
        lines.append(f"⚔️ {_atk_summary(u)}")
        _append_extras(lines, u)
        if opponent:
            _append_counter_info(lines, u, opponent)

    elif not lineup.is_multi:
        # 单兵种押注 / 自选 / 王中王 / 黑名单单兵种：紧凑
        lines.append(f"{emoji} {label} · {lineup.unit.name} ×{lineup.count}")
        u = lineup.unit
        lines.append(f"类型：{_type_str_zh(u)}")
        if is_blacklist:
            lines.append(
                f"⭐总战力 {lineup.total_power:,.0f}（单兵 {power_score(u):,.0f}）"
            )
        else:
            lines.append(f"💰总资源 {lineup.total_cost}")
        lines.append(f"❤️{u.hp} 🦶{u.speed}")
        lines.append(f"⚔️ {_atk_summary(u)}")
        _append_extras(lines, u)
        if opponent:
            _append_counter_info(lines, u, opponent)

    else:
        # 多兵种押注模式 / 黑名单乱斗多兵种：每个兵种一段
        if is_blacklist:
            lines.append(
                f"{emoji} {label}（总战力 {lineup.total_power:,.0f}，总人数 {lineup.total_count}）"
            )
        else:
            lines.append(
                f"{emoji} {label}（总资源 {lineup.total_cost}，人口 {lineup.total_pop}）"
            )
        for slot in lineup.slots:
            u = slot.unit
            lines.append(f"  {'─' * 20}")
            if is_blacklist:
                lines.append(
                    f"  {u.name} ×{slot.count}  ⭐{power_score(u):,.0f}/只"
                )
            else:
                lines.append(f"  {u.name} ×{slot.count}")
            lines.append(f"  类型：{_type_str_zh(u)}")
            lines.append(f"  ❤️{u.hp} 🦶{u.speed}")
            lines.append(f"  ⚔️ {_atk_summary(u)}")
            _append_extras(lines, u, indent="  ")
            if opponent:
                _append_counter_info(lines, u, opponent, indent="  ")

    return "\n".join(lines)


def _append_extras(lines: list[str], u: Unit, indent: str = "") -> None:
    """追加抗性 + AOE + 官方 tooltip。"""
    extras = []
    armor = _armor_str(u)
    if armor:
        extras.append(f"🛡️{armor}")
    aoe_parts = []
    if u.aoe_radius_ranged:
        aoe_parts.append(f"远程AOE{u.aoe_radius_ranged}")
    if u.aoe_radius_melee:
        aoe_parts.append(f"近战AOE{u.aoe_radius_melee}")
    if u.aoe_radius_siege:
        aoe_parts.append(f"攻城AOE{u.aoe_radius_siege}")
    if aoe_parts:
        extras.append("💥" + " ".join(aoe_parts))
    elif u.aoe_radius:
        extras.append(f"💥AOE{u.aoe_radius}")
    if extras:
        lines.append(f"{indent}{' '.join(extras)}")
    append_unit_tooltip(lines, u, indent=indent)


def _append_counter_info(
    lines: list[str], u: Unit, opponent: "Lineup", indent: str = ""
) -> None:
    """追加克制关系高亮行。"""
    advantages, disadvantages = _find_counter_relations(u, opponent)
    if advantages:
        for adv in advantages:
            lines.append(f"{indent}✅ {adv}")
    if disadvantages:
        for dis in disadvantages:
            lines.append(f"{indent}⚠️ {dis}")


def format_vs_banner(lineup: MatchLineup) -> str:
    """生成 VS 总览 + 押注提示（第三条消息）。"""
    r = lineup.red
    b = lineup.blue

    if lineup.mode == "duel":
        title = "⚔️ 帝国3斗蛐蛐 · 单挑"
        red_str = f"🔴 {r.unit.name}"
        blue_str = f"🔵 {b.unit.name}"
    elif lineup.mode == "custom":
        title = "🎯 帝国3斗蛐蛐 · 自选对决"
        red_str = f"🔴 {r.unit.name} ×{r.count}"
        blue_str = f"🔵 {b.unit.name} ×{b.count}"
    elif lineup.mode == "rival":
        theme = lineup.rival_theme or "王中王"
        title = f"⚔️ 帝国3斗蛐蛐 · 王中王 · {theme}"
        red_str = f"🔴 {r.unit.name} ×{r.count}"
        blue_str = f"🔵 {b.unit.name} ×{b.count}"
    elif lineup.mode == "blacklist":
        title = "🎪 帝国3斗蛐蛐 · 黑名单乱斗"
        if r.is_multi or b.is_multi:
            red_parts = "+".join(f"{s.count}{s.unit.name}" for s in r.slots)
            blue_parts = "+".join(f"{s.count}{s.unit.name}" for s in b.slots)
            red_str = f"🔴 [{red_parts}]"
            blue_str = f"🔵 [{blue_parts}]"
        else:
            red_str = f"🔴 {r.unit.name} ×{r.count}"
            blue_str = f"🔵 {b.unit.name} ×{b.count}"
    elif r.is_multi or b.is_multi:
        title = "⚔️ 帝国3斗蛐蛐"
        red_parts = "+".join(f"{s.count}{s.unit.name}" for s in r.slots)
        blue_parts = "+".join(f"{s.count}{s.unit.name}" for s in b.slots)
        red_str = f"🔴 [{red_parts}]"
        blue_str = f"🔵 [{blue_parts}]"
    else:
        title = "⚔️ 帝国3斗蛐蛐"
        red_str = f"🔴 {r.unit.name} ×{r.count}"
        blue_str = f"🔵 {b.unit.name} ×{b.count}"

    lines = [
        title,
        f"{red_str}  VS  {blue_str}",
    ]
    # 时代 + 已激活类别科技（§3.10.6）
    if lineup.age is not None:
        from src.plugins.aoe3.i18n import t
        from src.plugins.aoe3.upgrades import active_category_techs
        age_names = {2: "商业", 3: "要塞", 4: "工业", 5: "帝王"}
        lines.append(f"⏳ 本局：{age_names.get(lineup.age, lineup.age)}时代（{lineup.age}）· 含逐时代改良")
        all_units = [s.unit for s in r.slots + b.slots]
        cats = active_category_techs(all_units, lineup.age)
        for name, hp_mult in cats:
            pct = round((hp_mult - 1.0) * 100)
            lines.append(f"   · {name}：血/攻 +{pct}%")
    if lineup.generic_tech_lines:
        lines.extend(lineup.generic_tech_lines)
    if lineup.mode == "blacklist":
        lines.append(
            f"⭐战力 🔴 {r.total_power:,.0f} vs 🔵 {b.total_power:,.0f}"
        )
        lines.append(
            f"👥总人数 🔴 {r.total_count} vs 🔵 {b.total_count}"
        )
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "@ 1 押红方 | @ 2 押蓝方",
        "入场券 5 金币 · @ 开战 直接开打",
    ])
    return "\n".join(lines)


def format_matchup_panel(lineup: MatchLineup) -> str:
    """兼容旧接口：生成完整对阵面板纯文本（CLI 等场景使用）。"""
    parts = []
    parts.append(format_side_panel(lineup.red, "red", lineup.mode, opponent=lineup.blue))
    parts.append("")
    parts.append(format_side_panel(lineup.blue, "blue", lineup.mode, opponent=lineup.red))
    parts.append("")
    parts.append(format_vs_banner(lineup))
    return "\n".join(parts)


def _unit_emoji(unit) -> str:
    """根据兵种类型返回对应 emoji。

    优先级：Ship > Elephant > Camel > Cavalry > Artillery > 步兵细分 > 兜底
    """
    tags = set(unit.type) if unit.type else set()
    # 按优先级匹配
    if tags & {"Ship", "AbstractWarShip"}:
        return "⛵"
    if tags & {"AbstractElephant"}:
        return "🐘"
    if tags & {"AbstractCamel"}:
        return "🐫"
    if tags & {"AbstractCavalry", "AbstractHeavyCavalry", "AbstractHandCavalry",
               "AbstractRangedCavalry", "AbstractLightCavalry", "AbstractLancer",
               "AbstractRangedHeavyCavalry"}:
        return "🐴"
    if tags & {"AbstractArtillery", "AbstractSiegeTrooper"}:
        return "💣"
    if tags & {"AbstractArcher"}:
        return "🏹"
    if tags & {"AbstractGunpowderTrooper", "AbstractMusketeer", "AbstractRifleman"}:
        return "🔫"
    if tags & {"AbstractPikeman"}:
        return "🗡️"
    if tags & {"AbstractMonk"}:
        return "✝️"
    if tags & {"Hero"}:
        return "👑"
    if tags & {"AbstractPet"}:
        return "🐾"
    if tags & {"Mercenary", "AbstractOutlaw", "MercType2"}:
        return "💰"
    if tags & {"AbstractVillager"}:
        return "👷"
    if tags & {"AbstractInfantry", "AbstractHeavyInfantry", "AbstractLightInfantry",
               "AbstractCoyoteMan", "AbstractRangedShockInfantry",
               "AbstractSkirmisher", "AbstractGrenadier",
               "AbstractNativeWarrior", "AbstractHandInfantry"}:
        return "⚔️"
    return "■"


def format_formation_panel(lineup: MatchLineup) -> str:
    """生成双方阵型排布面板文本（群聊开战前发送）。"""
    from .simulator import (
        ArmySlot as SimSlot,
        FormationRow,
        Side,
        compute_formation_rows,
    )

    def _format_row(row: FormationRow, num_rows: int) -> str:
        icons = ""
        for unit, count in row.slots:
            icons += _unit_emoji(unit) * count
        tag = "前排" if row.row_index == 0 else (
            "后排" if row.row_index == num_rows - 1 and num_rows > 2
            else ""
        )
        desc = row.label
        tag_str = f" ← {tag}" if tag else ""
        return f"  {row.row_index + 1}排 [{icons}] {desc}{tag_str}"

    def _side_text(
        side_lineup: Lineup,
        side: Side,
        emoji: str,
        label: str,
        reverse: bool = False,
    ) -> str:
        sim_army = [SimSlot(s.unit, s.count) for s in side_lineup.slots]
        rows: list[FormationRow] = compute_formation_rows(sim_army, side)
        num_rows = len(rows)

        lines: list[str] = []
        lines.append(f"{emoji} {label}阵型（{side_lineup.total_count}人，{num_rows}排）")

        display_rows = list(reversed(rows)) if reverse else rows
        for row in display_rows:
            lines.append(_format_row(row, num_rows))

        return "\n".join(lines)

    # 红方倒序（后排在上，前排靠近空地）
    # 蓝方正序（前排靠近空地，后排在下）
    red_text = _side_text(lineup.red, Side.RED, "🔴", "红方", reverse=True)
    blue_text = _side_text(lineup.blue, Side.BLUE, "🔵", "蓝方", reverse=False)

    gap = "      ─── 空地 ───"
    return f"{red_text}\n{gap}\n{blue_text}"


# =====================================================================
# 自选兵种对决
# =====================================================================

def resolve_unit_name(repo: UnitRepo, name: str) -> Unit | None:
    """根据玩家输入的兵种名解析为 Unit 对象。

    匹配策略：精确优先 → 模糊匹配；在候选里取第一个可参战单位。
    玩家可以选 ``BATTLE_BLACKLIST`` 彩蛋兵，但不可选：
    - ``is_excluded_unit``（含 ``_EXCLUDED_IDS``、yphc 战役村民等）
    - 村民（``AbstractVillager``，与押注池一致）
    必须有攻击力和 HP。
    """
    results = repo.search(name, limit=8)
    for u in results:
        if is_excluded_unit(u):
            continue
        if _is_villager(u):
            continue
        if not u.has_attack or u.hp <= 0:
            continue
        return u
    return None


def generate_custom_lineup(
    repo: UnitRepo,
    unit_names: list[str],
    *,
    budget: int = BUDGET,
    age: int | None = None,
    rng: random.Random | None = None,
) -> MatchLineup | str:
    """生成自选兵种对决阵容。

    参数：
      unit_names: 玩家输入的 1~2 个兵种名
      budget: 资源预算（双方共用）
      rng: 随机数生成器

    返回：
      成功 → MatchLineup
      失败 → str（错误提示文本）

    规则：
      - 选 1 种：玩家选的 = 红方，系统从正常池随机 1 种 = 蓝方
      - 选 2 种：第一个 = 红方，第二个 = 蓝方
      - 双方使用相同预算，数量 = budget ÷ cost（向下取整）
      - 双方都是单兵种时使用 LCM 算法平衡资源
      - 玩家可选黑名单兵种；系统随机时排除黑名单
    """
    if rng is None:
        rng = random.Random()

    if not unit_names or len(unit_names) > 2:
        return "⚠️ 请指定 1~2 个兵种名"

    # 解析玩家选的兵种
    resolved_units: list[Unit] = []
    for name in unit_names:
        u = resolve_unit_name(repo, name)
        if u is None:
            return (
                f"⚠️ 找不到兵种「{name}」"
                "（需可训练战斗单位；村民/战役专属/占位符不可自选）"
            )
        resolved_units.append(u)

    # 红方 = 第一个兵种
    red_unit = resolved_units[0]

    if len(resolved_units) == 2:
        # 选了 2 种：直接对打
        blue_unit = resolved_units[1]
    else:
        # 选了 1 种：系统从正常池随机对手（对手尊重时代限定；玩家明选不受限）
        pool = get_bet_pool(repo, age=age)
        # 排除玩家已选的兵种（不镜像对决）
        pool = [u for u in pool if u.id != red_unit.id]
        if not pool:
            return "⚠️ 兵种池为空，无法生成对手"
        blue_unit = rng.choice(pool)

    # 计算数量：使用 LCM 算法平衡资源（双方都是单兵种）
    cost_a = _unit_cost(red_unit)
    cost_b = _unit_cost(blue_unit)

    if cost_a <= 0:
        return f"⚠️ 兵种「{red_unit.name}」没有资源消耗数据，无法参战"
    if cost_b <= 0:
        return f"⚠️ 兵种「{blue_unit.name}」没有资源消耗数据，无法参战"

    lcm_budget = approx_lcm_budget(cost_a, cost_b, budget)

    red_count = max(1, lcm_budget // cost_a)
    blue_count = max(1, lcm_budget // cost_b)

    red = Lineup(slots=[UnitSlot(unit=red_unit, count=red_count)])
    blue = Lineup(slots=[UnitSlot(unit=blue_unit, count=blue_count)])

    logger.info(
        "自选阵容：LCM预算 %d → %d，🔴 %s ×%d (%d) vs 🔵 %s ×%d (%d) 差=%d",
        budget, lcm_budget,
        red_unit.name, red_count, red.total_cost,
        blue_unit.name, blue_count, blue.total_cost,
        abs(red.total_cost - blue.total_cost),
    )

    _apply_age_to_lineup(red, age)
    _apply_age_to_lineup(blue, age)
    return MatchLineup(red=red, blue=blue, mode="custom", age=age)


def generate_rival_lineup(
    repo: UnitRepo,
    theme_id: str,
    *,
    budget: int = BUDGET,
    age: int | None = None,
    rng: random.Random | None = None,
) -> MatchLineup | str:
    """生成王中王阵容：主题池内随机两兵种 + LCM（同自选）。"""
    from .rival_themes import filter_theme_pool, get_theme_by_id

    if rng is None:
        rng = random.Random()

    theme = get_theme_by_id(theme_id)
    if theme is None:
        return f"⚠️ 未知王中王主题 id：{theme_id}"

    pool = filter_theme_pool(get_bet_pool(repo, age=age), theme)
    if len(pool) < 2:
        return f"⚠️ 主题「{theme.title}」兵种池不足（仅 {len(pool)} 个）"

    red_unit, blue_unit = rng.sample(pool, 2)

    cost_a = _unit_cost(red_unit)
    cost_b = _unit_cost(blue_unit)
    if cost_a <= 0:
        return f"⚠️ 兵种「{red_unit.name}」没有资源消耗数据，无法参战"
    if cost_b <= 0:
        return f"⚠️ 兵种「{blue_unit.name}」没有资源消耗数据，无法参战"

    lcm_budget = approx_lcm_budget(cost_a, cost_b, budget)
    red_count = max(1, lcm_budget // cost_a)
    blue_count = max(1, lcm_budget // cost_b)

    red = Lineup(slots=[UnitSlot(unit=red_unit, count=red_count)])
    blue = Lineup(slots=[UnitSlot(unit=blue_unit, count=blue_count)])

    logger.info(
        "王中王阵容 [%s]：LCM %d → 🔴 %s ×%d vs 🔵 %s ×%d",
        theme.title, lcm_budget,
        red_unit.name, red_count, blue_unit.name, blue_count,
    )

    _apply_age_to_lineup(red, age)
    _apply_age_to_lineup(blue, age)
    return MatchLineup(
        red=red, blue=blue, mode="rival", rival_theme=theme.title, age=age,
    )
